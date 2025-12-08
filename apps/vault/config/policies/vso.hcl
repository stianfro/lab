# VSO policy - allows Vault Secrets Operator to read secrets
# Used by vault-secrets-operator to sync secrets to Kubernetes

# Read secrets from the main secrets path
path "secret/*" {
  capabilities = ["read", "list"]
}

path "secret/data/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/*" {
  capabilities = ["read", "list"]
}

# Read secrets from the infrastructure path
path "infra/*" {
  capabilities = ["read", "list"]
}

path "infra/data/*" {
  capabilities = ["read", "list"]
}

path "infra/metadata/*" {
  capabilities = ["read", "list"]
}
