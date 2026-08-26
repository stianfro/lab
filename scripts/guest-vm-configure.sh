#!/usr/bin/env bash
set -euo pipefail

readonly wireguard_image="lscr.io/linuxserver/wireguard:1.0.20260223-r0-ls120@sha256:3abfd4b82212106e357989750b9c0c9859aa511f5305a9a55c18c8de7198b655"
readonly config_dir="${GUEST_VM_CONFIG_DIR:-$HOME/.config/guest-vm}"
readonly vpn_config="${VPN_CONFIG_FILE:-$config_dir/vpn.yaml}"
readonly vault_namespace="${VAULT_NAMESPACE:-vault}"
readonly vault_pod="${VAULT_POD:-vault-0}"
readonly vault_path="guest-vm/config"

usage() {
  cat <<'EOF'
Usage: guest-vm-configure.sh [VPN WireGuard profile]

The script reads the VPN private key, preshared key, and tunnel address from the
profile. It reads public connection settings from the local VPN settings file,
generates the lab WireGuard server key pair on first use, and writes the exact
Vault secret at secret/guest-vm/config.

The default input files are:
  ~/.config/guest-vm/vpn.conf
  ~/.config/guest-vm/vpn.yaml
  ~/.config/guest-vm/guest-wg.pub
  ~/.config/guest-vm/guest-ssh.pub

Override them with VPN_PROFILE_FILE, VPN_CONFIG_FILE,
GUEST_WG_PUBLIC_KEY_FILE, and GUEST_SSH_PUBLIC_KEY_FILE. Missing public-key
files cause an interactive prompt.

The script prompts for a Vault token without echo. For unattended use, set
VAULT_TOKEN_FILE to a mode 0600 file that contains only the token.
EOF
}

