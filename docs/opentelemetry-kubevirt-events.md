# OpenTelemetry Collector for KubeVirt Events

This document describes how to configure the OpenTelemetry Collector to collect, filter, and forward KubeVirt events (VirtualMachineInstance and VirtualMachineInstanceMigration) to a logging backend.

## Overview

This setup uses the OpenTelemetry Collector to:
1. Collect Kubernetes events related to KubeVirt VirtualMachineInstances
2. Filter out non-KubeVirt events
3. Forward only VirtualMachineInstance events to your logging backend

## Architecture

```
Kubernetes Events (KubeVirt)
        ↓
k8seventsreceiver (watches all namespaces)
        ↓
filter/kubevirt (keeps only VirtualMachineInstance events)
        ↓
resource processor (adds service.name label)
        ↓
batch processor
        ↓
Logging Backend (Loki, Elasticsearch, etc.)
```

## Prerequisites

- OpenTelemetry Collector Contrib v0.139.0 or later
- Kubernetes cluster with KubeVirt installed
- RBAC permissions to read events cluster-wide

## Configuration

### Receivers

The `k8seventsreceiver` collects Kubernetes events:

```yaml
receivers:
  k8s_events:
    auth_type: serviceAccount
    namespaces: []  # Empty array = watch all namespaces
```

**Key Points:**
- `auth_type: serviceAccount` - Uses the pod's service account for authentication
- `namespaces: []` - Watches all namespaces. Specify namespace names to limit scope.
- The receiver sets resource attributes including `k8s.object.kind` from the event's `involvedObject.kind`

### Processors

#### Filter Processor

The filter processor drops non-KubeVirt events:

```yaml
processors:
  filter/kubevirt:
    logs:
      log_record:
        - 'not IsMatch(resource.attributes["k8s.object.kind"], "^VirtualMachineInstance")'
```

**Critical Understanding:**
- The filter processor **DROPS** events that match the condition
- We use `not IsMatch` to invert the logic and drop events that do NOT match
- This keeps only events where `k8s.object.kind` starts with "VirtualMachineInstance"

**Matches:**
- ✅ `VirtualMachineInstance` - VM instance lifecycle events
- ✅ `VirtualMachineInstanceMigration` - VM migration events

**Drops:**
- ❌ `Pod`, `Deployment`, `ReplicaSet`, etc. - All non-KubeVirt events

#### Resource Processor

Adds a service name label for easier querying:

```yaml
processors:
  resource:
    attributes:
      - key: service.name
        value: kubevirt-events
        action: insert
```

#### Batch Processor

Batches events for efficient transmission:

```yaml
processors:
  batch:
    timeout: 10s
    send_batch_size: 1024
```

### Exporters

Configure your preferred logging backend. Example for OTLP HTTP:

```yaml
exporters:
  otlphttp:
    endpoint: http://your-backend:4318
    tls:
      insecure: false  # Set to true for testing
```

### Pipeline Configuration

**Important:** Do NOT enable the `kubernetesAttributes` preset for event logs!

```yaml
presets:
  kubernetesAttributes:
    enabled: false  # MUST be false - interferes with k8seventsreceiver
```

The logs pipeline:

```yaml
service:
  pipelines:
    logs:
      receivers: [k8s_events]
      processors: [filter/kubevirt, resource, batch]
      exporters: [otlphttp]
```

**Pipeline Order Matters:**
1. `filter/kubevirt` - Filter first to reduce processing load
2. `resource` - Add labels after filtering
3. `batch` - Batch before export

## RBAC Configuration

