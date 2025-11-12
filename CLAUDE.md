# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a homelab Kubernetes cluster running Talos Linux on 3x Minisforum UM790 Pro Mini-PCs. The infrastructure is managed declaratively using GitOps with Argo CD.

## Architecture

### Infrastructure Layer
- **OS**: Talos Linux v1.11.3 with custom system extensions (AMD GPU, iSCSI tools, util-linux-tools)
- **Kubernetes**: v1.34.1
- **Cluster Endpoint**: https://talos.froystein.jp:6443
- **Node IPs**: 192.168.1.100-102
- **CNI**: Cilium (custom manifest)
- **Pod Network**: 10.244.0.0/16
- **Service Network**: 10.96.0.0/12

### GitOps & Application Management
- **GitOps Tool**: Argo CD v3.2.0
- **Application Structure**: Each subdirectory in `apps/` represents a separate application managed by Argo CD ApplicationSet
- **ApplicationSet**: `apps/appset.yaml` automatically creates Argo CD Applications for each directory in `apps/`
- **Sync Policy**: Manual sync by default (automated sync disabled)

### Key Applications
- **argocd**: GitOps controller, bootstrapped via kustomize from upstream manifest
- **cert-manager**: TLS certificate management
- **cilium**: CNI with Hubble observability
- **gateway**: Kubernetes Gateway API implementation
- **longhorn**: Distributed block storage (used by monitoring stack)
- **metallb**: Bare-metal load balancer
- **monitoring**: kube-prometheus-stack (Prometheus + Grafana)
  - Grafana uses GitHub OAuth (client ID/secret from Secret)
  - Persistent storage via Longhorn (50Gi for Prometheus, 10Gi for Grafana)
- **kubevirt**: VM workload support
- **cdi**: Containerized Data Importer for KubeVirt
- **multus**: Multiple network interfaces for pods
- **vm**: Virtual machine definitions

### Configuration Patterns
- **Helm-based apps** use Argo CD Application with `chart:` source pointing to OCI registries (e.g., ghcr.io)
- **Kustomize-based apps** use kustomization.yaml with resources (local or remote URLs)
- **HTTPRoutes** define ingress routing via Gateway API (found in various apps)

## Development Workflow

### Prerequisites
- `talosctl`: Talos Linux CLI
- `kubectl`: Kubernetes CLI
- `just`: Command runner
- `direnv`: Environment variable management (exports CP_IPS for control plane IPs)

### Common Commands

#### Bootstrap cluster (first time setup)
```bash
# Install Argo CD
just bootstrap

# Create ApplicationSet to deploy all apps
just bootstrap-apps
```

#### Apply Talos machine config patches
```bash
# Patches all control plane nodes with configs from patches/ directory
just patch
```

#### Argo CD operations
```bash
# View Argo CD applications
kubectl get applications -n argocd

# Sync an application
kubectl -n argocd patch application <app-name> --type merge -p '{"operation":{"sync":{}}}'

# View application details
kubectl describe application <app-name> -n argocd
```

#### Talos operations
```bash
# Set environment variables (CP_IPS)
just env

# Access Talos API
talosctl --endpoints $CP_IPS <command>

# View cluster health
talosctl health --endpoints $CP_IPS

# View service logs
talosctl logs <service> --endpoints $CP_IPS
```

### File Organization
- `controlplane.yaml` / `worker.yaml`: Base Talos machine configurations
- `controlplane-patch.yaml`: Patches for control plane nodes
- `patches/`: Additional machine config patches applied via `just patch`
- `manifests/cilium.yaml`: CNI manifest referenced by Talos config
- `apps/`: All Kubernetes applications (one directory per app)
  - `*/chart.yaml`: Argo CD Application for Helm charts
  - `*/kustomization.yaml`: Kustomize configuration
  - `*/namespace.yaml`: Namespace definitions
  - `*/httproute.yaml`: Gateway API routes

### Making Changes

#### Adding a new application
1. Create directory under `apps/<app-name>/`
2. Add either:
   - `chart.yaml` (Argo CD Application for Helm)
   - `kustomization.yaml` (for kustomize)
3. ApplicationSet will automatically detect and create the Application

#### Modifying Talos configuration
1. Edit `controlplane.yaml`, `worker.yaml`, or create patch file in `patches/`
2. Apply with `just patch` (for patches) or use talosctl commands directly

#### Updating application versions
- For Helm apps: Update `targetRevision` in `chart.yaml`
- For kustomize apps: Update resource URLs or add patches

### Security Notes
- Secrets like Grafana OAuth credentials are stored as Kubernetes Secrets (not in git)
- Talos machine configs contain certificates/keys (these are committed but should be treated as sensitive)
- GitHub OAuth is configured for Grafana access control (stianfro user gets GrafanaAdmin role)