die() {
  printf 'guest-vm configuration failed: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

trim() {
  local value=$1
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

ini_value() {
  local section=$1
  local key=$2
  local file=$3

  awk -v wanted_section="$section" -v wanted_key="$key" '
    function trim(value) {
      sub(/^[[:space:]]+/, "", value)
      sub(/[[:space:]]+$/, "", value)
      return value
    }
    {
      sub(/\r$/, "")
    }
    /^[[:space:]]*\[[^]]+\][[:space:]]*$/ {
      current_section = $0
      gsub(/^[[:space:]]*\[|\][[:space:]]*$/, "", current_section)
      next
    }
    current_section == wanted_section {
      separator = index($0, "=")
      if (separator == 0) {
        next
      }
      current_key = trim(substr($0, 1, separator - 1))
      if (current_key == wanted_key) {
        print trim(substr($0, separator + 1))
        exit
      }
    }
  ' "$file"
}

valid_wireguard_key() {
  local key=$1
  local size

  [[ "$key" =~ ^[A-Za-z0-9+/]{43}=$ ]] || return 1
  size="$(printf '%s' "$key" | base64 --decode 2>/dev/null | wc -c)" || return 1
  [[ "$size" -eq 32 ]]
}

normalize_ssh_public_key() {
  local key=$1
  local key_type
  local key_data
  local normalized

  read -r key_type key_data _ <<<"$key"
  [[ -n "$key_type" && -n "$key_data" ]] || return 1
  normalized="$key_type $key_data"
  printf '%s\n' "$normalized" | ssh-keygen -lf - >/dev/null 2>&1 || return 1
  printf '%s' "$normalized"
}

wg_genkey() {
  if command -v wg >/dev/null 2>&1; then
    wg genkey
    return
  fi

  docker run --rm --network none --read-only --cap-drop ALL \
    --entrypoint wg "$wireguard_image" genkey
}

wg_pubkey() {
  if command -v wg >/dev/null 2>&1; then
    wg pubkey
    return
  fi

  docker run --rm -i --network none --read-only --cap-drop ALL \
    --entrypoint wg "$wireguard_image" pubkey
}

prompt_if_empty() {
  local variable_name=$1
  local prompt=$2
  local value=${!variable_name:-}

  if [[ -z "$value" ]]; then
    [[ -r /dev/tty ]] || die "$variable_name is required when no terminal is available"
    read -r -p "$prompt" value </dev/tty
  fi
  printf -v "$variable_name" '%s' "$(trim "$value")"
}

if [[ $# -gt 1 ]]; then
  usage >&2
  exit 2
fi

readonly vpn_profile="${1:-${VPN_PROFILE_FILE:-$config_dir/vpn.conf}}"
[[ -r "$vpn_profile" ]] || die "cannot read VPN profile: $vpn_profile"
[[ -r "$vpn_config" ]] || die "cannot read VPN settings: $vpn_config"

for command in awk base64 docker jq kubectl ssh-keygen yq; do
  if [[ "$command" == docker ]] && command -v wg >/dev/null 2>&1; then
    continue
  fi
  require_command "$command"
done

vpn_service_provider="$(yq -r '.serviceProvider // ""' "$vpn_config")"
vpn_forwarded_port="$(yq -r '.forwardedPort // ""' "$vpn_config")"
vpn_ddns_name="$(yq -r '.ddnsName // ""' "$vpn_config")"
[[ "$vpn_service_provider" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || \
  die "the VPN service provider setting is invalid"
[[ "$vpn_forwarded_port" =~ ^[0-9]{1,5}$ ]] || \
  die "the VPN forwarded port setting is invalid"
((10#$vpn_forwarded_port >= 1 && 10#$vpn_forwarded_port <= 65535)) || \
  die "the VPN forwarded port is outside the valid range"
[[ "$vpn_ddns_name" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$ ]] || \
  die "the VPN DDNS name setting is invalid"

vpn_private_key="$(ini_value Interface PrivateKey "$vpn_profile")"
vpn_preshared_key="$(ini_value Peer PresharedKey "$vpn_profile")"
profile_addresses="$(ini_value Interface Address "$vpn_profile")"

valid_wireguard_key "$vpn_private_key" || \
  die "the VPN profile has no valid Interface PrivateKey"
valid_wireguard_key "$vpn_preshared_key" || \
  die "the VPN profile has no valid Peer PresharedKey"

profile_ipv4_address=""
IFS=',' read -r -a profile_address_list <<<"$profile_addresses"
for candidate in "${profile_address_list[@]}"; do
  candidate="$(trim "$candidate")"
  if [[ "$candidate" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; then
    profile_ipv4_address=$candidate
    break
  fi
done
[[ -n "$profile_ipv4_address" ]] || \
  die "the VPN profile has no IPv4 Interface Address"
vpn_tunnel_address="$profile_ipv4_address"
guest_wg_public_key="${GUEST_WG_PUBLIC_KEY:-}"
guest_ssh_public_key="${GUEST_SSH_PUBLIC_KEY:-}"
unset GUEST_SSH_PUBLIC_KEY
guest_wg_public_key_file="${GUEST_WG_PUBLIC_KEY_FILE:-$config_dir/guest-wg.pub}"
guest_ssh_public_key_file="${GUEST_SSH_PUBLIC_KEY_FILE:-$config_dir/guest-ssh.pub}"
if [[ -n "${GUEST_WG_PUBLIC_KEY_FILE:-}" && ! -r "$guest_wg_public_key_file" ]]; then
  die "cannot read GUEST_WG_PUBLIC_KEY_FILE: $guest_wg_public_key_file"
fi
if [[ -r "$guest_wg_public_key_file" ]]; then
  IFS= read -r guest_wg_public_key <"$guest_wg_public_key_file"
fi
if [[ -n "${GUEST_SSH_PUBLIC_KEY_FILE:-}" && ! -r "$guest_ssh_public_key_file" ]]; then
  die "cannot read GUEST_SSH_PUBLIC_KEY_FILE: $guest_ssh_public_key_file"
fi
if [[ -r "$guest_ssh_public_key_file" ]]; then
  IFS= read -r guest_ssh_public_key <"$guest_ssh_public_key_file"
fi

vault_token="${VAULT_TOKEN:-}"
unset VAULT_TOKEN
if [[ -n "${VAULT_TOKEN_FILE:-}" ]]; then
  [[ -r "$VAULT_TOKEN_FILE" ]] || die "cannot read VAULT_TOKEN_FILE: $VAULT_TOKEN_FILE"
  IFS= read -r vault_token <"$VAULT_TOKEN_FILE"
fi
if [[ -z "$vault_token" ]]; then
  [[ -r /dev/tty ]] || die "VAULT_TOKEN_FILE is required when no terminal is available"
  read -r -s -p 'Vault token: ' vault_token </dev/tty
  printf '\n' >/dev/tty
fi
[[ -n "$vault_token" ]] || die "Vault token is empty"

kubectl_text=${KUBECTL:-kubectl}
read -r -a kubectl_cmd <<<"$kubectl_text"

vault_call() {
  printf '%s\n' "$vault_token" | \
    "${kubectl_cmd[@]}" exec -i -n "$vault_namespace" "$vault_pod" -- \
      sh -ec 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec vault "$@"' \
      vault "$@"
}

vault_put() {
  local payload_file=$1
  shift
  {
    printf '%s\n' "$vault_token"
    cat "$payload_file"
  } | "${kubectl_cmd[@]}" exec -i -n "$vault_namespace" "$vault_pod" -- \
    sh -ec 'IFS= read -r VAULT_TOKEN; export VAULT_TOKEN; exec vault "$@"' \
    vault "$@"
}

vault_call token lookup >/dev/null || die "Vault token authentication failed"

work_dir="$(mktemp -d)"
chmod 0700 "$work_dir"
cleanup() {
  rm -rf "$work_dir"
  unset vpn_private_key vpn_preshared_key guest_ssh_public_key vault_token wg_server_private_key
}
trap cleanup EXIT

existing_file="$work_dir/existing.json"
existing_error="$work_dir/existing.error"
if vault_call kv get -format=json -mount=secret "$vault_path" \
  >"$existing_file" 2>"$existing_error"; then
  jq -e '.data.data | type == "object"' "$existing_file" >/dev/null || \
    die "Vault returned an unexpected value for secret/$vault_path"
else
  if grep -Fq 'No value found' "$existing_error"; then
    printf '{"data":{"data":{}}}\n' >"$existing_file"
  else
    cat "$existing_error" >&2
    die "cannot read secret/$vault_path"
  fi
fi

if [[ -z "$guest_wg_public_key" ]]; then
  guest_wg_public_key="$(jq -r '.data.data.guest_wg_public_key // empty' "$existing_file")"
fi
if [[ -z "$guest_ssh_public_key" ]]; then
  guest_ssh_public_key="$(jq -r '.data.data.guest_ssh_public_key // empty' "$existing_file")"
fi

prompt_if_empty guest_wg_public_key 'Remote gateway WireGuard public key: '
prompt_if_empty guest_ssh_public_key 'Guest SSH public key: '

valid_wireguard_key "$guest_wg_public_key" || \
  die "remote gateway WireGuard public key is invalid"
guest_ssh_public_key="$(normalize_ssh_public_key "$guest_ssh_public_key")" || \
  die "guest SSH public key is invalid"

wg_server_private_key="$(jq -r '.data.data.wg_server_private_key // empty' "$existing_file")"
wg_server_public_key="$(jq -r '.data.data.wg_server_public_key // empty' "$existing_file")"
if [[ -z "$wg_server_private_key" && -z "$wg_server_public_key" ]]; then
  wg_server_private_key="$(wg_genkey)"
  wg_server_public_key="$(printf '%s\n' "$wg_server_private_key" | wg_pubkey)"
  printf 'Generated a new lab WireGuard server key pair.\n'
elif [[ -z "$wg_server_private_key" || -z "$wg_server_public_key" ]]; then
  die "Vault contains only one half of the lab WireGuard server key pair"
else
  valid_wireguard_key "$wg_server_private_key" || \
    die "Vault contains an invalid lab WireGuard server private key"
  valid_wireguard_key "$wg_server_public_key" || \
    die "Vault contains an invalid lab WireGuard server public key"
  derived_server_public_key="$(printf '%s\n' "$wg_server_private_key" | wg_pubkey)"
  [[ "$derived_server_public_key" == "$wg_server_public_key" ]] || \
    die "the lab WireGuard server keys in Vault do not match"
  printf 'Kept the existing lab WireGuard server key pair.\n'
fi

payload_file="$work_dir/payload.json"
printf '%s' "$vpn_service_provider" >"$work_dir/vpn-service-provider"
printf '%s' "$vpn_private_key" >"$work_dir/vpn-private-key"
printf '%s' "$vpn_preshared_key" >"$work_dir/vpn-preshared-key"
printf '%s' "$vpn_tunnel_address" >"$work_dir/vpn-tunnel-address"
printf '%s' "$vpn_ddns_name" >"$work_dir/vpn-ddns-name"
printf '%s' "$vpn_forwarded_port" >"$work_dir/vpn-forwarded-port"
printf '%s' "$wg_server_private_key" >"$work_dir/wg-server-private-key"
printf '%s' "$wg_server_public_key" >"$work_dir/wg-server-public-key"
printf '%s' "$guest_wg_public_key" >"$work_dir/guest-wg-public-key"
printf '%s' "$guest_ssh_public_key" >"$work_dir/guest-ssh-public-key"
chmod 0600 "$work_dir"/*
jq -n \
  --rawfile vpn_service_provider "$work_dir/vpn-service-provider" \
  --rawfile vpn_private_key "$work_dir/vpn-private-key" \
  --rawfile vpn_preshared_key "$work_dir/vpn-preshared-key" \
  --rawfile vpn_tunnel_address "$work_dir/vpn-tunnel-address" \
  --rawfile vpn_ddns_name "$work_dir/vpn-ddns-name" \
  --rawfile vpn_forwarded_port "$work_dir/vpn-forwarded-port" \
  --rawfile wg_server_private_key "$work_dir/wg-server-private-key" \
  --rawfile wg_server_public_key "$work_dir/wg-server-public-key" \
  --rawfile guest_wg_public_key "$work_dir/guest-wg-public-key" \
  --rawfile guest_ssh_public_key "$work_dir/guest-ssh-public-key" \
  '{
    vpn_service_provider: $vpn_service_provider,
    vpn_private_key: $vpn_private_key,
    vpn_preshared_key: $vpn_preshared_key,
    vpn_tunnel_address: $vpn_tunnel_address,
    vpn_ddns_name: $vpn_ddns_name,
    vpn_forwarded_port: $vpn_forwarded_port,
    wg_server_private_key: $wg_server_private_key,
    wg_server_public_key: $wg_server_public_key,
    guest_wg_public_key: $guest_wg_public_key,
    guest_ssh_public_key: $guest_ssh_public_key
  }' >"$payload_file"
chmod 0600 "$payload_file"

vault_put "$payload_file" kv put -mount=secret "$vault_path" @/dev/stdin >/dev/null || \
  die "cannot write secret/$vault_path"

vault_call kv get -format=json -mount=secret "$vault_path" | \
  jq -e \
    --arg server_public_key "$wg_server_public_key" \
    --arg guest_public_key "$guest_wg_public_key" \
    --rawfile guest_ssh_public_key "$work_dir/guest-ssh-public-key" \
    '.data.data as $secret
     | ($secret | keys | sort) == ([
         "vpn_ddns_name",
         "vpn_forwarded_port",
         "vpn_preshared_key",
         "vpn_private_key",
         "vpn_service_provider",
         "vpn_tunnel_address",
         "guest_ssh_public_key",
         "guest_wg_public_key",
         "wg_server_private_key",
         "wg_server_public_key"
       ] | sort)
     and $secret.wg_server_public_key == $server_public_key
     and $secret.guest_wg_public_key == $guest_public_key
     and $secret.guest_ssh_public_key == $guest_ssh_public_key' >/dev/null || \
  die "Vault verification failed after the write"

printf 'Configured secret/%s. No private key was written to Git.\n' "$vault_path"
printf 'Lab WireGuard server public key: %s\n' "$wg_server_public_key"