The collector requires cluster-wide read access to events:

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: otel-collector-k8s-events
rules:
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["namespaces", "pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: otel-collector-k8s-events
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: otel-collector-k8s-events
subjects:
  - kind: ServiceAccount
    name: otel-collector
    namespace: your-namespace
```

## Complete Example Configuration

```yaml
mode: deployment

image:
  repository: otel/opentelemetry-collector-contrib
  tag: 0.139.0

# IMPORTANT: Disable kubernetesAttributes preset
presets:
  kubernetesAttributes:
    enabled: false  # MUST be false for event logs
  kubeletMetrics:
    enabled: false

config:
  receivers:
    k8s_events:
      auth_type: serviceAccount
      namespaces: []  # Watch all namespaces

  processors:
    # Filter to keep only VirtualMachineInstance events
    # Note: Filter DROPS matching events, so we use "not" to invert
    filter/kubevirt:
      logs:
        log_record:
          - 'not IsMatch(resource.attributes["k8s.object.kind"], "^VirtualMachineInstance")'

    batch:
      timeout: 10s
      send_batch_size: 1024

    resource:
      attributes:
        - key: service.name
          value: kubevirt-events
          action: insert

  exporters:
    otlphttp:
      endpoint: http://your-backend:4318
      tls:
        insecure: false

  service:
    pipelines:
      logs:
        receivers: [k8s_events]
        processors: [filter/kubevirt, resource, batch]
        exporters: [otlphttp]

# RBAC
clusterRole:
  create: true
  rules:
    - apiGroups: [""]
      resources: ["events"]
      verbs: ["get", "list", "watch"]
    - apiGroups: [""]
      resources: ["namespaces", "pods"]
      verbs: ["get", "list", "watch"]
```

## Verification

### Check Collector Metrics

Query the collector's Prometheus metrics endpoint (default: `:8888/metrics`):

```bash
# Events received by k8seventsreceiver
curl http://collector:8888/metrics | grep otelcol_receiver_accepted_log_records_total

# Events dropped by filter
curl http://collector:8888/metrics | grep otelcol_processor_filter_logs_filtered_total

# Events sent to backend
curl http://collector:8888/metrics | grep otelcol_exporter_sent_log_records_total
```

**Expected Behavior:**
- `accepted` > `filtered` - Receiving events from multiple sources
- `sent` = `accepted` - `filtered` - Only VirtualMachineInstance events forwarded

### Sample Event Attributes

Events will have these resource attributes:

```yaml
resource.attributes:
  k8s.object.kind: VirtualMachineInstance
  k8s.object.name: vm-name
  k8s.object.uid: 12345-67890-abcdef
  k8s.namespace.name: virtualmachines
  k8s.node.name: worker-node-1
  service.name: kubevirt-events  # Added by resource processor

log.attributes:
  k8s.event.reason: Migrated
  k8s.event.action: ""
  k8s.event.count: 1
  k8s.event.name: vm-name.abc123
  k8s.event.start_time: "2024-01-01T00:00:00Z"
```

## Troubleshooting

### Issue: Seeing Non-KubeVirt Events

**Symptom:** Logs contain Pod, Deployment, or other non-KubeVirt events

**Causes:**
1. Filter condition is incorrect (missing `not` operator)
2. `kubernetesAttributes` preset is enabled (interfering with resource attributes)

**Solution:**
```yaml
# Ensure filter uses NOT
filter/kubevirt:
  logs:
    log_record:
      - 'not IsMatch(resource.attributes["k8s.object.kind"], "^VirtualMachineInstance")'

# Ensure preset is disabled
presets:
  kubernetesAttributes:
    enabled: false
```

### Issue: No Events Collected

**Symptom:** No events appear in logs

**Checks:**
1. Verify RBAC permissions: `kubectl auth can-i list events --as=system:serviceaccount:namespace:otel-collector`
2. Check collector logs for errors: `kubectl logs -l app=otel-collector`
3. Verify k8seventsreceiver is configured with correct namespace(s)
4. Ensure VirtualMachineInstance events exist: `kubectl get events -A --field-selector involvedObject.kind=VirtualMachineInstance`

### Issue: All Events Dropped

**Symptom:** `filtered` count equals `accepted` count

**Cause:** Filter regex doesn't match the attribute value

**Debug:**
1. Temporarily disable the filter to verify collection works
2. Check the actual attribute values in your logging backend
3. Verify the attribute path: `resource.attributes["k8s.object.kind"]` vs `attributes["k8s.object.kind"]`

**Note:** The k8seventsreceiver sets `k8s.object.kind` as a **resource-level attribute**, not a log-level attribute.

### Issue: Events Missing After Enabling kubernetesAttributes

**Symptom:** Events stop flowing after enabling the `kubernetesAttributes` preset

**Cause:** The `k8sattributes` processor (injected by the preset) is designed for pod logs and interferes with the resource attributes set by k8seventsreceiver.

**Solution:** Keep `kubernetesAttributes` disabled for event logs:
```yaml
presets:
  kubernetesAttributes:
    enabled: false
```

## Performance Considerations

### Resource Usage

- **Memory:** ~50-100MB for typical workloads
- **CPU:** ~50-100m for typical event volumes
- **Network:** Depends on event frequency and backend latency

### Tuning

Adjust batch processor for your environment:

```yaml
processors:
  batch:
    timeout: 10s          # Lower = more real-time, higher = more efficient
    send_batch_size: 1024 # Adjust based on event volume
```

### Limiting Namespaces

To reduce load, watch only namespaces with VMs:

```yaml
receivers:
  k8s_events:
    auth_type: serviceAccount
    namespaces: [vm-namespace-1, vm-namespace-2]
```

## Advanced Filtering

### Filter by Namespace

Keep events only from specific namespaces:

```yaml
filter/kubevirt:
  logs:
    log_record:
      - 'not (IsMatch(resource.attributes["k8s.object.kind"], "^VirtualMachineInstance") and resource.attributes["k8s.namespace.name"] == "production")'
```

### Filter by Event Reason

Keep only migration-related events:

```yaml
filter/kubevirt:
  logs:
    log_record:
      - 'not (IsMatch(resource.attributes["k8s.object.kind"], "^VirtualMachineInstance") and IsMatch(attributes["k8s.event.reason"], "Migrat"))'
```

### Combine Multiple Conditions

Use boolean operators (`and`, `or`, `not`):

```yaml
filter/kubevirt:
  logs:
    log_record:
      - 'not (IsMatch(resource.attributes["k8s.object.kind"], "^VirtualMachineInstance") and (resource.attributes["k8s.namespace.name"] == "prod" or resource.attributes["k8s.namespace.name"] == "staging"))'
```

## OTTL Filter Syntax Reference

### Boolean Operators

- `and` - All conditions must be true
- `or` - Any condition must be true
- `not` - Negates the expression

**Precedence:** `not` > `and` > `or` (use parentheses to override)

### Common Functions

- `IsMatch(field, "regex")` - Check if field matches regex pattern
- `==`, `!=` - Equality comparison
- `>`, `<`, `>=`, `<=` - Numeric comparison

### Accessing Attributes

- `resource.attributes["key"]` - Resource-level attributes (set by receiver)
- `attributes["key"]` - Log-level attributes (event-specific)
- `body` - Log message body

## References

- [OpenTelemetry k8seventsreceiver](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/receiver/k8seventsreceiver)
- [OpenTelemetry filterprocessor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/filterprocessor)
- [OTTL Language Specification](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/pkg/ottl/LANGUAGE.md)
- [KubeVirt Documentation](https://kubevirt.io/user-guide/)

## Version Compatibility

This configuration is tested with:
- OpenTelemetry Collector Contrib: v0.139.0+
- Kubernetes: 1.28+
- KubeVirt: 1.0+

## License

This documentation is provided as-is for use in any environment.
