#!/bin/sh
# Remove a staged install so the node boots from its local disk again.
# Usage: ./unstage.sh aa:bb:cc:dd:ee:ff
set -eu

DIR=$(dirname "$0")
[ $# -ge 1 ] || { echo "usage: $0 <mac>" >&2; exit 1; }
mac=$(printf '%s' "$1" | tr 'A-Z' 'a-z' | tr ':' '-')
rm -f "$DIR/http/nodes/$mac.ipxe"
echo "unstaged: $mac (next boot falls through to local disk)"
