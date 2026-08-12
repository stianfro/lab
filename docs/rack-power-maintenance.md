# Rack Power Maintenance

Use this runbook when work on rack power will stop all three Talos nodes, the
FRR router, the switch, and the devbox VM.

The devbox is a VM in the lab cluster. The devbox terminal will disconnect when
the VM stops. Complete the Mac handoff before you stop the devbox.

## Hosts

| Device | Address |
| --- | --- |
| Talos node 1 | `192.168.1.100` |
| Talos node 2 | `192.168.1.101` |
| Talos node 3 | `192.168.1.102` |
| FRR router | `192.168.1.159` |
| Devbox service | `192.168.1.51` |

## 1. Prepare the Mac

Do these steps on the Mac before you change the cluster. Do not rely on a
terminal, file, or chat session that exists only on devbox.

1. Pull this repository on the Mac.
2. Open this file on the Mac or on GitHub.
3. Open a second Mac terminal for the final shutdown commands.
4. Verify cluster access from the Mac:

   ```bash
   cd /path/to/lab
   direnv allow
   direnv exec . kubectl get nodes
   direnv exec . talosctl version \
     --nodes 192.168.1.100,192.168.1.101,192.168.1.102
   ssh stianfroystein@192.168.1.159 true
   ```

Keep this section available on the Mac after devbox stops:

```bash
cd /path/to/lab

direnv exec . kubectl wait \
  --for=delete vmi/devbox \
  --namespace devbox \
  --timeout=5m

until [[ "$(direnv exec . kubectl -n longhorn-system \
  get volume pvc-f41ea678-d780-48f8-9a39-ad3a925969ee \
  -o jsonpath='{.status.state}')" == detached ]]; do
  sleep 2
done

direnv exec . talosctl shutdown \
  --nodes 192.168.1.100,192.168.1.101,192.168.1.102 \
  --force \
  --wait=false

ssh stianfroystein@192.168.1.159 sudo systemctl poweroff
```

The `--force` option skips the Talos cordon and drain. Use it here only after
all persistent workloads are stopped and all Longhorn volumes are detached.

## 2. Check the Live State

Run these commands on devbox:

```bash
git status --short --branch
kubectl get nodes -o wide
flux get kustomizations -A
flux get helmreleases -A
kubectl get vm,vmi -A -o wide
kubectl get clusters.postgresql.cnpg.io -A -o wide
kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
kubectl -n longhorn-system get backuptargets.longhorn.io -o wide
```

Stop if the backup target is not available. Record all degraded volumes and
database faults before maintenance. Do not treat a pre-existing fault as a
shutdown failure during recovery.

Check all repositories and active sessions on devbox. Commit, push, or accept
any local work that must survive the shutdown.

## 3. Suspend Flux

Suspend Flux before you scale workloads to zero. This prevents Flux from
restoring them during the shutdown procedure.

```bash
flux suspend helmrelease --all --namespace flux-system
flux suspend kustomization --all --namespace flux-system
```

Verify that every item in `flux-system` has `SUSPENDED=True`:

```bash
flux get helmreleases --namespace flux-system
flux get kustomizations --namespace flux-system
```

## 4. Stop Persistent Workloads

Stop database clients first:

```bash
kubectl -n authentik scale \
  deploy/authentik-chart-server \
  deploy/authentik-chart-worker \
  --replicas=0

kubectl -n umami scale deploy/umami --replicas=0

kubectl -n minato-system scale \
  deploy/minato-admin \
  deploy/minato-api \
  deploy/minato-mcp \
  deploy/minato-zot \
  deploy/openfga \
  deploy/operator-controller-manager \
  deploy/portal \
  --replicas=0
```

Stop other persistent deployments and the OCP VM:

```bash
kubectl -n home-assistant scale \
  deploy/home-assistant deploy/matter-server --replicas=0
kubectl -n kemuri scale deploy/kemuri --replicas=0
kubectl -n monitoring scale deploy/kube-prom-stack-grafana --replicas=0
kubectl -n mosquitto scale deploy/mosquitto --replicas=0
kubectl -n openclaw scale deploy/openclaw --replicas=0

virtctl stop ocp-upgrade-lab --namespace ocp-upgrade-lab
kubectl wait --for=delete vmi/ocp-upgrade-lab \
  --namespace ocp-upgrade-lab --timeout=10m
```

Stop persistent StatefulSets. Stop the Prometheus operator before Prometheus,
so the operator does not restore the StatefulSet replica count.

First, confirm that Loki retains its PVC when it scales down. Do not scale Loki
to zero if either value is `Delete`:

```bash
kubectl -n loki get sts loki -o json | jq \
  '.spec.persistentVolumeClaimRetentionPolicy'
```

The expected values are:

```json
{
  "whenDeleted": "Retain",
  "whenScaled": "Retain"
}
```

The Loki HelmRelease sets `singleBinary.persistence.whenDeleted` and
`singleBinary.persistence.whenScaled` to `Retain`. Fix and reconcile those
settings before you continue if the live policy is not `Retain`.

```bash
kubectl -n registry scale sts/registry --replicas=0
kubectl -n loki scale sts/loki --replicas=0
kubectl -n vault scale sts/vault --replicas=0

kubectl -n monitoring scale \
  deploy/kube-prom-stack-kube-prome-operator --replicas=0
kubectl -n monitoring scale \
  sts/prometheus-kube-prom-stack-kube-prome-prometheus --replicas=0
```

