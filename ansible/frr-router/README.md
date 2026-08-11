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
- Static IP: the Pi keeps `192.168.1.159`. This was its DHCP lease. The
  playbook converts the NetworkManager connection to a static (manual)
  configuration with the same address.

## Manual Router Steps (TP-Link BE19000)

The owner must do these steps on the TP-Link BE19000:

1. Add a static route: `192.168.100.0/24` with next hop `192.168.1.159`.
2. Add a DHCP reservation for the Pi's MAC address, so no other device gets
   `192.168.1.159`.

## Converge

```bash
just frr-router-converge
```

## Wired Priority

The Pi is on wifi (`wlan0`, NM connection `preconfigured`) today. The
playbook pre-provisions a wired profile `lan-wired` on `eth0` with the same
static IP `192.168.1.159`. The IP follows the Pi, not the interface.

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
