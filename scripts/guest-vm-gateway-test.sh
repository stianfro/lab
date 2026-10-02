#!/usr/bin/env bash
set -euo pipefail

manifest=apps/guest-vm/gateway.yaml
container='.spec.template.spec.containers[] | select(.name == "outer-vpn")'
yq eval -e "$container | select(.command[0] == \"/bin/sh\" and .command[1] == \"-ec\" and .command[2] == null)" "$manifest" >/dev/null
startup="$(yq eval -r "$container | .args[0]" "$manifest")"
printf '%s\n' "$startup" | sh -n
[[ "$startup" == *'exec /gluetun-entrypoint' ]]

# Run the actual startup shell with fake routing commands. The fake rejects
# broad deletions that could remove the inner tunnel's or Kubernetes' rules.
test_startup="${startup//exec \/gluetun-entrypoint/gluetun_test_entrypoint}"
for counts in '0 0' '1 0' '0 1' '3 2'; do
  read -r ipv4 ipv6 <<<"$counts"
  IPV4_RULES="$ipv4" IPV6_RULES="$ipv6" STARTUP="$test_startup" sh -ec '
    calls=0
    expected_calls=$((IPV4_RULES + IPV6_RULES + 2))
    ip() {
      family=$1
      shift
      if [ "$*" != "rule del priority 101 not fwmark 51820 table 51820" ]; then
        echo "Unexpected routing command: $*" >&2
        exit 1
      fi
      calls=$((calls + 1))
      case "$family" in
        -4)
          [ "$IPV4_RULES" -gt 0 ] || return 2
          IPV4_RULES=$((IPV4_RULES - 1))
          ;;
        -6)
          [ "$IPV6_RULES" -gt 0 ] || return 2
          IPV6_RULES=$((IPV6_RULES - 1))
          ;;
        *) exit 1 ;;
      esac
    }
    gluetun_test_entrypoint() {
      [ "$IPV4_RULES" -eq 0 ]
      [ "$IPV6_RULES" -eq 0 ]
      [ "$calls" -eq "$expected_calls" ]
      started=true
    }
    started=false
    eval "$STARTUP"
    [ "$started" = true ]
  '
  printf 'Gateway startup passed with %s IPv4 and %s IPv6 stale rules.\n' "$ipv4" "$ipv6"
done
