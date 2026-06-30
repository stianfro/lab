# Lessons Learned

Issues encountered while setting up the homelab cluster, documented so the same mistakes are not repeated.

---

## Dex does not expand environment variables in config files

**Context:** Dex OIDC provider deployment.

Dex v2.44.0 does not support `${VAR}` environment variable substitution in its config file. Setting secrets as env vars and referencing them as `${MY_SECRET}` in the config YAML silently fails - the literal string `${MY_SECRET}` is used instead, causing `invalid_client` errors.

**Fix:** Store the full rendered Dex config (with real secrets already substituted) in Vault at `secret/dex/config`. Use a VaultStaticSecret to sync it to a Kubernetes Secret, and reference that secret via `configSecret.create: false, name: dex-config` in the Helm chart.

---

## Vault OIDC role with groups_claim fails when Dex returns empty groups array

**Context:** Vault OIDC login via Dex.

If a Vault OIDC role is configured with `groups_claim=groups` but the user has no groups, Dex returns `"groups": []` (empty array). Vault treats this as the claim being absent and returns: "Authentication failed: failed to fetch groups: 'groups' claim not found in token".

**Fix:** Clear `groups_claim` on the Vault role if group-based access control is not needed:

```bash
vault write auth/oidc/role/admin \
  ... \
  groups_claim=""
```

Verify with `vault read auth/oidc/role/admin` and confirm `groups_claim = n/a`.

---

## Headlamp OIDC requires kube-apiserver OIDC configuration

**Context:** Headlamp Kubernetes dashboard with Dex OIDC.

The plan stated "no API server changes required" because Headlamp uses an in-cluster service account. This is wrong for OIDC mode. Headlamp v0.41.0 uses the OIDC id_token from the browser cookie as the `Authorization: Bearer` token for ALL Kubernetes API proxy calls. Without `--oidc-issuer-url` and related flags on kube-apiserver, every API call returns 401, and the user is bounced back to the sign-in page immediately after the OIDC popup closes.

**Fix:** Configure kube-apiserver with OIDC flags pointing at the Dex issuer (see `talos/patches/apiserver-oidc.yaml`). The `ClusterRoleBinding` for the authenticated user email must also exist so the API calls are authorized.

---

## `talosctl patch machineconfig` is broken in Talos v1.11.3

**Context:** Applying kube-apiserver extraArgs via `just patch`.

`talosctl patch machineconfig --patch @file` (RFC 6902 JSON Patch format) fails with:

```
failure applying rfc6902 patches to talos machine config:
json: cannot unmarshal string into Go value of type jsonpatch.partialDoc
```

This affects ALL patches, including pre-existing ones. The root cause is that Talos v1.11.3 stores the machine config as a YAML literal block string inside the resource spec. The jsonpatch library cannot operate on a string value.

**Workaround:** Read the config from the node, modify it with yq, and apply via `talosctl apply-config`:

```bash
talosctl get machineconfig v1alpha1 -o jsonpath='{.spec}' \
  --endpoints $node --nodes $node | \
  tail -n +2 | sed 's/^    //' | \
  yq '.cluster.apiServer.extraArgs."oidc-issuer-url" = "https://dex.talos.froystein.jp"' | \
  talosctl apply-config --file /dev/stdin \
  --endpoints $node --nodes $node --mode no-reboot
```

Use `--mode no-reboot` to restart only the affected component (e.g. kube-apiserver) without rebooting the node. Run `--dry-run` first to inspect the diff.

---

## Headlamp Helm chart: set clientSecret via externalSecret, not direct value

**Context:** Headlamp OIDC client secret injection.

When `config.oidc.clientSecret` is set in Helm values (even to an empty string `""`), Headlamp passes `--oidc-client-secret=` as a CLI flag, which overrides any env var approach. The flag takes precedence even when blank.

**Fix:** Use `config.oidc.externalSecret.enabled: true` with the name of the Kubernetes Secret created by VaultStaticSecret. Headlamp then uses `envFrom: [{secretRef: {name: ...}}]` and passes `$(OIDC_CLIENT_SECRET)` as the CLI arg, which correctly resolves from the secret.
