# Admin policy - full access to Vault
# Use sparingly, prefer more restrictive policies

path "*" {
  capabilities = ["create", "read", "update", "delete", "list", "sudo"]
}
