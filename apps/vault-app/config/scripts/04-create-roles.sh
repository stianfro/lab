#!/bin/bash
# Create Kubernetes auth roles
set -e

echo "Creating Kubernetes auth roles..."

# VSO role - allows Vault Secrets Operator to read secrets
# Note: bound_service_account_namespaces=* allows syncing secrets to any namespace
# Accepts both the VSO controller SA and the 'default' SA (for cross-namespace VaultAuth)
vault write auth/kubernetes/role/vault-secrets-operator \
    bound_service_account_names="vault-secrets-operator-controller-manager,default" \
    bound_service_account_namespaces="*" \
    policies=vso \
    ttl=1h

# Backup role - allows backup job to take snapshots
vault write auth/kubernetes/role/vault-backup \
    bound_service_account_names=vault-backup \
    bound_service_account_namespaces=vault \
    policies=backup \
    ttl=1h

echo "Roles created:"
vault list auth/kubernetes/role
