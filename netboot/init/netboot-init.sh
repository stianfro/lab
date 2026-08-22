#!/bin/sh
# Downloads iPXE chainload binaries and the Talos PXE assets for the
# pinned schematic, then generates a Talos install script that boots
# from the local mirror (no HTTPS or internet needed at node boot time).
set -eu

# Keep these in sync with talos/controlplane.yaml (install.image).
SCHEMATIC=cb120f5908d584b52477963c9d095efa80750f4e4fdc48190eb68730cb749448
VERSION=v1.13.9
SERVER=http://192.168.1.10:8181
FACTORY=https://pxe.factory.talos.dev

apk add --no-cache curl >/dev/null

mkdir -p /tftpboot /http/nodes "/http/talos/$VERSION"

fetch() {
  # fetch <dest> <url>
  if [ ! -s "$1" ]; then
    echo "downloading $2"
    curl -fsSL -o "$1.tmp" "$2" && mv "$1.tmp" "$1"
  fi
}

fetch /tftpboot/undionly.kpxe https://boot.ipxe.org/undionly.kpxe
fetch /tftpboot/snponly.efi   https://boot.ipxe.org/x86_64-efi/snponly.efi

fetch "/http/talos/$VERSION/kernel-amd64" \
  "$FACTORY/image/$SCHEMATIC/$VERSION/kernel-amd64"
fetch "/http/talos/$VERSION/initramfs-amd64.xz" \
  "$FACTORY/image/$SCHEMATIC/$VERSION/initramfs-amd64.xz"

# The factory PXE endpoint returns a ready iPXE script with the correct
# kernel command line for the schematic. Rewrite its asset URLs to the
# local mirror so nodes never need internet or HTTPS during netboot.
if [ ! -s "/http/talos/$VERSION/boot.ipxe" ]; then
  echo "generating talos/$VERSION/boot.ipxe"
  curl -fsSL "$FACTORY/pxe/$SCHEMATIC/$VERSION/metal-amd64" \
    | sed "s#$FACTORY/image/$SCHEMATIC/$VERSION#$SERVER/talos/$VERSION#g" \
    > "/http/talos/$VERSION/boot.ipxe.tmp"
  grep -q '^#!ipxe' "/http/talos/$VERSION/boot.ipxe.tmp"
  mv "/http/talos/$VERSION/boot.ipxe.tmp" "/http/talos/$VERSION/boot.ipxe"
fi

echo "netboot assets ready:"
ls -l /tftpboot "/http/talos/$VERSION"
