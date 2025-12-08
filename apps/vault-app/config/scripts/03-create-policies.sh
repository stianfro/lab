#!/bin/bash
# Create Vault policies from HCL files
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
POLICIES_DIR="$SCRIPT_DIR/../policies"

echo "Creating Vault policies..."

for policy_file in "$POLICIES_DIR"/*.hcl; do
    if [ -f "$policy_file" ]; then
        policy_name=$(basename "$policy_file" .hcl)
        echo "Creating policy: $policy_name"
        vault policy write "$policy_name" "$policy_file"
    fi
done

echo "Policies created:"
vault policy list
