# KubeVirt VM Migration Event Logging with OpenTelemetry and Loki

This document describes the setup for capturing and storing KubeVirt VM migration events using OpenTelemetry Collector and Loki.

## Architecture Overview

```
┌─────────────────────┐
│  Kubernetes Events  │ (virtualmachines namespace)
│  (VM Migrations)    │
└──────────┬──────────┘
           │
           ▼
┌──────────────────────────┐
│ OpenTelemetry Collector  │
│  - k8s_events receiver   │
│  - batch processor       │
│  - otlphttp exporter     │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│         Loki             │
│  - Single-binary mode    │
│  - Longhorn storage      │
│  - 7-day retention       │
│  - OTLP receiver         │
└──────────┬───────────────┘
           │
           ▼
┌──────────────────────────┐
│        Grafana           │
│  - Loki datasource       │
│  - Log exploration       │
└──────────────────────────┘
```

## Components

### 1. OpenTelemetry Collector (`apps/otel-collector/`)

**Purpose**: Collect Kubernetes events for VirtualMachineInstance resources across all namespaces and forward them to Loki.

**Key Features**:
- Uses `otel/opentelemetry-collector-contrib` image
- `k8s_events` receiver watches all namespaces
- Filters events to only VirtualMachineInstance and VirtualMachineInstanceMigration resources
- Batches events before sending to Loki
- RBAC configured to read cluster-wide events

**Configuration Highlights**:
```yaml
receivers:
  k8s_events:
    # Watch all namespaces

processors:
  filter/kubevirt:
    logs:
      log_record:
        - 'IsMatch(resource.attributes["k8s.object.kind"], "VirtualMachineInstance.*")'

exporters:
  otlphttp:
    endpoint: http://loki-gateway.loki.svc.cluster.local/otlp
```

**Files**:
- `namespace.yaml`: Creates `otel-collector` namespace
- `chart.yaml`: Argo CD Application using OpenTelemetry Helm chart
- `kustomization.yaml`: Resource list

### 2. Loki (`apps/loki/`)

**Purpose**: Store and query VM migration event logs.

**Key Features**:
- Loki Helm chart v6.46.0 (latest stable release)
- Single-binary deployment (simpler for homelab)
- 50Gi Longhorn persistent storage
- 7-day log retention
- OTLP receiver enabled for OpenTelemetry integration
- Web UI exposed at `https://loki.talos.froystein.jp`

**Configuration Highlights**:
```yaml
loki:
  limits_config:
    retention_period: 168h  # 7 days

singleBinary:
  persistence:
    enabled: true
    storageClass: longhorn
    size: 50Gi
```

**Files**:
- `namespace.yaml`: Creates `loki` namespace
- `chart.yaml`: Argo CD Application using Grafana Loki Helm chart
- `httproute.yaml`: Gateway API route for web UI access
- `kustomization.yaml`: Resource list

### 3. Grafana Datasource Configuration

**Purpose**: Connect Grafana to Loki for log visualization.

**Changes**: Updated `apps/monitoring/chart.yaml` to add Loki as an additional datasource:

```yaml
grafana:
  additionalDataSources:
    - name: Loki
      type: loki
      access: proxy
      url: http://loki-gateway.loki.svc.cluster.local
      isDefault: false
      editable: false
      orgId: 1
      version: 1
      jsonData:
        maxLines: 1000
```

**Required Fields**:
- `orgId: 1` - Organization ID (required by kube-prometheus-stack)
- `version: 1` - Datasource schema version
- `editable: false` - Prevent manual modification (recommended for GitOps)
- `isDefault: false` - Only one datasource can be default (Prometheus is default)

## Deployment

### Deploy Applications via Argo CD

The applications will be automatically detected by the existing ApplicationSet. To deploy:

1. **Commit and push the changes**:
   ```bash
   git add apps/otel-collector apps/loki apps/monitoring/chart.yaml
   git commit -m "feat: add OpenTelemetry collector and Loki for VM migration logging"
   git push
   ```

