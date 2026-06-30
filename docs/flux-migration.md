# Flux Migration Notes

Date: 2026-06-29

## Current State Assessment

- The cluster is Kubernetes `v1.34.1` on Talos `v1.12.4`.
- Argo CD is currently installed and managing applications through nested
  ApplicationSets.
- Flux is not installed before this migration.
- `flux check --pre` passed against the live cluster.
- Live cluster state wins over the old repo layout.

Important live differences recorded before conversion:

- `vllm` is absent in the live namespace and is intentionally not recreated.
- `ocp-upgrade-lab` has a running VM and LoadBalancer service. Its ISO import
  Job has completed and is moved to `tasks/` so Flux does not recreate it.
- `tempo` has stale remnants but no workload or service. It should be cleaned up,
  not recreated.
- `authentik-db` is synced but degraded because `authentik-pg-1` is unhealthy.
- `authentik/authentik-secrets` and `monitoring/grafana-github-oauth` are live
  manual secrets and are not replaced by this migration.
- External `blog` and `froystein.jp` env branches contain raw `manifests.yaml`
  files, so this repo wraps them with small kustomizations.

## Bootstrap Manifest Classification

Keep in Talos:

- Cilium CNI at `talos/manifests/cilium.yaml`.
- API server OIDC flags in `talos/patches/apiserver-oidc.yaml`.

Move to Flux:

- Metrics Server, now `apps/metrics-server`.
- kubelet-serving-cert-approver, now `apps/kubelet-serving-cert-approver`.

Remove:

- Argo CD bootstrap and ApplicationSets.
- Kargo resources.
- Argo Rollouts resources.

## New Flux Shape

- `clusters/talos/flux-system` installs Flux and points it at this repo.
- `clusters/talos/sources.yaml` contains Helm chart sources.
- `clusters/talos/apps.yaml` contains explicit Flux `Kustomization` objects.
- App directories contain either plain Kubernetes manifests or Flux
  `HelmRelease` manifests.

Helm release names are preserved for live takeover, including:

- `authentik-chart`
- `cert-manager-chart`
- `longhorn-chart`
- `kube-prom-stack`
- `vault`
- `vault-secrets-operator`

## Migration Order

1. Merge and push the repo changes.
2. Stop Argo reconciliation without deleting workloads:

   ```bash
   kubectl --kubeconfig ./kubeconfig -n argocd scale sts argocd-application-controller --replicas=0
   kubectl --kubeconfig ./kubeconfig -n argocd scale deploy argocd-applicationset-controller argocd-notifications-controller --replicas=0
   ```

3. Bootstrap Flux:

   ```bash
   kubectl --kubeconfig ./kubeconfig apply -f clusters/talos/flux-system/gotk-components.yaml
   kubectl --kubeconfig ./kubeconfig wait --for=condition=Established crd/gitrepositories.source.toolkit.fluxcd.io crd/kustomizations.kustomize.toolkit.fluxcd.io --timeout=60s
   kubectl --kubeconfig ./kubeconfig -n flux-system rollout status deployment/source-controller
   kubectl --kubeconfig ./kubeconfig -n flux-system rollout status deployment/kustomize-controller
   kubectl --kubeconfig ./kubeconfig -n flux-system rollout status deployment/helm-controller
   kubectl --kubeconfig ./kubeconfig apply -f clusters/talos/flux-system/gotk-sync.yaml
   flux --kubeconfig ./kubeconfig reconcile kustomization cluster -n flux-system --with-source
   ```

4. Verify Flux health:

   ```bash
   flux --kubeconfig ./kubeconfig check
   flux --kubeconfig ./kubeconfig get sources git -A
   flux --kubeconfig ./kubeconfig get sources helm -A
   flux --kubeconfig ./kubeconfig get kustomizations -A
   flux --kubeconfig ./kubeconfig get helmreleases -A
   ```

5. Remove Argo finalizers before deleting Argo objects:

   ```bash
   kubectl --kubeconfig ./kubeconfig -n argocd patch applications.argoproj.io --all --type=merge -p '{"metadata":{"finalizers":[]}}'
   kubectl --kubeconfig ./kubeconfig -n argocd delete applicationsets.argoproj.io --all
   kubectl --kubeconfig ./kubeconfig -n argocd delete applications.argoproj.io --all
   ```

6. Remove obsolete controllers and CRDs after Flux is ready:

   ```bash
   kubectl --kubeconfig ./kubeconfig delete ns argocd kargo argo-rollouts --ignore-not-found
   kubectl --kubeconfig ./kubeconfig delete crd applications.argoproj.io applicationsets.argoproj.io appprojects.argoproj.io --ignore-not-found
   kubectl --kubeconfig ./kubeconfig delete crd rollouts.argoproj.io analysisruns.argoproj.io analysistemplates.argoproj.io clusteranalysistemplates.argoproj.io experiments.argoproj.io --ignore-not-found
   kubectl --kubeconfig ./kubeconfig delete crd projects.kargo.akuity.io projectconfigs.kargo.akuity.io warehouses.kargo.akuity.io stages.kargo.akuity.io freights.kargo.akuity.io promotions.kargo.akuity.io promotiontasks.kargo.akuity.io clusterpromotiontasks.kargo.akuity.io clusterconfigs.kargo.akuity.io --ignore-not-found
   ```

7. Clean stale resources:

   ```bash
   kubectl --kubeconfig ./kubeconfig delete ns vllm blog-pr-12 blog-pr-14 tempo --ignore-not-found
   ```

## Validation Commands

```bash
flux --kubeconfig ./kubeconfig check
flux --kubeconfig ./kubeconfig get sources git -A
flux --kubeconfig ./kubeconfig get sources helm -A
flux --kubeconfig ./kubeconfig get kustomizations -A
flux --kubeconfig ./kubeconfig get helmreleases -A
kubectl --kubeconfig ./kubeconfig get pods -A
kubectl --kubeconfig ./kubeconfig get gateways,httproutes -A
kubectl --kubeconfig ./kubeconfig get vaultstaticsecrets -A
kubectl --kubeconfig ./kubeconfig get vm -A
kubectl --kubeconfig ./kubeconfig get cluster.postgresql.cnpg.io -A
kubectl --kubeconfig ./kubeconfig get applications.argoproj.io,applicationsets.argoproj.io -A
```

Fresh bootstrap expectation:

- Talos applies Cilium.
- `just bootstrap` applies Flux.
- Flux reconciles `clusters/talos`.
- All apps converge through Flux without Argo CD, Kargo, or Argo Rollouts.

## Follow-Ups

- Repair or rebuild `authentik-pg-1`.
- Decide whether to move `authentik-secrets` and `grafana-github-oauth` into
  VaultStaticSecret resources.
- Add `kustomization.yaml` to external `blog` and `froystein.jp` env branches.
- The Kargo finalizer incident is documented in
  `docs/postmortems/2026-06-30-kargo-finalizer-outage.md`. Before any further
  controller or CRD cleanup, run `just controller-decommission-preflight
  <pattern>` and run targeted smoke tests, for example `just
  smoke-public-sites`.
- Decide whether to remove the leftover `kargo-cluster-secrets` namespace. It
  matched the Kargo preflight by name on 2026-06-30, but no Kargo finalizers or
  owner references remained.
- Create a reusable "how to use lab" guide for coding agents in other projects,
  so an agent can deploy a dev environment to this cluster from another repo.
- Perform Talos version updates as a separate task.
