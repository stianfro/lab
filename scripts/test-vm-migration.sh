#!/usr/bin/env bash

set -euo pipefail

# Configuration
VM_NAME="${VM_NAME:-fedora-vm}"
VM_NAMESPACE="${VM_NAMESPACE:-virtualmachines}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if VM exists
log_info "Checking if VM '$VM_NAME' exists in namespace '$VM_NAMESPACE'..."
if ! kubectl get vm "$VM_NAME" -n "$VM_NAMESPACE" &>/dev/null; then
    log_error "VM '$VM_NAME' not found in namespace '$VM_NAMESPACE'"
    exit 1
fi

log_info "VM '$VM_NAME' found"

# Check if VM is running
VM_STATUS=$(kubectl get vm "$VM_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.printableStatus}' 2>/dev/null || echo "Unknown")
log_info "VM status: $VM_STATUS"

if [[ "$VM_STATUS" != "Running" ]]; then
    log_warn "VM is not running (status: $VM_STATUS). Starting VM..."

    # Start the VM by setting spec.running to true
    kubectl patch vm "$VM_NAME" -n "$VM_NAMESPACE" --type merge -p '{"spec":{"running":true}}'

    log_info "Waiting for VM to start..."
    timeout=300
    elapsed=0
    while [[ "$VM_STATUS" != "Running" ]] && [[ $elapsed -lt $timeout ]]; do
        sleep 5
        elapsed=$((elapsed + 5))
        VM_STATUS=$(kubectl get vm "$VM_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.printableStatus}' 2>/dev/null || echo "Unknown")
        log_info "VM status: $VM_STATUS (waited ${elapsed}s)"
    done

    if [[ "$VM_STATUS" != "Running" ]]; then
        log_error "VM failed to start within ${timeout}s"
        exit 1
    fi

    log_info "VM is now running"
fi

# Get the VMI name (should match VM name)
VMI_NAME="$VM_NAME"

# Check if VMI is ready
log_info "Checking if VMI is ready..."
VMI_READY=$(kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")

if [[ "$VMI_READY" != "True" ]]; then
    log_warn "VMI is not ready yet. Waiting..."
    timeout=120
    elapsed=0
    while [[ "$VMI_READY" != "True" ]] && [[ $elapsed -lt $timeout ]]; do
        sleep 5
        elapsed=$((elapsed + 5))
        VMI_READY=$(kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null || echo "Unknown")
        log_info "VMI ready status: $VMI_READY (waited ${elapsed}s)"
    done

    if [[ "$VMI_READY" != "True" ]]; then
        log_error "VMI failed to become ready within ${timeout}s"
        exit 1
    fi
fi

log_info "VMI is ready"

# Get current node
CURRENT_NODE=$(kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.nodeName}')
log_info "VM is currently running on node: $CURRENT_NODE"

# Trigger migration
log_info "Triggering VM migration..."

# Create a VirtualMachineInstanceMigration object
MIGRATION_NAME="${VM_NAME}-migration-$(date +%s)"

cat <<EOF | kubectl apply -f -
apiVersion: kubevirt.io/v1
kind: VirtualMachineInstanceMigration
metadata:
  name: $MIGRATION_NAME
  namespace: $VM_NAMESPACE
spec:
  vmiName: $VMI_NAME
EOF

log_info "Migration object '$MIGRATION_NAME' created"

# Monitor migration progress
log_info "Monitoring migration progress..."
timeout=300
elapsed=0
MIGRATION_PHASE="Unknown"

while [[ "$MIGRATION_PHASE" != "Succeeded" ]] && [[ "$MIGRATION_PHASE" != "Failed" ]] && [[ $elapsed -lt $timeout ]]; do
    sleep 5
    elapsed=$((elapsed + 5))

    MIGRATION_PHASE=$(kubectl get vmim "$MIGRATION_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
    log_info "Migration phase: $MIGRATION_PHASE (waited ${elapsed}s)"

    # Show current and target nodes
    if kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" &>/dev/null; then
        CURRENT_NODE=$(kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.nodeName}')
        MIGRATION_TARGET=$(kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.migrationState.targetNode}' 2>/dev/null || echo "N/A")
        log_info "  Current node: $CURRENT_NODE"
        if [[ "$MIGRATION_TARGET" != "N/A" ]]; then
            log_info "  Target node: $MIGRATION_TARGET"
        fi
    fi
done

# Check final status
if [[ "$MIGRATION_PHASE" == "Succeeded" ]]; then
    NEW_NODE=$(kubectl get vmi "$VMI_NAME" -n "$VM_NAMESPACE" -o jsonpath='{.status.nodeName}')
    log_info "Migration succeeded! VM migrated to node: $NEW_NODE"

    log_info ""
    log_info "Check Loki logs in Grafana at: https://grafana.talos.froystein.jp"
    log_info "Use LogQL query: {service_name=\"kubevirt-events\"}"
elif [[ "$MIGRATION_PHASE" == "Failed" ]]; then
    log_error "Migration failed!"
    kubectl describe vmim "$MIGRATION_NAME" -n "$VM_NAMESPACE"
    exit 1
else
    log_error "Migration timed out after ${timeout}s"
    kubectl describe vmim "$MIGRATION_NAME" -n "$VM_NAMESPACE"
    exit 1
fi
