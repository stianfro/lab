# Netboot (PXE) Server

Headless network boot for the Talos nodes. Runs as three containers on
the container host at `192.168.1.10`. The goal: reinstall a node without
a screen, a keyboard, or a USB stick.

## How it works

1. `dnsmasq` runs in proxy-DHCP mode. It answers only the PXE part of
   the DHCP conversation. The router keeps assigning addresses, so the
   router config does not change.
2. The firmware PXE stack chainloads iPXE over TFTP (`snponly.efi` for
   UEFI, `undionly.kpxe` for BIOS).
3. iPXE fetches `boot.ipxe` over HTTP and asks for a per-node script at
   `nodes/<mac>.ipxe`.
4. When no script is staged for that MAC, iPXE exits and the firmware
   falls through to the next boot entry: the local disk. This makes a
   network-first boot order safe for daily reboots.
5. When a script is staged, the node boots the Talos PXE environment
   for the pinned Image Factory schematic and waits in maintenance mode
   for `talosctl apply-config`.

The `assets` init container downloads the iPXE binaries and mirrors the
Talos kernel and initramfs locally. Nodes never need internet access or
HTTPS support during netboot.

## Deploy

Keep a checkout of this repository on the container host. This
directory is the source of truth; do not copy the files out of it.

Preferred: register `netboot/docker-compose.yaml` as a stack in the
host's compose stack manager, pointed at the checkout path (an
external or indirect stack path). That gives autostart with the host's
storage lifecycle and a UI view, while git stays the only place the
stack is defined. Update flow: `git pull`, then redeploy the stack.

Fallback without a stack manager:

```bash
cd netboot
docker compose up -d
docker compose logs assets    # confirm downloads succeeded
```

The restart policies bring the containers back after a host reboot,
but only the stack manager ties startup to storage availability.

Port 8181 (HTTP) must be free on the host. TFTP (69/udp) and the
proxy-DHCP ports (67/udp, 4011/udp) bind on the host network.

If the schematic or Talos version changes, update the variables at the
top of `init/netboot-init.sh` (keep them in sync with
`talos/controlplane.yaml`), delete `http/talos/`, and run
`docker compose up -d` again.

## Reinstall a node

```bash
./stage.sh <node-mac>          # find the MAC in the router's client list
# power cycle the node
talosctl apply-config --insecure --nodes <node-ip> --file talos/controlplane.yaml
./unstage.sh <node-mac>        # do this as soon as the install starts
```

If the staged file stays in place, the node boots into maintenance mode
on every reboot instead of the installed system. Nothing is destroyed,
but the node does not come up until you unstage and power cycle it.

## One-time node preparation

Each node needs one firmware visit (screen required once):

- Put network boot (UEFI PXE, IPv4) first in the boot order.
- Keep Secure Boot off.

Exception: a machine with a blank disk usually tries network boot on
its own after finding no bootable disk. A fresh node with a new drive
can often be installed with zero screen time even before this firmware
change.

## Test without touching a real node

Create a throwaway VM on the libvirt host, attached to the same bridge:

```bash
virt-install --name pxe-test --memory 2048 --vcpus 1 --disk none \
  --pxe --boot uefi --network bridge=br0 --graphics none --noautoconsole
virsh console pxe-test
```

Unstaged MAC: the serial console shows iPXE fetch `boot.ipxe`, fail the
`nodes/` lookup, and exit. Staged MAC (`./stage.sh <vm-mac>`): it boots
the Talos kernel into maintenance mode. Clean up with
`virsh destroy pxe-test; virsh undefine pxe-test --nvram` and unstage
the MAC.

## Troubleshooting

- `docker compose logs dnsmasq` shows every PXE DHCP exchange
  (`log-dhcp` is on). No lines while a node boots means the broadcasts
  do not reach the host (check host networking on the dnsmasq
  container).
- iPXE loads but the script fetch fails: check that port 8181 answers,
  `curl http://192.168.1.10:8181/boot.ipxe`.
- Firmware that ignores proxy-DHCP menus exists. If a node's PXE stack
  times out at stage 1, that node needs the DHCP boot options served by
  the main DHCP server instead; handle that case only if it appears.
