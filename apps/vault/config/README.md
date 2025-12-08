# Vault Configuration Scripts

This directory contains shell scripts and policies for configuring Vault.

## Prerequisites

1. Vault must be initialized and unsealed
2. You must be logged in with a token that has admin privileges

## Usage

Run the scripts in order from within a Vault pod:

```bash
# Get a shell in the Vault pod
kubectl exec -it vault-0 -n vault -- /bin/sh

# Login with root token
vault login

# Run scripts (copy from local or mount as ConfigMap)
./00-enable-audit.sh
./01-enable-kv-engine.sh
./02-enable-kubernetes-auth.sh
./03-create-policies.sh
./04-create-roles.sh
```

## Scripts

| Script | Purpose |
|--------|---------|
| `00-enable-audit.sh` | Enable audit logging to file |
| `01-enable-kv-engine.sh` | Enable KV v2 secrets engines at `secret/` and `infra/` |
| `02-enable-kubernetes-auth.sh` | Enable and configure Kubernetes authentication |
| `03-create-policies.sh` | Create policies from `policies/*.hcl` files |
| `04-create-roles.sh` | Create Kubernetes auth roles for VSO and backup |

## Policies

| Policy | Purpose |
|--------|---------|
| `admin.hcl` | Full admin access (use sparingly) |
| `backup.hcl` | Allows taking Raft snapshots |
| `vso.hcl` | Allows VSO to read secrets |
| `app-readonly.hcl` | Example policy for applications |

## Creating Application Roles

To allow an application to read secrets, create a Kubernetes auth role:

```bash
vault write auth/kubernetes/role/myapp \
    bound_service_account_names=myapp \
    bound_service_account_namespaces=myapp-namespace \
    policies=app-readonly \
    ttl=1h
```

Then create a VaultStaticSecret in your application namespace:

```yaml
apiVersion: secrets.hashicorp.com/v1beta1
kind: VaultStaticSecret
metadata:
  name: myapp-config
  namespace: myapp-namespace
spec:
  vaultAuthRef: vault/default
  mount: secret
  type: kv-v2
  path: myapp-namespace/config
  refreshAfter: 60s
  destination:
    name: myapp-config
    create: true
```
