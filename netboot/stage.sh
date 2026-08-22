#!/bin/sh
# Stage a Talos install for one node.
# Usage: ./stage.sh aa:bb:cc:dd:ee:ff [version]
# The next network boot of that MAC runs the Talos PXE environment
# (maintenance mode). Then apply the machine config from the repo:
#   talosctl apply-config --insecure --nodes <ip> --file talos/controlplane.yaml
# IMPORTANT: run ./unstage.sh for the same MAC as soon as the install
# starts, or the node keeps booting into maintenance mode instead of
# the installed system.
set -eu

VERSION=${2:-v1.12.4}
DIR=$(dirname "$0")

[ $# -ge 1 ] || { echo "usage: $0 <mac> [version]" >&2; exit 1; }
mac=$(printf '%s' "$1" | tr 'A-Z' 'a-z' | tr ':' '-')
case $mac in
  [0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]-[0-9a-f][0-9a-f]) ;;
  *) echo "invalid mac: $1" >&2; exit 1 ;;
esac

mkdir -p "$DIR/http/nodes"
cat > "$DIR/http/nodes/$mac.ipxe" <<EOF
#!ipxe
chain --replace http://192.168.1.10:8181/talos/$VERSION/boot.ipxe
EOF
echo "staged: $mac -> talos $VERSION"
echo "power cycle the node, then apply the machine config."
echo "remember: ./unstage.sh $1 once the install starts."
