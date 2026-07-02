# Minato lab prerequisites

Minato app acceptance runs in the Talos lab after changes merge to Minato `main`.
The lab is not a required pull request gate. Local smoke tests and Minato CI stay
as the pre-merge signal.

## Managed here

This repo owns the cluster prerequisites Minato needs:

- Knative Serving with Gateway API enabled.
- kpack and the Minato-approved ClusterBuilder set.
- A dedicated MetalLB pool for Minato tenant Gateways: `192.168.1.200-192.168.1.250`.

Minato itself is deployed from the Minato repo with `just deploy-lab` against the
`admin@talos-homelab` context.

## DNS

Create DNS-only Cloudflare records for the lab:

- `minato.talos.froystein.jp` to `192.168.1.20`
- `minato-mcp.talos.froystein.jp` to `192.168.1.20`
- `*.acme.talos.froystein.jp` to `192.168.1.200`

The tenant wildcard points at the first Minato tenant Gateway IP. Keep it DNS-only
so TLS terminates in the lab through cert-manager and Envoy Gateway.

## Checks

```bash
just validate
flux reconcile kustomization cluster -n flux-system --with-source
kubectl -n knative-serving wait knativeserving/knative-serving --for=condition=Ready --timeout=15m
kubectl -n kpack rollout status deploy/kpack-controller --timeout=5m
kubectl -n kpack rollout status deploy/kpack-webhook --timeout=5m
kubectl get clusterbuilder
```
