# Lab Operations

## Bootstrap

```bash
just bootstrap
just reconcile
```

`just bootstrap` installs Flux from `clusters/talos/flux-system`. Flux then
reconciles `clusters/talos`.

## Flux

```bash
flux check
flux get sources git -A
flux get sources helm -A
flux get kustomizations -A
flux get helmreleases -A
flux reconcile kustomization cluster -n flux-system --with-source
```

## Apps

Apps live under `apps/`. Add the app files there, then add one explicit Flux
`Kustomization` in `clusters/talos/apps.yaml`.

For Helm charts:

1. Add or reuse a `HelmRepository` in `clusters/talos/sources.yaml`.
2. Add `apps/<name>/helmrelease.yaml`.
3. Preserve `spec.releaseName` if taking over an existing live chart.
4. Put dependent custom resources in a separate `*-config` directory if the CRD
   is installed by the chart.

## Talos

```bash
just env
just patch
talosctl --endpoints $CP_IPS health
talosctl --endpoints $CP_IPS logs <service>
```

Talos files live under `talos/`. Cilium stays in Talos bootstrap because the
cluster needs CNI before Flux can run.

## Gateway

Internal services use the `eg` Gateway and `*.talos.froystein.jp`.
Public services use the `eg-public` Gateway and `*.froystein.jp` through
Cloudflare Tunnel.

```bash
kubectl get gateways,httproutes -A
kubectl get svc -n envoy-gateway-system
```

## Secrets

Most synced secrets use Vault Secrets Operator:

```bash
kubectl get vaultauths,vaultconnections,vaultstaticsecrets -A
```

Manual live secrets to preserve unless intentionally migrated:

- `authentik/authentik-secrets`
- `monitoring/grafana-github-oauth`

## Manual Tasks

One-shot manifests live under `tasks/` and are not reconciled by Flux. Apply them
manually when needed, for example:

```bash
kubectl apply -f tasks/ocp-upgrade-lab/import-iso-job.yaml
```
