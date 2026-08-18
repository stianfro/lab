# Devbox On An External libvirt/KVM Host

These files run the devbox VM on an external libvirt/KVM host instead of
KubeVirt.

## Files

- `domain.xml`: libvirt domain definition (q35, host-passthrough CPU,
  8 vCPUs, 20 GiB RAM, virtio disk/net/balloon/rng, serial console,
  local VNC).
- `user-data`: cloud-init NoCloud user data. It matches the KubeVirt
  cloud-init config: user `stian` with SSH keys, SSH hardening, base
  packages, and the netplan DHCP file for `en*` interfaces.
- `meta-data`: cloud-init NoCloud metadata (instance id and hostname).

## Sizing Note

The KubeVirt VM used 32 GiB RAM. The external host has about 25 GiB
free, so the domain uses 20 GiB to leave headroom. Raise
`<memory>`/`<currentMemory>` if the host gains RAM. vCPU count stays
at 8 (4 cores, 2 threads).

## Networking

The domain attaches to bridge `br0` with fixed MAC
`52:54:00:6d:15:51`. Add a DHCP reservation on the LAN that maps this
MAC to `192.168.1.51`. The guest netplan config uses DHCP, so no guest
change is needed.

## Prepare The Root Disk

```bash
mkdir -p /mnt/cache/domains/devbox
curl -LO https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img
qemu-img convert -f qcow2 -O raw noble-server-cloudimg-amd64.img \
  /mnt/cache/domains/devbox/vdisk1.img
qemu-img resize -f raw /mnt/cache/domains/devbox/vdisk1.img 200G
```

Cloud-init grows the root filesystem to fill the disk on first boot.

## Build The Seed ISO

With `cloud-localds` (from the `cloud-image-utils` package):

```bash
cloud-localds /mnt/cache/domains/devbox/seed.iso user-data meta-data
```

Or with `genisoimage`:

```bash
genisoimage -output /mnt/cache/domains/devbox/seed.iso \
  -volid cidata -joliet -rock user-data meta-data
```

## Define And Start The Domain

Before you define the domain, confirm the emulator path on the host:

```bash
virsh capabilities | grep -o '<emulator>[^<]*</emulator>' | head -1
```

If the path differs from `/usr/bin/qemu-system-x86_64`, update the
`<emulator>` element in `domain.xml` first.

Also free the IP before first start: the cluster still announces
`192.168.1.51` through the `devbox-ssh` LoadBalancer Service while the
standby app is deployed. Remove or re-IP that Service (see
`apps/devbox/README.md`) before the new VM claims the address.

```bash
virsh define domain.xml
virsh start devbox
virsh console devbox
```

## Emergency Access

VNC listens on `127.0.0.1` with an auto-assigned port. Find the port
with `virsh vncdisplay devbox`, then reach it through an SSH tunnel to
the host. The serial console is available with `virsh console devbox`.

## After First Boot

Run `just devbox-converge` from the lab repo. Ansible already targets
`stian@192.168.1.51`, so no inventory change is needed.
