# Cloudflare Tunnel Setup

This document describes how to expose Kubernetes services to the public internet using Cloudflare Tunnel with Envoy Gateway.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Internet                                        │
│                         (https://app.froystein.jp)                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Cloudflare Edge                                    │
│  • TLS termination          • DDoS protection                               │
│  • WAF (optional)           • CDN caching                                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                              Tunnel (QUIC)
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Kubernetes Cluster                                    │
│                                                                              │
│  ┌─────────────────────┐    ┌─────────────────────┐                         │
│  │  cloudflared        │    │  cloudflared        │   (2 replicas)          │
│  │  namespace:         │    │  namespace:         │                         │
│  │  cloudflare-tunnel  │    │  cloudflare-tunnel  │                         │
│  └─────────┬───────────┘    └─────────┬───────────┘                         │
│            │                          │                                      │
│            └──────────┬───────────────┘                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────┐                            │
│  │  Envoy Gateway (eg-public)                  │                            │
│  │  namespace: envoy-gateway-system            │                            │
│  │  service: ClusterIP (no LoadBalancer)       │                            │
│  └─────────────────────┬───────────────────────┘                            │
│                        │                                                     │
│                   HTTPRoute                                                  │
│                        │                                                     │
│                        ▼                                                     │
│  ┌─────────────────────────────────────────────┐                            │
│  │  Backend Service                            │                            │
│  │  (e.g., froystein-jp)                       │                            │
│  └─────────────────────────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Cloudflare Tunnel (`lab-public`)

- **Tunnel ID**: `bbe4d352-a6f1-4cec-9070-1e609897ff0f`
- **Tunnel Name**: `lab-public`
- **Protocol**: QUIC (auto-negotiated)
- **Connectors**: 2 (one per cloudflared pod)

### 2. gateway-public (`apps/gateway-public/`)

| Resource | Name | Description |
|----------|------|-------------|
| EnvoyProxy | `public-config` | Configures ClusterIP service type |
| GatewayClass | `eg-public` | References the EnvoyProxy config |
| Gateway | `eg-public` | HTTP listener on port 80 for `*.froystein.jp` |

### 3. cloudflare-tunnel (`apps/cloudflare-tunnel/`)

| Resource | Name | Description |
|----------|------|-------------|
| Namespace | `cloudflare-tunnel` | Isolated namespace for tunnel components |
| VaultStaticSecret | `cloudflare-tunnel-credentials` | Syncs credentials from Vault |
| ConfigMap | `cloudflare-tunnel-config` | Tunnel ingress configuration |
| Deployment | `cloudflared` | 2 replicas of cloudflared |
| PodDisruptionBudget | `cloudflared` | Ensures HA during updates |
| Service | `cloudflared-metrics` | Exposes metrics for Prometheus |

## Initial Setup

### Prerequisites

- `cloudflared` CLI installed locally
- Cloudflare account with domain configured
- Vault with VSO (Vault Secrets Operator) configured

### Step 1: Create the Tunnel

```bash
# Login to Cloudflare (opens browser)
cloudflared login

# Create the tunnel
cloudflared tunnel create lab-public

# Note the Tunnel ID from output:
# Created tunnel lab-public with id bbe4d352-a6f1-4cec-9070-1e609897ff0f
```

### Step 2: Configure DNS Routes

```bash
# Wildcard for all subdomains
cloudflared tunnel route dns lab-public "*.froystein.jp"

# Bare domain (use --overwrite-dns if A record exists)
cloudflared tunnel route dns --overwrite-dns lab-public "froystein.jp"

# Specific subdomain
cloudflared tunnel route dns lab-public "www.froystein.jp"
```

### Step 3: Store Credentials in Vault

The credentials file is created at `~/.cloudflared/<tunnel-id>.json`:

```json
{
  "AccountTag": "f0432fef8de80b8f77e4082465c26b88",
  "TunnelSecret": "base64-encoded-secret",
  "TunnelID": "bbe4d352-a6f1-4cec-9070-1e609897ff0f"
}
```

Store in Vault:

```bash
kubectl exec -it vault-0 -n vault -- vault kv put secret/cloudflare-tunnel/credentials \
    account_id="<AccountTag>" \
    tunnel_secret="<TunnelSecret>" \
    tunnel_id="<TunnelID>"
```

### Step 4: Deploy the Apps

The apps are deployed via Argo CD ApplicationSet:

1. `apps/gateway-public/` - Creates the public gateway
2. `apps/cloudflare-tunnel/` - Deploys cloudflared

After pushing to git, Argo CD will sync automatically.

### Step 5: Update ConfigMap with Gateway Service

After the gateway is deployed, get the service name:

```bash
kubectl get svc -n envoy-gateway-system | grep eg-public
# Example: envoy-envoy-gateway-system-eg-public-7b646a69
```

Update `apps/cloudflare-tunnel/configmap.yaml` with the service name.

## Exposing Services

### Quick Start

To expose a service publicly:

1. **Create HTTPRoute** in your app's namespace:

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

2. **Add DNS route** (if not using wildcard):

```bash
cloudflared tunnel route dns lab-public "myapp.froystein.jp"
```

### Multiple Hostnames

```yaml
spec:
  hostnames:
    - "myapp.froystein.jp"
    - "www.myapp.froystein.jp"
```

### Path-Based Routing

```yaml
rules:
  - matches:
      - path:
          type: PathPrefix
          value: /api
    backendRefs:
      - name: api-service
        port: 8080
  - matches:
      - path:
          type: PathPrefix
          value: /
    backendRefs:
      - name: frontend-service
          port: 80
```

## Configuration Reference

### cloudflared ConfigMap

```yaml
data:
  config.yaml: |
    tunnel: bbe4d352-a6f1-4cec-9070-1e609897ff0f
    credentials-file: /etc/cloudflared/credentials.json
    metrics: 0.0.0.0:2000
    no-autoupdate: true
    loglevel: info
    protocol: auto

    originRequest:
      noTLSVerify: false
      connectTimeout: 30s
      keepAliveConnections: 100
      keepAliveTimeout: 90s
      http2Origin: true

    ingress:
      - hostname: "*.froystein.jp"
        service: http://envoy-envoy-gateway-system-eg-public-7b646a69.envoy-gateway-system.svc.cluster.local:80
      - hostname: "froystein.jp"
        service: http://envoy-envoy-gateway-system-eg-public-7b646a69.envoy-gateway-system.svc.cluster.local:80
      - service: http_status:404
```

### VaultStaticSecret

```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: cloudflare-tunnel-credentials
  namespace: cloudflare-tunnel
spec:
  vaultAuthRef: vault/default
  mount: secret
  type: kv-v2
  path: cloudflare-tunnel/credentials
  refreshAfter: 1h
  destination:
    name: cloudflare-tunnel-credentials
    create: true
    transformation:
      excludeRaw: true
      templates:
        credentials.json:
          text: |
            {
              "AccountTag": "{{ .Secrets.account_id }}",
              "TunnelSecret": "{{ .Secrets.tunnel_secret }}",
              "TunnelID": "{{ .Secrets.tunnel_id }}"
            }
```

## Operations

### Check Tunnel Status

```bash
# Tunnel info and connectors
cloudflared tunnel info lab-public

# Pod status
kubectl get pods -n cloudflare-tunnel

# Tunnel connection logs
kubectl logs -n cloudflare-tunnel -l app.kubernetes.io/name=cloudflare-tunnel --tail=20
```

### Restart cloudflared

```bash
kubectl rollout restart deployment/cloudflared -n cloudflare-tunnel
```

### Add New DNS Route

```bash
# Normal add
cloudflared tunnel route dns lab-public "newhost.froystein.jp"

# Overwrite existing record
cloudflared tunnel route dns --overwrite-dns lab-public "existinghost.froystein.jp"
```

### Delete DNS Route

Manage via Cloudflare Dashboard: DNS → Records → Delete the CNAME pointing to `<tunnel-id>.cfargotunnel.com`

## Troubleshooting

### Error 1016: Origin DNS Error

**Cause**: DNS record not pointing to the tunnel.

**Fix**:
```bash
cloudflared tunnel route dns --overwrite-dns lab-public "hostname.froystein.jp"
```

### 502 Bad Gateway

**Cause**: cloudflared can't reach the Gateway service.

**Debug**:
```bash
# Check gateway service exists
kubectl get svc -n envoy-gateway-system | grep eg-public

# Check gateway pods are running
kubectl get pods -n envoy-gateway-system | grep eg-public

# Check cloudflared logs for errors
kubectl logs -n cloudflare-tunnel -l app.kubernetes.io/name=cloudflare-tunnel | grep -i error
```

### 404 Not Found

**Cause**: No HTTPRoute matches the hostname.

**Debug**:
```bash
# List HTTPRoutes
kubectl get httproute -A

# Check route status
kubectl describe httproute <name> -n <namespace>
```

### Gateway Pods Not Scheduling

**Cause**: AI Gateway webhook certificate issues.

**Fix**:
```bash
# Restart AI gateway controller
kubectl rollout restart deployment/ai-gateway-controller -n envoy-ai-gateway-system

# Then restart the gateway deployment
kubectl rollout restart deployment/envoy-envoy-gateway-system-eg-public-7b646a69 -n envoy-gateway-system
```

### VaultStaticSecret Not Syncing

**Debug**:
```bash
# Check VSO logs
kubectl logs -n vault -l app.kubernetes.io/name=vault-secrets-operator --tail=50

# Verify secret exists in Vault
kubectl exec -it vault-0 -n vault -- vault kv get secret/cloudflare-tunnel/credentials

# Check VaultStaticSecret status
kubectl describe vaultstaticsecret cloudflare-tunnel-credentials -n cloudflare-tunnel
```

## Security Considerations

1. **Tunnel credentials** are stored in Vault, never in git
2. **No public IPs** exposed - all ingress via Cloudflare
3. **Cloudflare protection** - DDoS, WAF, rate limiting at edge
4. **Zero Trust** - Can add Cloudflare Access policies for authentication

## Monitoring

cloudflared exposes Prometheus metrics on port 2000:

- `cloudflared_tunnel_active_streams` - Active connections
- `cloudflared_tunnel_request_errors` - Failed requests
- `cloudflared_tunnel_response_by_code` - Response codes

The metrics Service has Prometheus annotations for auto-discovery:

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "2000"
  prometheus.io/path: "/metrics"
```
