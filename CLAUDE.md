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
- **gateway**: Internal Kubernetes Gateway API (Envoy Gateway) for `*.talos.froystein.jp`
- **gateway-public**: Public gateway for Cloudflare tunnel traffic on `*.froystein.jp`
- **cloudflare-tunnel**: Cloudflared deployment connecting to Cloudflare for public internet access
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

## Kargo

Kargo is installed for GitOps promotions at `https://kargo.talos.froystein.jp`.

### OIDC Configuration
- **Provider**: Authentik (at `https://authentik.talos.froystein.jp`)
- **Client Type**: Public (NOT Confidential)
- **Authentication**: PKCE (Proof Key for Code Exchange) - no client secret required
- **Admin Access**: Controlled via `argo-admin` group claim from Authentik
- **Issuer URL**: `https://authentik.talos.froystein.jp/application/o/kargo/`

### Important Notes
- Kargo uses PKCE and does NOT need a client secret - the Authentik OAuth2 provider must be set to "Public" client type
- Do not use `clientSecretFromSecret` in Helm values - it's unnecessary for PKCE
- The redirect URI for the web UI is `/login` (not `/auth/callback`)
- CLI redirect URI is `http://localhost:11111/auth/callback`

## Authentik

Authentik is the identity provider for this cluster.

### API Access
- API endpoint: `https://authentik.talos.froystein.jp/api/v3/`
- API tokens can be created in the Authentik admin UI under Directory → Tokens
- Use Bearer token authentication: `Authorization: Bearer <token>`

### Useful API Operations
```bash
# List OAuth2 providers
curl -s -H "Authorization: Bearer $TOKEN" "https://authentik.talos.froystein.jp/api/v3/providers/oauth2/"

# Update a provider (e.g., change client_type to public)
curl -X PATCH "https://authentik.talos.froystein.jp/api/v3/providers/oauth2/<pk>/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"client_type": "public"}'

# Check OIDC discovery endpoint
curl -s "https://authentik.talos.froystein.jp/application/o/<slug>/.well-known/openid-configuration"
```

### OAuth2 Provider Configuration
- For applications using PKCE (like Kargo): Use "Public" client type
- For applications requiring client secret exchange: Use "Confidential" client type
- Check `token_endpoint_auth_methods_supported` in the OIDC discovery endpoint to verify supported authentication methods

## Cloudflare Tunnel & Public Gateway

The cluster has two gateway setups for different use cases:

### Gateway Architecture

| Gateway | GatewayClass | Domain | Purpose |
|---------|--------------|--------|---------|
| `eg` | `eg` | `*.talos.froystein.jp` | Internal services (LoadBalancer via MetalLB) |
| `eg-public` | `eg-public` | `*.froystein.jp` | Public internet access via Cloudflare Tunnel |

### Traffic Flow (Public)
```
Internet → Cloudflare Edge → cloudflared pods → eg-public Gateway → HTTPRoute → Service
```

### Key Components

**gateway-public** (`apps/gateway-public/`):
- GatewayClass `eg-public` with ClusterIP service (no LoadBalancer needed)
- EnvoyProxy configured for ClusterIP since Cloudflare handles external access
- HTTP listener on port 80 (Cloudflare terminates TLS)

**cloudflare-tunnel** (`apps/cloudflare-tunnel/`):
- Tunnel ID: `bbe4d352-a6f1-4cec-9070-1e609897ff0f`
- Credentials stored in Vault at `secret/cloudflare-tunnel/credentials`
- VaultStaticSecret syncs credentials to Kubernetes
- 2 replicas with pod anti-affinity for HA

### Exposing a Service Publicly

1. Create an HTTPRoute targeting `eg-public`:
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: myapp-public
  namespace: myapp
spec:
  parentRefs:
    - name: eg-public
      namespace: envoy-gateway-system
  hostnames:
    - "myapp.froystein.jp"
  rules:
    - backendRefs:
        - name: myapp-service
          port: 80
```

2. Add DNS route (if not using wildcard):
```bash
cloudflared tunnel route dns lab-public "myapp.froystein.jp"
```

### Managing the Tunnel

```bash
# List tunnel info
cloudflared tunnel info lab-public

# Add DNS route
cloudflared tunnel route dns lab-public "newhost.froystein.jp"

# Add DNS route (overwrite existing)
cloudflared tunnel route dns --overwrite-dns lab-public "host.froystein.jp"

# Check tunnel connections
kubectl logs -n cloudflare-tunnel -l app.kubernetes.io/name=cloudflare-tunnel
```

### Troubleshooting

**Error 1016 (Origin DNS error)**: DNS not pointing to tunnel
```bash
cloudflared tunnel route dns --overwrite-dns lab-public "hostname.froystein.jp"
```

**502 Bad Gateway**: Check gateway service connectivity
```bash
kubectl get svc -n envoy-gateway-system | grep eg-public
kubectl logs -n cloudflare-tunnel -l app.kubernetes.io/name=cloudflare-tunnel
```

**Pods not scheduling**: AI Gateway webhook interference
```bash
# Restart AI gateway controller to fix certificate issues
kubectl rollout restart deployment/ai-gateway-controller -n envoy-ai-gateway-system
```

See `docs/cloudflare-tunnel.md` for detailed setup documentation.