Stop the CloudNativePG operator, then stop all PostgreSQL pods. Kubernetes gives
each database pod its configured termination grace period.

```bash
kubectl -n cnpg-system scale deploy/cloudnative-pg --replicas=0
kubectl delete pods --all-namespaces \
  --selector cnpg.io/cluster \
  --wait=true \
  --timeout=10m
```

Confirm that devbox is the only pod that still consumes a PVC:

```bash
kubectl get pods -A -o json | jq -r '
  .items[]
  | select([.spec.volumes[]? | select(has("persistentVolumeClaim"))] | length > 0)
  | [
      .metadata.namespace,
      .metadata.name,
      ([.spec.volumes[]?
       | select(has("persistentVolumeClaim"))
       | .persistentVolumeClaim.claimName]
       | join(","))
    ]
  | @tsv'
```

Wait until every Longhorn volume except the devbox volume is detached:

```bash
while kubectl -n longhorn-system get volumes.longhorn.io -o json | jq -e '
  [.items[]
   | select(
       .metadata.name != "pvc-f41ea678-d780-48f8-9a39-ad3a925969ee"
       and .status.state != "detached"
     )]
  | length > 0' >/dev/null; do
  sleep 2
done
```

## 5. Create Fresh Backups

Create one Longhorn system backup. The `always` policy creates a backup for
each volume. Longhorn can back up detached volumes. This can take several
minutes.

```bash
BACKUP="pre-power-$(date -u +%Y%m%d-%H%M%S)"

cat <<EOF | yq eval '.' - | kubectl apply -f -
apiVersion: longhorn.io/v1beta2
kind: SystemBackup
metadata:
  name: ${BACKUP}
  namespace: longhorn-system
spec:
  volumeBackupPolicy: always
EOF

watch kubectl -n longhorn-system get systembackup "${BACKUP}"
```

Do not continue until the system backup state is `Ready` and no backup is in
progress:

```bash
kubectl -n longhorn-system get systembackup "${BACKUP}" \
  -o jsonpath='{.status.state}{"\n"}'

kubectl -n longhorn-system get backups.longhorn.io -o json | jq -r '
  .items[]
  | select(.status.state != "Completed")
  | [.metadata.name, .status.state, .status.progress]
  | @tsv'
```

## 6. Stop Devbox

Confirm that the Mac terminal has the commands from section 1. Then run this as
the last command on devbox:

```bash
sudo sync
virtctl stop devbox --namespace devbox
```

The connection will close. Continue on the Mac.

## 7. Stop the Rack

On the Mac, run the saved commands from section 1. Wait for the Talos machines
and the FRR router to power off. Shut down any other storage or power-managed
host in the rack with its own supported procedure.

Move power cables only after the hosts are off. Move the switch after the hosts
are off.

## 8. Start the Rack

Use this order:

1. Start the switch.
2. Start the NFS backup host and any other network storage.
3. Start the FRR router.
4. Wait until `192.168.1.159` responds on Ethernet.
5. Start all three Talos nodes.

From the Mac, wait for Talos health. The `health` command uses one node as the
server and checks all three control-plane nodes:

```bash
direnv exec . talosctl health \
  --nodes 192.168.1.100 \
  --control-plane-nodes 192.168.1.100,192.168.1.101,192.168.1.102 \
  --wait-timeout 10m

direnv exec . kubectl get nodes -o wide
```

Resume the root Flux Kustomization first. Then resume all Flux resources and
request a reconciliation:

```bash
direnv exec . flux resume kustomization cluster --namespace flux-system
direnv exec . flux resume kustomization --all --namespace flux-system
direnv exec . flux resume helmrelease --all --namespace flux-system
direnv exec . just reconcile
```

Flux restores the scaled workloads and the desired VM state from Git. Wait for
devbox SSH before you reconnect:

```bash
until ssh -o BatchMode=yes -o ConnectTimeout=5 \
  stian@192.168.1.51 true; do
  sleep 5
done
```

## 9. Verify Recovery

Run these checks from the Mac or devbox:

```bash
direnv exec . talosctl health \
  --nodes 192.168.1.100 \
  --control-plane-nodes 192.168.1.100,192.168.1.101,192.168.1.102 \
  --wait-timeout 10m

kubectl get nodes -o wide
flux check
flux get kustomizations -A
flux get helmreleases -A
kubectl get vm,vmi -A -o wide
kubectl get clusters.postgresql.cnpg.io -A -o wide
kubectl -n longhorn-system get nodes.longhorn.io
kubectl -n longhorn-system get volumes.longhorn.io \
  -o custom-columns='NAME:.metadata.name,STATE:.status.state,ROBUSTNESS:.status.robustness,NODE:.status.currentNodeID'
just smoke-public-sites
```

Verify the wired FRR router and all three BGP sessions:

```bash
ssh stianfroystein@192.168.1.159 \
  'nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status; \
   sudo vtysh -c "show bgp summary"'
```

The recovery is complete when:

- all three Kubernetes nodes are Ready;
- Talos health passes;
- etcd has three members and no alarms;
- all Flux resources are resumed and Ready;
- Longhorn nodes are Ready and schedulable;
- no new Longhorn volume is faulted or degraded;
- database state matches the recorded preflight state;
- both expected VMs are running;
- the public smoke test passes;
- the FRR router uses `lan-wired` and has three BGP sessions.