2. **Sync applications in Argo CD**:
   ```bash
   # Sync OpenTelemetry Collector
   kubectl -n argocd patch application otel-collector --type merge -p '{"operation":{"sync":{}}}'

   # Sync Loki
   kubectl -n argocd patch application loki --type merge -p '{"operation":{"sync":{}}}'

   # Sync monitoring (to update Grafana datasource)
   kubectl -n argocd patch application kube-prometheus-stack --type merge -p '{"operation":{"sync":{}}}'
   ```

3. **Verify deployments**:
   ```bash
   # Check OpenTelemetry Collector
   kubectl get pods -n otel-collector
   kubectl logs -n otel-collector -l app.kubernetes.io/name=opentelemetry-collector

   # Check Loki
   kubectl get pods -n loki
   kubectl logs -n loki -l app.kubernetes.io/name=loki

   # Check that Loki datasource ConfigMap is created
   kubectl get configmap -n monitoring kube-prom-stack-grafana-datasource -o yaml | grep -A 10 Loki

   # Restart Grafana to pick up the new datasource
   kubectl rollout restart deployment/kube-prom-stack-grafana -n monitoring

   # Wait for Grafana to be ready
   kubectl rollout status deployment/kube-prom-stack-grafana -n monitoring

   # Verify Loki datasource is available in Grafana
   kubectl exec -n monitoring deploy/kube-prom-stack-grafana -- \
     wget -q -O - http://localhost:3000/api/datasources | grep -i loki
   ```

   **Note**: After updating the datasource configuration, you may need to restart Grafana for changes to take effect.

## Testing VM Migrations

### Using the Test Script

A bash script is provided to easily test VM migrations:

```bash
# Run with default VM (fedora-vm)
./scripts/test-vm-migration.sh

# Run with custom VM
VM_NAME=my-vm VM_NAMESPACE=virtualmachines ./scripts/test-vm-migration.sh
```

**What the script does**:
1. Checks if the VM exists
2. Starts the VM if not running
3. Waits for VM to be ready
4. Creates a `VirtualMachineInstanceMigration` object
5. Monitors migration progress
6. Reports success/failure

### Manual Migration Testing

1. **Ensure VM is running**:
   ```bash
   kubectl get vm fedora-vm -n virtualmachines
   kubectl patch vm fedora-vm -n virtualmachines --type merge -p '{"spec":{"running":true}}'
   ```

2. **Trigger migration**:
   ```bash
   kubectl create -f - <<EOF
   apiVersion: kubevirt.io/v1
   kind: VirtualMachineInstanceMigration
   metadata:
     name: test-migration-$(date +%s)
     namespace: virtualmachines
   spec:
     vmiName: fedora-vm
   EOF
   ```

3. **Monitor migration**:
   ```bash
   kubectl get vmim -n virtualmachines -w
   kubectl get events -n virtualmachines --sort-by=.lastTimestamp
   ```

## Querying Logs in Grafana

### Access Grafana

Navigate to: `https://grafana.talos.froystein.jp`

### LogQL Queries for VM Migrations

1. **All KubeVirt events from OpenTelemetry**:
   ```logql
   {service_name="kubevirt-events"}
   ```

2. **Only VirtualMachineInstanceMigration events**:
   ```logql
   {service_name="kubevirt-events"} |= "VirtualMachineInstanceMigration"
   ```

3. **Migration success events**:
   ```logql
   {service_name="kubevirt-events"} |= "Migration" |= "Succeeded"
   ```

4. **Migration failures**:
   ```logql
   {service_name="kubevirt-events"} |= "Migration" |= "Failed"
   ```

5. **Events for specific VM**:
   ```logql
   {service_name="kubevirt-events"} |= "fedora-vm"
   ```

6. **Migration events in last hour**:
   ```logql
   {service_name="kubevirt-events"} |= "Migration" | json | __timestamp__ > now() - 1h
   ```

### Creating a Dashboard

You can create a Grafana dashboard to visualize VM migrations:

