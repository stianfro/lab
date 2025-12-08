# Envoy AI Gateway

This application deploys Envoy AI Gateway alongside the existing Envoy Gateway for AI/ML inference workloads.

## Architecture

```
Client Request
    │
    ▼
AI Gateway (eg-ai) @ 192.168.1.21
    │
    ├─► AIGatewayRoute (matches x-ai-eg-model header)
    │       │
    │       ▼
    │   InferencePool (gemma2)
    │       │
    │       ▼
    │   EndpointPicker (EPP) - intelligent scheduling
    │       │
    │       ▼
    │   vLLM engine pod (port 8000)
    │
    └─► Direct HTTPRoute (Service backend)
            │
            ▼
        vLLM service
```

## Components

| Component | Namespace | Purpose |
|-----------|-----------|---------|
| envoy-gateway | envoy-ai-gateway-system | Envoy Gateway with AI extension manager |
| ai-gateway-controller | envoy-ai-gateway-system | AI Gateway controller for AIGatewayRoute CRD |
| ai-gateway-extproc | envoy-ai-gateway-system | Sidecar for model name processing |
| gemma2-epp | vllm | EndpointPicker for intelligent request scheduling |

## CRDs Installed

- `aigatewayroutes.aigateway.envoyproxy.io` - AI Gateway routes
- `aiservicebackends.aigateway.envoyproxy.io` - AI service backends
- `backendsecuritypolicies.aigateway.envoyproxy.io` - Backend security
- `mcproutes.aigateway.envoyproxy.io` - MCP routes
- `inferencepools.inference.networking.k8s.io` - Gateway API Inference Extension (stable)
- `inferenceobjectives.inference.networking.x-k8s.io` - Gateway API Inference Extension (experimental)

## Configuration

### Gateway
- GatewayClass: `eg-ai` with controller `gateway.envoyproxy.io/ai-gatewayclass-controller`
- Gateway: `eg-ai` in `envoy-ai-gateway-system`
- Listeners: HTTPS on port 443 for `*.ai.froystein.jp` and `ai.froystein.jp`
- TLS: cert-manager with letsencrypt-issuer

### Extension Manager
The Envoy Gateway is configured with an extension manager that:
- Hooks into xdsTranslator for listener, route, cluster, and secret translation
- Connects to ai-gateway-controller on port 1063
- Watches InferencePool resources as backend types

## Known Issues

### AIGatewayRoute + InferencePool Integration (December 2025)

**Status:** NOT WORKING

**Symptoms:**
- Requests to `https://ai.froystein.jp/v1/chat/completions` timeout after 60s
- EPP correctly selects endpoints (visible in logs)
- vLLM never receives the request

**Root Cause Analysis:**

1. **Upstream ext_proc filter failure:**
   - The AIGatewayRoute creates an HTTPRoute with an upstream ext_proc filter on the cluster
   - This filter connects to `ai-gateway-extproc-uds` (UDS socket to the sidecar)
   - All gRPC streams to this ext_proc fail: `streams_failed: N`, `upstream_rq_tx_reset: N`
   - The ext_proc responds with HTTP 200 but Envoy resets the transmission

2. **Envoy stats showing the issue:**
   ```
   cluster.httproute/vllm/gemma2/rule/0ext_proc.streams_started: 7
   cluster.httproute/vllm/gemma2/rule/0ext_proc.streams_failed: 7
   cluster.httproute/vllm/gemma2/rule/0ext_proc.stream_msgs_sent: 7
   cluster.httproute/vllm/gemma2/rule/0ext_proc.stream_msgs_received: 0

   cluster.ai-gateway-extproc-uds.upstream_rq_200: 7
   cluster.ai-gateway-extproc-uds.upstream_rq_tx_reset: 7
   ```

3. **ai-gateway-extproc sidecar:**
   - Starts successfully and logs "AI Gateway External Processor is ready"
   - Never logs any request processing
   - The ext_proc is configured on the **upstream** HTTP filter chain (per-cluster)

**What Works:**
- Direct HTTPRoute to Service (bypassing InferencePool): Works
- EPP endpoint selection: Works correctly
- vLLM direct access: Works
- Gateway TLS termination: Works
- Certificate (wildcard + bare domain): Valid

**Debugging Commands:**

```bash
# Check EPP logs (should show endpoint selection)
kubectl logs -n vllm deployment/gemma2-epp --tail=50 | grep -E "(handled|endpoint)"

# Check ai-gateway-extproc logs (should show request processing - currently empty)
kubectl logs -n envoy-ai-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=eg-ai -c ai-gateway-extproc --tail=50

# Check Envoy access logs
kubectl logs -n envoy-ai-gateway-system -l gateway.envoyproxy.io/owning-gateway-name=eg-ai -c envoy --tail=20

# Port-forward to Envoy admin interface
kubectl port-forward -n envoy-ai-gateway-system deployment/envoy-envoy-ai-gateway-system-eg-ai-* 19000:19000

# Check cluster stats
curl -s "http://localhost:19000/clusters" | grep -E "(gemma2|inferencepool)"

# Check ext_proc stats
curl -s "http://localhost:19000/stats" | grep ext_proc

# Check cluster configuration
curl -s "http://localhost:19000/config_dump" | jq '.configs[] | select(.["@type"] | contains("Clusters")) | .dynamic_active_clusters[] | select(.cluster.name | contains("gemma2"))'
```

**Cluster Configuration (for reference):**
The InferencePool cluster is configured as:
- Type: `ORIGINAL_DST`
- Uses `x-gateway-destination-endpoint` header for routing
- Has upstream HTTP filter: `envoy.filters.http.ext_proc/aigateway` connecting to `ai-gateway-extproc-uds`

**Versions:**
- Envoy Gateway: v1.5.4
- AI Gateway: v0.4.0
- Gateway API Inference Extension EPP: v1.0.1
- InferencePool CRD: v1.2.0

**Potential Fixes to Investigate:**
1. Check if newer AI Gateway versions fix this issue
2. Check if the ai-gateway-extproc needs specific configuration for InferencePool
3. Try disabling the upstream ext_proc filter for InferencePool routes
4. Check Envoy AI Gateway GitHub issues for similar reports

## Working Alternatives

### Option 1: Direct Service Route (No EPP)
```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: vllm-direct
  namespace: vllm
spec:
  parentRefs:
    - name: eg-ai
      namespace: envoy-ai-gateway-system
  hostnames:
    - "direct.ai.froystein.jp"
  rules:
    - backendRefs:
        - name: vllm-chart-gemma2-engine-service
          port: 80
```

### Option 2: Use Regular Gateway
The existing route at `vllm.talos.froystein.jp` works via the regular Envoy Gateway.

## Files

| File | Purpose |
|------|---------|
| namespace.yaml | Creates envoy-ai-gateway-system namespace |
| envoy-gateway.yaml | Argo CD Application for Envoy Gateway with AI config |
| ai-gateway-crds.yaml | AI Gateway CRDs |
| ai-gateway.yaml | AI Gateway controller deployment |
| gateway.yaml | GatewayClass and Gateway resources |
| inference-pool-crds.yaml | InferencePool CRD (stable API) |
| inference-experimental-crds.yaml | InferenceObjective CRD (experimental API) |

## Related Apps

- `apps/vllm/` - vLLM deployment with InferencePool, EPP, and AIGatewayRoute
- `apps/gateway/` - Regular Envoy Gateway (working)
