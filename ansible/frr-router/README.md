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

## Switch From Wifi To eth0

The Pi is on wifi (`wlan0`, NM connection `preconfigured`) today. To move it
to a cable:

1. Connect the ethernet cable to the Pi.
2. Set these values in `group_vars/frr_routers.yaml`:
   - `frr_lan_interface: eth0`
   - `frr_nm_connection: "Wired connection 1"`
3. Run `just frr-router-converge` again. This sets the static IP on the wired
   profile and disables autoconnect on the wifi profile.
4. Run `nmcli con down preconfigured` on the Pi, or reboot it. This completes
   the switch. The playbook does not take wlan0 down, because you can be
   connected through it.

## Validation

Run these commands on the Pi:

```bash
sudo vtysh -c 'show bgp summary'
sudo vtysh -c 'show ip bgp'
ip route
```

Expect one BGP session per cluster node in `show bgp summary`. Expect /32
routes for LoadBalancer IPs via the node IPs in `ip route`.
