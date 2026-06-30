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

## Production Smoke Test

Use this after Gateway, Cloudflare Tunnel, or production app changes:

```bash
just smoke-public-sites
```

The recipe creates a short-lived curl pod and sends requests through the same
`eg-public` Envoy service that Cloudflare Tunnel uses. It checks:

- `froystein.jp`
- `www.froystein.jp`
- `blog.froystein.jp`

If local DNS for the kubeconfig server name is broken, point kubectl directly at
a control-plane IP:

```bash
KUBECTL='kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig' just smoke-public-sites
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

## Controller Decommissioning

Use this checklist before removing any controller that owns CRDs, webhooks, or
finalizers. Examples: Argo CD, Argo Rollouts, Kargo, cert-manager, Longhorn,
Vault Secrets Operator, CloudNativePG.

Never delete CRDs first. CRDs are last.

1. Run the preflight recipe:

   ```bash
   just controller-decommission-preflight kargo
   ```

   If local DNS for the kubeconfig server name is broken:

   ```bash
   KUBECTL='kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig' just controller-decommission-preflight kargo
   ```

2. Read every section of the output:

   - matching CRDs
   - matching API resources
   - matching webhooks
   - namespaces with matching names
   - finalizers on namespaces and other resources
   - owner references on cluster-scoped and namespaced resources

3. While the controller is still running, delete or migrate its custom
   resources.
4. Confirm the finalizer and owner reference sections are empty, or document why
   each remaining item is safe.
5. Remove admission webhooks only after custom resources and finalizers are
   handled.
6. Delete the controller namespace only after webhook and finalizer risk is
   understood.
7. Delete CRDs last.
8. Re-run the preflight recipe and confirm no unexpected matches remain.
9. Run affected app checks. For public sites, run:

   ```bash
   just smoke-public-sites
   ```

Do not continue if the preflight output shows finalizers or owner references
that you cannot explain.
