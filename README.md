# Lab

Homelab Kubernetes cluster running Talos Linux on three Minisforum UM790 Pro
mini PCs. The cluster is managed with Flux GitOps.

![lab](https://github.com/user-attachments/assets/7610c388-37d5-419e-9917-5a834fe79f1c)

## Hardware

- 3x Minisforum UM790 Pro Mini-PC
- 1x TP-Link TL-SG108-M2 8-Port 2.5G Switch

## Network

| Hostname | IP            | MAC               |
| -------- | ------------- | ----------------- |
| talos-0  | 192.168.1.100 | 58-47-CA-7F-C3-47 |
| talos-1  | 192.168.1.101 | 58-47-CA-7F-C2-9C |
| talos-2  | 192.168.1.102 | 58-47-CA-7F-C3-46 |

## GitOps

- Flux is bootstrapped from `clusters/talos/flux-system`.
- The root Flux `Kustomization` reconciles `clusters/talos`.
- Each app or infrastructure concern has an explicit Flux `Kustomization` in
  `clusters/talos/apps.yaml`.
- Helm charts are represented as Flux `HelmRelease` objects in the app
  directories.
- Argo CD, Kargo, and Argo Rollouts are intentionally not part of this setup.

## Bootstrap

```bash
just bootstrap
just reconcile
```

## Common Checks

```bash
flux check
flux get sources git -A
flux get sources helm -A
flux get kustomizations -A
flux get helmreleases -A
kubectl get pods -A
```

## Talos

Talos machine configuration lives under `talos/`.

- `talos/controlplane.yaml`
- `talos/worker.yaml`
- `talos/patches/`
- `talos/manifests/cilium.yaml`

Cilium remains a Talos bootstrap manifest so a fresh cluster has CNI before
Flux starts. Metrics Server and kubelet serving certificate approver are
Flux-managed apps.
