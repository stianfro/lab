#!/usr/bin/env bash
set -euo pipefail

namespace=guest-vm
gateway_selector=app.kubernetes.io/name=guest-vm-gateway
interface=gve2e
client_address=10.203.77.3
client_cidr="$client_address/32"
server_address=10.203.77.1
server_cidr="$server_address/32"
test_user="codex-e2e-${BASHPID}"
tmpdir="$(mktemp -d)"
peer_added=false
route_added=false
interface_added=false
guest_user_added=false
launcher=
gateway_pod=
client_public_key=
domain=

qga_exec() {
  local script=$1
  local payload response pid status exited exitcode output error_output
  local attempt

  payload="$(
    jq -cn --arg script "$script" \
      '{execute:"guest-exec",arguments:{path:"/bin/sh",arg:["-c",$script],"capture-output":true}}'
  )"
  response="$(
    kubectl -n "$namespace" exec "$launcher" -c compute -- \
      virsh qemu-agent-command "$domain" "$payload"
  )"
  pid="$(jq -er '.return.pid' <<<"$response")"

  for ((attempt = 0; attempt < 50; attempt++)); do
    payload="$(
      jq -cn --argjson pid "$pid" \
        '{execute:"guest-exec-status",arguments:{pid:$pid}}'
    )"
    status="$(
      kubectl -n "$namespace" exec "$launcher" -c compute -- \
        virsh qemu-agent-command "$domain" "$payload"
    )"
    exited="$(jq -r '.return.exited // false' <<<"$status")"
    if [[ "$exited" == true ]]; then
      exitcode="$(jq -r '.return.exitcode // 1' <<<"$status")"
      output="$(
        jq -r '.return["out-data"] // empty' <<<"$status" \
          | base64 --decode 2>/dev/null || true
      )"
      error_output="$(
        jq -r '.return["err-data"] // empty' <<<"$status" \
          | base64 --decode 2>/dev/null || true
      )"
      [[ -z "$output" ]] || printf '%s' "$output"
      [[ -z "$error_output" ]] || printf '%s' "$error_output" >&2
      [[ "$exitcode" -eq 0 ]]
      return
    fi
    sleep 0.2
  done

  printf 'Timed out while waiting for the VM guest agent.\n' >&2
  return 1
}

cleanup() {
  local exitcode=$?
  trap - EXIT INT TERM
  set +e

  if [[ "$guest_user_added" == true && -n "$launcher" ]]; then
    qga_exec "userdel --remove $test_user >/dev/null 2>&1 || true" >/dev/null
  fi
  if [[ "$interface_added" == true ]]; then
    sudo ip link delete "$interface" >/dev/null 2>&1
  fi
  if [[ "$peer_added" == true && -n "$gateway_pod" ]]; then
    kubectl -n "$namespace" exec "$gateway_pod" -c wireguard -- \
      wg set wg0 peer "$client_public_key" remove >/dev/null
  fi
  if [[ "$route_added" == true && -n "$gateway_pod" ]]; then
    kubectl -n "$namespace" exec "$gateway_pod" -c wireguard -- \
      ip route delete "$client_cidr" dev wg0 >/dev/null 2>&1
  fi
  rm -rf "$tmpdir"
  exit "$exitcode"
}
trap cleanup EXIT INT TERM

for command in base64 flock getent ip jq kubectl ssh ssh-keygen sudo wg; do
  if ! command -v "$command" >/dev/null; then
    printf 'Required command not found: %s\n' "$command" >&2
    exit 1
  fi
done
if ! sudo -n true; then
  printf 'Passwordless sudo is required to create the temporary WireGuard interface.\n' >&2
  exit 1
fi

exec 9>/tmp/guest-vm-e2e.lock
if ! flock -n 9; then
  printf 'Another guest VM end-to-end test is running.\n' >&2
  exit 1
fi

read_secret() {
  kubectl -n "$namespace" get secret guest-vm-connection \
    -o "jsonpath={.data.${1}}" | base64 --decode
}

endpoint="$(read_secret endpoint)"
port="$(read_secret forwarded_port)"
server_public_key="$(read_secret server_public_key)"
endpoint_ipv4="$(getent ahostsv4 "$endpoint" | awk 'NR == 1 { print $1; exit }')"
if [[ -z "$endpoint_ipv4" ]]; then
  printf 'The remote endpoint has no IPv4 address.\n' >&2
  exit 1
fi

gateway_pod="$(
  kubectl -n "$namespace" get pod -l "$gateway_selector" \
    -o jsonpath='{.items[0].metadata.name}'
)"
launcher="$(
  kubectl -n "$namespace" get pod -l kubevirt.io=virt-launcher \
    -o jsonpath='{.items[0].metadata.name}'
)"
domain="$(
  kubectl -n "$namespace" exec "$launcher" -c compute -- \
    virsh domid guest-vm_guest-vm
)"

umask 077
wg genkey >"$tmpdir/wg-private.key"
wg pubkey <"$tmpdir/wg-private.key" >"$tmpdir/wg-public.key"
client_public_key="$(<"$tmpdir/wg-public.key")"
ssh-keygen -q -t ed25519 -N '' -C temporary-devbox-e2e \
  -f "$tmpdir/ssh-key"

kubectl -n "$namespace" exec "$gateway_pod" -c wireguard -- \
  wg set wg0 peer "$client_public_key" allowed-ips "$client_cidr"
peer_added=true
kubectl -n "$namespace" exec "$gateway_pod" -c wireguard -- \
  ip route replace "$client_cidr" dev wg0
route_added=true

sudo ip link add "$interface" type wireguard
interface_added=true
sudo ip link set mtu 1280 dev "$interface"
sudo wg set "$interface" private-key "$tmpdir/wg-private.key" \
  peer "$server_public_key" \
  endpoint "$endpoint_ipv4:$port" \
  allowed-ips "$server_cidr" \
  persistent-keepalive 25
sudo ip address add "$client_cidr" dev "$interface"
sudo ip link set up dev "$interface"
sudo ip route replace "$server_cidr" dev "$interface"

printf 'Waiting for the public WireGuard handshake...\n'
handshake=0
for ((attempt = 0; attempt < 15; attempt++)); do
  handshake="$(sudo wg show "$interface" latest-handshakes | awk '{print $2}')"
  if ((handshake > 0)); then
    break
  fi
  sleep 1
done
if ((handshake == 0)); then
  printf 'The public WireGuard handshake timed out.\n' >&2
  exit 1
fi

public_key_base64="$(base64 -w0 <"$tmpdir/ssh-key.pub")"
guest_user_added=true
qga_exec "set -eu
useradd --create-home --shell /bin/bash $test_user
install -d -m 0700 -o $test_user -g $test_user /home/$test_user/.ssh
printf '%s' '$public_key_base64' | base64 --decode > /home/$test_user/.ssh/authorized_keys
chown $test_user:$test_user /home/$test_user/.ssh/authorized_keys
chmod 0600 /home/$test_user/.ssh/authorized_keys"

result="$(
  remote_command="test \"\$(id -un)\" = $test_user; test \"\$(hostname)\" = guest-vm; printf \"user=%s host=%s\" \"\$(id -un)\" \"\$(hostname)\""
  ssh -i "$tmpdir/ssh-key" \
    -o IdentitiesOnly=yes \
    -o StrictHostKeyChecking=accept-new \
    -o UserKnownHostsFile="$tmpdir/known_hosts" \
    -o ConnectTimeout=12 \
    "$test_user@$server_address" \
    "$remote_command"
)"

printf 'End-to-end SSH passed: %s\n' "$result"
