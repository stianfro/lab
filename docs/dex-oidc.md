# Dex OIDC Provider

Dex is the OIDC provider for this cluster. It runs at `https://dex.talos.froystein.jp` and handles authentication for Headlamp and Vault by delegating to GitHub OAuth2.

## Architecture

```
Browser
  |
  | OIDC login (redirect)
  v
Dex (dex.talos.froystein.jp)
  |
  | OAuth2 (GitHub connector)
  v
GitHub
  |
  | callback with code
  v
Dex
  |
  | issues id_token (JWT) with email + groups claims
  v
Application (Headlamp / Vault)
```

## Deployment

- **Namespace:** `dex`
- **Helm chart:** `dex` from `https://charts.dexidp.io`, version 0.24.0 (Dex app v2.44.0)
- **Files:** `apps/dex/`

| File | Purpose |
|------|---------|
| `helmrelease.yaml` | Flux HelmRelease for the Dex chart |
| `vaultstaticsecret.yaml` | Syncs `secret/dex/secrets` from Vault to k8s Secret `dex-secrets` |
| `vaultstaticsecret-config.yaml` | Syncs `secret/dex/config` from Vault to k8s Secret `dex-config` |
| `httproute.yaml` | Envoy Gateway route at `dex.talos.froystein.jp` |
| `namespace.yaml` | `dex` namespace |

## Config Management

Dex config is stored as a fully rendered YAML string in Vault at `secret/dex/config` (key: `config`). A VaultStaticSecret syncs it to the `dex-config` Kubernetes Secret. The Helm chart is told not to create its own config secret:

```yaml
configSecret:
  create: false
  name: dex-config
```

**Why Vault and not a ConfigMap with env var substitution:** Dex v2.44.0 does not expand `${VAR}` environment variable references in its config file. Storing the fully rendered config in Vault is the only reliable way to inject secrets (client secrets, GitHub OAuth credentials) into the config.

### Updating the Dex Config

1. Fetch the current config: `vault kv get -field=config secret/dex/config`
2. Edit the value locally
3. Write it back: `vault kv put secret/dex/config config=@dex-config.yaml`
4. VSO syncs the updated secret within `refreshAfter: 60s`; Dex picks it up on the next config reload or pod restart

## Static OIDC Clients

The Dex config in Vault defines static clients. All client secrets are also stored in `secret/dex/secrets` for reference:

| Client ID | Redirect URI | Consumer |
|-----------|-------------|---------|
| `headlamp` | `https://headlamp.talos.froystein.jp/oidc-callback` | Headlamp dashboard |
| `vault` | `https://vault.talos.froystein.jp/ui/vault/auth/oidc/oidc/callback`, `http://localhost:8250/oidc/callback` | Vault UI + CLI |
If a `kargo` client is still present in the Vault-backed Dex config, it is stale and should be removed when the Vault secret is next edited.

## GitHub Connector

Dex authenticates users via GitHub OAuth2. The GitHub OAuth app credentials are stored in the Dex config in Vault. Dex issues tokens with:

- `email` claim: the user's GitHub email
- `groups` claim: empty array `[]` (no GitHub org/team mapping configured)

## Headlamp Integration

Headlamp uses the OIDC id_token issued by Dex as a Bearer token for all Kubernetes API proxy calls. This requires two things:

### 1. kube-apiserver OIDC flags

Applied via `talos/patches/apiserver-oidc.yaml` (see the [Talos patch note](#applying-config-to-talos) below):

```yaml
cluster:
  apiServer:
    extraArgs:
      oidc-issuer-url: https://dex.talos.froystein.jp
      oidc-client-id: headlamp
      oidc-username-claim: email
      oidc-groups-claim: groups
```

Without these flags the apiserver rejects all Dex-issued JWTs with 401, and Headlamp bounces the user back to the sign-in page immediately after the OIDC popup closes.

### 2. RBAC for the authenticated user

`apps/headlamp/clusterrolebinding.yaml` grants `cluster-admin` to the user's email as reported by Dex:

```yaml
subjects:
  - kind: User
    name: stianfroy@gmail.com
    apiGroup: rbac.authorization.k8s.io
```

### Client Secret in Headlamp

The Headlamp OIDC client secret is stored in Vault at `secret/headlamp/oidc` (key: `client-secret`). A VaultStaticSecret in `apps/headlamp/vaultstaticsecret.yaml` syncs it to the `headlamp-oidc` Kubernetes Secret. The chart uses:

```yaml
config:
  oidc:
    externalSecret:
      enabled: true
      name: headlamp-oidc
```

**Do not** set `config.oidc.clientSecret` in Helm values. If that field is present (even empty), Headlamp passes `--oidc-client-secret=` as a CLI flag which overrides the env var sourced from the secret.

## Vault Integration

Vault OIDC is configured to use Dex as the provider. The Vault OIDC role `admin` uses:

- `user_claim = email`
- `groups_claim = n/a` (cleared - Dex returns `groups: []` which Vault treats as missing)

If `groups_claim` is set to `groups`, Vault returns "Authentication failed: failed to fetch groups: 'groups' claim not found in token" for users with no group memberships.

To inspect the current role config:
```bash
vault read auth/oidc/role/admin
```

## Applying Config to Talos

The `talos/patches/apiserver-oidc.yaml` file documents the intended patch in RFC 6902 format, but `talosctl patch machineconfig` is broken in Talos v1.11.3 (see `docs/lessons-learned.md`). The config was applied using:

```bash
for node in 192.168.1.100 192.168.1.101 192.168.1.102; do
  talosctl get machineconfig v1alpha1 -o jsonpath='{.spec}' \
    --endpoints $node --nodes $node | \
    tail -n +2 | sed 's/^    //' | \
    yq '.cluster.apiServer.extraArgs."oidc-issuer-url" = "https://dex.talos.froystein.jp" |
        .cluster.apiServer.extraArgs."oidc-client-id" = "headlamp" |
        .cluster.apiServer.extraArgs."oidc-username-claim" = "email" |
        .cluster.apiServer.extraArgs."oidc-groups-claim" = "groups"' | \
    talosctl apply-config --file /dev/stdin \
      --endpoints $node --nodes $node --mode no-reboot
done
```

`--mode no-reboot` restarts only the apiserver process; no node reboot is needed.

## Troubleshooting

**`invalid_client` on redirect back from Dex:** The client secret in the Dex config does not match what the application is sending. Fetch and verify the config: `vault kv get -field=config secret/dex/config`.

**`groups claim not found in token` in Vault:** The Vault OIDC role has `groups_claim=groups` set but the token has an empty groups array. Run `vault write auth/oidc/role/admin groups_claim=""`.

**Headlamp stuck at sign-in after popup closes:** The kube-apiserver OIDC flags are not set or point to the wrong issuer. Check: `talosctl get staticpod kube-apiserver -o yaml --nodes <node> | grep oidc`.

**Dex pod crashlooping:** Config YAML in the Vault secret is malformed. Fetch it and validate: `vault kv get -field=config secret/dex/config | yq '.'`.
