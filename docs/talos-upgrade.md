# Talos And Kubernetes Upgrade Runbook

Validated on the 2026-08-22 upgrades: Talos 1.12.4 to 1.13.9,
Kubernetes 1.34.1 to 1.35.4, and Kubernetes 1.35.4 to 1.36.3.

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
direnv exec . talosctl --nodes 192.168.1.100 upgrade-k8s --to <version> --dry-run
just upgrade-k8s <version>
```

Always read the dry-run first. It prints the full manifest diff; expect
only `Pruned`, `configured`, and `unchanged` lines that you can explain.

Then verify: `kubectl get nodes` shows the new version on all nodes,
coredns runs, Cilium DaemonSet is 3/3 (see warning below), Longhorn
volumes healthy, Flux green, and a scratch PVC pod works.

## WARNING: bootstrap manifest pruning can delete Cilium

`talosctl upgrade-k8s` re-applies the Talos bootstrap manifests with
inventory-based pruning (Talos 1.13+, inventory in the ConfigMap
`kube-system/talos-bootstrap-manifests-inventory`). It applies the
`Manifest` resources that Talos already holds (`talosctl get manifests`),
NOT a fresh download: Talos fetches `cluster.network.cni.urls` and
`cluster.extraManifests` when the machine config changes, then caches
the result. On 2026-08-22 a stale CNI URL in the live machine config
(`/manifests/cilium.yaml` instead of `/talos/manifests/cilium.yaml`)
made that cache empty, and the upgrade pruned the live Cilium DaemonSet
and operator. Later the same day the cache still held an old render
(chart 1.18.3) after the repo had moved to 1.20.1; the dry-run showed
it would downgrade Cilium.

Before every `upgrade-k8s`:

```bash
# every URL must return 200
direnv exec . talosctl --nodes 192.168.1.100 get machineconfig v1alpha1 -o yaml \
  | grep -oE 'https://[^" ]+\.(yaml|yml)' | sort -u | xargs -I{} curl -sL -o /dev/null -w '%{http_code} {}\n' {}

# the cached Cilium manifest must match main (image tag and object list)
direnv exec . talosctl --nodes 192.168.1.100 get manifests \
  '05-https://raw.githubusercontent.com/stianfro/lab/refs/heads/main/talos/manifests/cilium.yaml' -o yaml \
  | grep -oE 'quay.io/cilium/cilium:v[0-9.]+' | sort -u
```

If the cache is stale, force a refetch on all nodes: RFC 6902 `replace`
`/cluster/network/cni/urls/0` with a commit-pinned URL
(`https://raw.githubusercontent.com/stianfro/lab/<sha>/talos/manifests/cilium.yaml`),
wait for the new `Manifest` to appear, then `replace` it back to the
`refs/heads/main` URL. Both patches apply with `--mode=no-reboot`. Then
re-run the dry-run.

The Cilium bootstrap manifest is rendered with `just render-cilium-bootstrap`
from the Flux HelmRelease values, with the Helm-generated TLS Secrets
(`cilium-ca`, `hubble-server-certs`, `hubble-relay-client-certs`) stripped.
The repo is public, and the live secrets belong to the HelmRelease. The
1.36.3 upgrade pruned `cilium-ca` and `hubble-server-certs` once (they were
in the old inventory); Flux drift correction recreated both from the Helm
release storage within a minute, with the same data, so Hubble stayed
consistent. They are no longer in the inventory. `helm template` also
renders an extra empty `--k8s-api-server-urls=` agent arg that the live
Helm release lacks; Talos applies it and Flux drift correction reverts it,
so expect two Cilium agent rollouts during `upgrade-k8s`. If hubble-relay
still crashloops with "unknown certificate authority" afterwards: delete
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
