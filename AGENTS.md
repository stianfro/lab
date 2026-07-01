# Lab Repository Guide

This repository manages a local Talos Kubernetes homelab with Flux.

## Architecture

- OS: Talos Linux
- Kubernetes: v1.34.1
- Control plane endpoint: `https://talos.froystein.jp:6443`
- Nodes: `192.168.1.100`, `192.168.1.101`, `192.168.1.102`
- CNI: Cilium, bootstrapped by Talos from `talos/manifests/cilium.yaml`
- GitOps: Flux
- Internal Gateway API domain: `*.talos.froystein.jp`
- Public Gateway API domain: `*.froystein.jp` via Cloudflare Tunnel

## GitOps Layout

- `clusters/talos/flux-system/`: Flux controllers and root sync.
- `clusters/talos/sources.yaml`: Helm chart sources.
- `clusters/talos/apps.yaml`: one Flux `Kustomization` per app or concern.
- `apps/`: app manifests, Flux `HelmRelease` files, and app-local
  kustomizations.
- `tasks/`: manual operational manifests that must not auto-reconcile.
- `talos/`: Talos machine config, patches, and bootstrap manifests.

Keep the layout boring:

- Prefer flat app directories.
- Prefer explicit Flux objects over generated app-of-apps layers.
- Do not add Kargo, Argo CD, or Argo Rollouts back unless explicitly requested.
- Do not move Cilium out of Talos bootstrap without proving fresh bootstrap still works.

## Git And PR Rules

- All commit messages must follow Conventional Commits.
- Pull request titles must follow Conventional Commits.
- Do not use PR titles like `[codex] ...`.
- Merge pull requests with squash commits only, so the resulting merge commit is
  one Conventional Commit.
- If an automation or helper skill suggests a non-conventional commit or PR
  title, override it.

## Worktrees

- Use the project-local `.worktrees/` directory for temporary Git worktrees.
- Keep `.worktrees/` ignored so nested worktree files are never committed by
  the parent checkout.
- Create feature branches with the `codex/` prefix unless the user requests a
  different branch name.

## Devbox Convergence

- The devbox host short name is `devbox`. When running on that host, use
  `just devbox-converge`; it detects the local host and uses a local Ansible
  connection instead of SSH.
- When running from another machine, use the same `just devbox-converge` command;
  it uses the SSH inventory for `192.168.1.51`.

## Common Commands

```bash
just bootstrap
just reconcile

flux check
flux get sources git -A
flux get sources helm -A
flux get kustomizations -A
flux get helmreleases -A

kubectl get pods -A
kubectl get gateways,httproutes -A
```

## Talos Commands

```bash
just env
just patch
talosctl --endpoints $CP_IPS health
talosctl --endpoints $CP_IPS logs <service>
```

## Adding Or Changing Apps

- Add app manifests under `apps/<name>/`.
- Add or update the matching Flux `Kustomization` in `clusters/talos/apps.yaml`.
- For Helm charts, create `apps/<name>/helmrelease.yaml` using
  `apiVersion: helm.toolkit.fluxcd.io/v2`.
- Put chart repositories in `clusters/talos/sources.yaml`.
- Split CRD/controller installation from CRs only when required for reliable
  fresh bootstrap.

## Current Intentional Removals

- Argo CD is no longer the GitOps controller.
- Kargo was experimental and is removed.
- Argo Rollouts was unused and is removed.
- VLLM was missing in the live cluster and is not recreated.
- Stale Tempo remnants should be cleaned up, not recreated.

## Secrets

Vault Secrets Operator manages most app secrets. Some live secrets are still
manual and must be preserved unless intentionally migrated:

- `authentik/authentik-secrets`
- `monitoring/grafana-github-oauth`

## Follow-Ups

- Repair degraded `authentik-pg-1`.
- Create a reusable "how to deploy to this lab" guide for coding agents working
  in other software projects.
- Keep Talos version upgrades separate from the Flux migration.
