# FRR BGP Router (Raspberry Pi 5)

This directory configures the Raspberry Pi 5 as the FRR BGP router for the
lab cluster. It is phase 1 of issue #56: Cilium BGP and LB-IPAM run next to
MetalLB.

## Design

- ASN plan: the cluster (Cilium) uses ASN 64512. The Pi (FRR) uses ASN 64513.
  The sessions are eBGP.
- FRR accepts dynamic neighbors from `192.168.1.0/24` through a `CILIUM`
  peer group.
- FRR accepts only the LB prefix `192.168.100.0/24` (and its more specific
  routes, up to /32) from the cluster. FRR announces nothing to the cluster.
- Timers: 3 seconds keepalive, 9 seconds hold.
- Static IP: the Pi uses `192.168.1.2`. This address is low in the subnet,
  so it sits outside the usual DHCP pool. Verify the pool start in the
  router UI. If the pool starts above `.2`, no DHCP reservation is needed.
  The playbook configures the NetworkManager connection as a static
  (manual) configuration with this address.

## Manual Router Steps (TP-Link BE19000)

The owner must do these steps on the TP-Link BE19000:

1. Add a static route: `192.168.100.0/24` with next hop `192.168.1.2`.
2. Verify that the DHCP pool starts above `192.168.1.2`. If it does, no
   DHCP reservation is needed. If the pool includes `.2`, add a DHCP
   reservation for the Pi's MAC address so no other device gets the
   address.

## FRR Version

FRR comes from the FRRouting apt repository (`deb.frrouting.org`), channel
`frr_apt_channel`, package version `frr_package_version` in
`group_vars/frr_routers.yaml`. The Debian bookworm package (8.4.4) is not
used: its bgpd crashed when all three Cilium agents restarted at the same
time. To move to a new FRR release, bump both variables and converge. The
package upgrade restarts frr, so the BGP sessions drop for a few seconds.

## Converge

```bash
just frr-router-converge
```

### Changing The LAN IP

A converge that changes the LAN IP disconnects mid-play. NetworkManager
reapplies the wifi or wired profile with the new address, and the SSH
connection to the old address drops. Run the converge in two passes:

1. Run pass 1 against the old address. Append
   `-e ansible_host=<old-ip>` to the ansible-playbook command. Expect the
   play to drop when the IP changes.
2. Run the normal `just frr-router-converge`. It targets the new inventory
   address and completes FRR and the remaining tasks.

## Wired Priority

The Pi is on wifi (`wlan0`, NM connection `preconfigured`) today. The
playbook pre-provisions a wired profile `lan-wired` on `eth0` with the same
static IP `192.168.1.2`. The IP follows the Pi, not the interface.

A NetworkManager dispatcher script
(`/etc/NetworkManager/dispatcher.d/50-wired-priority`) prefers the wire
automatically:

- When `eth0` gets link, the script takes the wifi connection down. The IP
  moves to the wire.
- When `eth0` loses link, the script brings the wifi connection back as
  fallback.

To switch to the cable, plug it in. Wifi drops within seconds and `eth0`
takes over the same IP. BGP sessions re-establish within the hold time
(9 seconds). Unplug the cable to restore wifi.

During the switch there is a brief window where both interfaces claim the
IP. This is harmless, because both interfaces belong to the same host.

The wifi profile stays configured as fallback. Delete it manually only if
you want a wired-only setup.

## Validation

Run these commands on the Pi:

```bash
sudo vtysh -c 'show bgp summary'
sudo vtysh -c 'show ip bgp'
ip route
```

Expect one BGP session per cluster node in `show bgp summary`. Expect /32
routes for LoadBalancer IPs via the node IPs in `ip route`.
