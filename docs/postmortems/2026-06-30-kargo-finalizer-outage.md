# Postmortem: Kargo Finalizer Outage During Flux Migration

Date: 2026-06-30

## Summary

During the live cleanup phase after migrating GitOps from Argo CD to Flux, production namespaces for the website and blog were deleted.

Affected services:

- `https://froystein.jp/`
- `https://www.froystein.jp/`
- `https://blog.froystein.jp/`

The namespaces `froystein-jp` and `blog` entered `Terminating` after Kargo custom resources were removed. Their contents were deleted, then the namespace objects remained stuck because they still had a stale Kargo finalizer:

```text
kargo.akuity.io/finalizer
```

Flux could not recreate resources while the namespaces were stuck in `Terminating`. Service was restored by removing the stale namespace finalizers and forcing Flux to reconcile the affected applications.

## Impact

- The production website was unavailable.
- The production blog was unavailable or at risk of full loss while the namespace was terminating.
- Kubernetes resources in both production namespaces were deleted and then recreated by Flux.
- No persistent data loss was identified. Both workloads are static site deployments.

## Detection

The issue was detected by the owner after the cleanup work:

- `https://froystein.jp/` was down.
- The blog appeared to be near deletion.

Initial local checks from the Codex sandbox could not resolve public DNS or reach the Kubernetes API through the default kubeconfig hostname. Diagnosis continued by talking directly to the control plane IP:

```bash
kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig get ns
```

This showed:

```text
blog           Terminating
froystein-jp   Terminating
```

## Root Cause

Kargo was removed before accounting for all resources and finalizers it had placed on production project namespaces.

The cleanup removed Kargo controllers, webhooks, CRDs, and custom resources. Kargo `Project` resources existed for:

- `blog`
- `froystein-jp`

When those Kargo resources were deleted as part of CRD cleanup, Kubernetes garbage collection and stale Kargo metadata caused the related namespaces to be marked for deletion. Because the Kargo controller and webhook service were already gone, the namespaces were left stuck with `kargo.akuity.io/finalizer`.

Flux then reported the affected app Kustomizations as blocked because it cannot apply resources into a namespace that is terminating.

Example Flux state during the incident:

```text
blog          False    timeout waiting for: [Namespace/blog status: 'Terminating']
froystein-jp Unknown  Reconciliation in progress
```

## Contributing Factors

- Kargo had been experimental, but it still had live production project resources.
- The cleanup focused on removing old controllers and CRDs, not on identifying namespace ownership and finalizers first.
- Kargo webhooks were removed before finalizers on all Kargo-managed resources were cleared.
- Production namespaces shared names with Kargo projects, which made the blast radius larger than expected.
- There was no preflight query for finalizers on namespaces before deleting Kargo CRDs.
- There was no written decommission checklist for controllers that install finalizers, webhooks, or CRDs.

## Recovery

Recovery steps used:

1. Confirmed both production namespaces were stuck in `Terminating`:

   ```bash
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig get ns blog froystein-jp
   ```

2. Confirmed namespace contents were already removed and that only the stale Kargo finalizer remained:

   ```bash
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig get ns blog -o jsonpath='{.metadata.finalizers}'
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig get ns froystein-jp -o jsonpath='{.metadata.finalizers}'
   ```

3. Removed the stale Kargo finalizer from both namespaces:

   ```bash
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig patch ns blog --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]'
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig patch ns froystein-jp --type=json -p='[{"op":"remove","path":"/metadata/finalizers"}]'
   ```

4. Triggered Flux reconciliation:

   ```bash
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig -n flux-system annotate gitrepository.source.toolkit.fluxcd.io lab reconcile.fluxcd.io/requestedAt=<timestamp> --overwrite
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig -n flux-system annotate kustomization.kustomize.toolkit.fluxcd.io cluster reconcile.fluxcd.io/requestedAt=<timestamp> --overwrite
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig -n flux-system annotate kustomization.kustomize.toolkit.fluxcd.io blog reconcile.fluxcd.io/requestedAt=<timestamp> --overwrite
   kubectl --server https://192.168.1.100:6443 --kubeconfig ./kubeconfig -n flux-system annotate kustomization.kustomize.toolkit.fluxcd.io froystein-jp reconcile.fluxcd.io/requestedAt=<timestamp> --overwrite
   ```

5. Verified both namespaces were recreated and active:

   ```text
   blog           Active
   froystein-jp   Active
   ```

6. Verified deployments were ready:

   ```text
   blog          available=2 ready=2 desired=2
   froystein-jp  available=2 ready=2 desired=2
   ```

7. Verified Gateway API routes were accepted and references were resolved:

   ```text
   blog          Accepted=True ResolvedRefs=True
   froystein-jp  Accepted=True ResolvedRefs=True
   ```

8. Verified in-cluster HTTP through the same public Envoy service used by Cloudflare Tunnel:

   ```text
   Host: froystein.jp       HTTP/1.1 200 OK
   Host: blog.froystein.jp  HTTP/1.1 200 OK
   ```

## What Went Well

- Flux recreated the production resources once the namespace blockers were removed.
- The apps were stateless static site deployments, so resource recreation was enough to restore service.
- Gateway API status and in-cluster HTTP checks gave a clear recovery signal.
- Direct control-plane IP access allowed diagnosis even when local DNS resolution in the sandbox failed.

## What Went Wrong

- Kargo was treated as an unused experiment, but it still had live production project resources.
- Controller decommissioning happened in the wrong order.
- Finalizers and owner relationships were not checked before deleting CRDs.
- The recovery required manual finalizer removal during an outage.
- The initial cleanup validation missed the production namespace deletion risk.

## Prevention

Before removing any Kubernetes controller that owns CRDs, webhooks, or finalizers:

1. List all custom resources for that controller.
2. List owner references and finalizers on related namespaces and resources.
3. Remove or migrate custom resources while the controller is still running when possible.
4. Remove finalizers only after understanding what cleanup they were meant to perform.
5. Remove webhooks after finalizers and custom resources are gone.
6. Remove CRDs last.
7. Run targeted production checks after each cleanup phase.

Useful checks:

```bash
kubectl get ns -o jsonpath='{range .items[*]}{.metadata.name}{" finalizers="}{.metadata.finalizers}{"\n"}{end}'
kubectl get crd | egrep 'kargo|argoproj|rollout'
kubectl api-resources | egrep 'kargo|argoproj|rollout'
kubectl get validatingwebhookconfiguration,mutatingwebhookconfiguration | egrep 'kargo|argoproj|rollout'
```

## Action Items

- [x] Add a controller decommission checklist to `docs/lab-operations.md`.
- [x] Add a preflight command set for finding namespace finalizers before deleting CRDs.
  This is available as `just controller-decommission-preflight <pattern>`.
- [x] Add a production smoke test command for `froystein.jp` and `blog.froystein.jp`.
  This is available as `just smoke-public-sites`.
- [x] Review whether any stale `kargo.akuity.io/finalizer` remains anywhere in the cluster.
  On 2026-06-30, `just controller-decommission-preflight kargo` found no Kargo
  finalizers or owner references. It did find the `kargo-cluster-secrets`
  namespace by name, which needs a separate keep-or-delete decision.
- [x] Keep the Flux migration follow-up list updated with this incident.
- [x] Avoid deleting CRDs for a removed controller until all related custom resources and finalizers are accounted for.
  The controller decommission checklist now states that CRDs are deleted last.
