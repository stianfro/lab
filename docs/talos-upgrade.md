# Talos And Kubernetes Upgrade Runbook

Validated on the 2026-08-22 upgrade: Talos 1.12.4 to 1.13.9 and
Kubernetes 1.34.1 to 1.35.4.

## Rules

- Upgrade one Talos minor at a time, one node at a time.
- Upgrade Talos first, then Kubernetes, one k8s minor at a time.
- Never start while a node is down, a Longhorn volume is degraded, or a
  Flux kustomization is not ready.
- Check CNI and storage compatibility before picking the k8s target
  (Cilium and Longhorn support matrices).
- The installer image keeps the same Image Factory schematic ID; only
  the version tag changes. Kernel args baked into the schematic carry
  over automatically.

## Preflight

```bash
direnv exec . talosctl --nodes $CP_IPS version --short
direnv exec . talosctl --nodes $CP_IPS etcd status
kubectl get nodes
flux get kustomizations -A
kubectl -n longhorn-system get volumes.longhorn.io
curl -sI https://factory.talos.dev/image/<schematic>/<new-version>/metal-amd64.iso  # expect 200
```

## Talos upgrade

Use a talosctl client that matches the SERVER version for the upgrade
call. A newer client's gRPC keepalives kill the long upgrade RPC
against older apid (GoAway too_many_pings), which aborts the upgrade
mid-install. Download the matching client from
`https://github.com/siderolabs/talos/releases/download/<server-ver>/talosctl-darwin-arm64`.

Per node (order: 101, 100, 102; use `--endpoints` of a node that is
NOT being upgraded so the stream survives the reboot):

```bash
just upgrade-node 192.168.1.101 v1.13.9
```

Between nodes, repeat the preflight gates and verify
`talosctl read /proc/cmdline` still contains the NVMe args.

Rollback for a node that misbehaves on the new image:
`talosctl rollback --nodes <ip>` (A/B boot).

## Kubernetes upgrade

```bash
just upgrade-k8s 1.35.4
```

Then verify: `kubectl get nodes` shows the new version on all nodes,
coredns runs, Cilium DaemonSet is 3/3 (see warning below), Longhorn
volumes healthy, Flux green, and a scratch PVC pod works.

## WARNING: bootstrap manifest pruning can delete Cilium

`talosctl upgrade-k8s` re-applies the Talos bootstrap manifests with
inventory-based pruning (Talos 1.13+). It fetches
`cluster.network.cni.urls` and `cluster.extraManifests` at that moment.
If a URL is wrong or unreachable, the objects it previously created
are PRUNED from the cluster. On 2026-08-22 this deleted the live
Cilium DaemonSet and operator because the live machine config carried
a stale CNI URL (`/manifests/cilium.yaml` instead of
`/talos/manifests/cilium.yaml`).

Before every `upgrade-k8s`:

```bash
# every URL must return 200
direnv exec . talosctl --nodes 192.168.1.100 get machineconfig v1alpha1 -o yaml \
  | grep -oE 'https://[^" ]+\.(yaml|yml)' | sort -u | xargs -I{} curl -s -o /dev/null -w '%{http_code} {}\n' {}
```

The Cilium bootstrap manifest is rendered with `just render-cilium-bootstrap`
from the Flux HelmRelease values, with the Helm-generated TLS Secrets
(`cilium-ca`, `hubble-server-certs`, `hubble-relay-client-certs`) stripped.
The repo is public, and the live secrets belong to the HelmRelease. The
inventory from before 2026-08-22 still lists `cilium-ca` and
`hubble-server-certs`, so the next `upgrade-k8s` prunes them once. If
hubble-relay then crashloops with "unknown certificate authority": delete
the three secrets, run `flux reconcile helmrelease cilium -n flux-system
--force`, wait for Ready, then `kubectl -n kube-system rollout restart
ds/cilium ds/cilium-envoy deploy/hubble-relay deploy/hubble-ui`.

Recovery if the CNI is pruned anyway:
`kubectl apply -f talos/manifests/cilium.yaml --server-side --force-conflicts`,
then fix the URL in the live machine config (RFC 6902 replace on
`/cluster/network/cni/urls`; strategic merge APPENDS to lists).

## After the upgrade

- Sync the repo pins: `talos/controlplane.yaml` and `talos/worker.yaml`
  (installer tag, kubelet and control plane images),
  `netboot/init/netboot-init.sh` and `netboot/stage.sh` VERSION,
  `ansible/devbox/group_vars/devboxes.yaml` (talosctl/kubectl),
  CLAUDE.md and AGENTS.md.
- On the netboot host: `git pull`, delete `netboot/http/talos/`, re-up
  the stack so the PXE mirror refetches the new version.
- Run `just devbox-converge` to roll the devbox CLI tools.
- Note: `talosctl upgrade` does not update `machine.install.image` in
  the live config; patch it to the new tag so live matches the repo.
