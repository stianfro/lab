#!/bin/bash
# Enable KV v2 secrets engines
set -e

echo "Enabling KV v2 secrets engines..."

# Main secrets path
vault secrets enable -path=secret kv-v2 || echo "secret/ already enabled"

# Infrastructure secrets path
vault secrets enable -path=infra kv-v2 || echo "infra/ already enabled"

echo "KV v2 secrets engines enabled."
vault secrets list