1. **Panel 1**: Recent migration events (Table)
   - Query: `{service_name="kubevirt-events"} |= "Migration"`
   - Visualization: Table
   - Columns: Time, Event Reason, Message, VM Name

2. **Panel 2**: Migration count over time (Graph)
   - Query: `count_over_time({service_name="kubevirt-events"} |= "Migration"[5m])`
   - Visualization: Time series

3. **Panel 3**: Migration success/failure ratio (Stat)
   - Query 1: `count_over_time({service_name="kubevirt-events"} |= "Migration" |= "Succeeded"[24h])`
   - Query 2: `count_over_time({service_name="kubevirt-events"} |= "Migration" |= "Failed"[24h])`
   - Visualization: Stat

## Troubleshooting

### No Events in Loki

1. **Check OpenTelemetry Collector logs**:
   ```bash
   kubectl logs -n otel-collector -l app.kubernetes.io/name=opentelemetry-collector
   ```

   Look for:
   - Connection errors to Loki
   - Event reception from Kubernetes API

2. **Check Loki logs**:
   ```bash
   kubectl logs -n loki -l app.kubernetes.io/name=loki
   ```

   Look for:
   - OTLP receiver errors
   - Ingestion errors

3. **Verify RBAC**:
   ```bash
   kubectl get clusterrole otel-collector-opentelemetry-collector
   kubectl get clusterrolebinding otel-collector-opentelemetry-collector
   ```

### OpenTelemetry Collector Not Receiving Events

1. **Check if events exist**:
   ```bash
   kubectl get events -n virtualmachines
   ```

2. **Verify collector configuration**:
   ```bash
   kubectl get configmap -n otel-collector
   kubectl describe configmap -n otel-collector otel-collector-opentelemetry-collector
   ```

### Loki Storage Issues

1. **Check PVC**:
   ```bash
   kubectl get pvc -n loki
   kubectl describe pvc -n loki
   ```

2. **Check Longhorn volume**:
   ```bash
   kubectl get volumes -n longhorn-system
   ```

### Grafana Not Showing Loki Datasource

1. **Restart Grafana pod**:
   ```bash
   kubectl rollout restart deployment/kube-prom-stack-grafana -n monitoring
   ```

2. **Check datasource configuration**:
   ```bash
   kubectl exec -n monitoring deploy/kube-prom-stack-grafana -- \
     cat /etc/grafana/provisioning/datasources/* | grep -A 10 Loki
   ```

## Performance Considerations

- **Event Volume**: Watches all namespaces but filters to only VirtualMachineInstance events, reducing noise
- **Resource Filtering**: Filter processor ensures only KubeVirt VM events are processed and stored
- **Batch Processing**: Events are batched (up to 1024 events or 10s timeout) before sending to Loki
- **Storage**: 50Gi with 7-day retention should be sufficient for typical homelab usage
- **Resource Limits**:
  - OpenTelemetry Collector: 256Mi-512Mi memory, 100m CPU
  - Loki: 1Gi-2Gi memory, 200m CPU

## Future Enhancements

Potential improvements to consider:

1. **Add metrics collection**: Scrape KubeVirt Prometheus metrics for migration duration, success rate
2. **Alerting**: Set up Loki ruler for alerts on migration failures
3. **Extended retention**: Increase to 30 or 90 days if needed
4. **Traces**: Add distributed tracing for complete observability stack
5. **Additional resource filters**: Extend filtering to capture other KubeVirt resources (DataVolumes, etc.)
6. **Multi-tenancy**: Enable Loki auth for separate log streams per team/namespace
7. **Structured log parsing**: Parse event messages into structured fields for better querying

## References

- [OpenTelemetry Collector Documentation](https://opentelemetry.io/docs/collector/)
- [Loki Documentation](https://grafana.com/docs/loki/latest/)
- [KubeVirt Documentation](https://kubevirt.io/user-guide/)
- [Kubernetes Events](https://kubernetes.io/docs/reference/kubernetes-api/cluster-resources/event-v1/)
- [LogQL Query Language](https://grafana.com/docs/loki/latest/query/)
