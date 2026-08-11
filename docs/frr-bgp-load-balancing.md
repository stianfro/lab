# BGP Service Load Balancing with FRR

This lab announces Kubernetes LoadBalancer addresses over BGP. The BGP
peer for the cluster is not a router: it is FRR on a Raspberry Pi 5,
attached to a consumer network whose gateway has no routing protocol
support. The point of this document is that a full BGP speaker can run
on any Linux host, and that one static route is enough to connect a
routed service prefix to a network that cannot participate in routing.

## Topology

```text
                        192.168.1.0/24 (LAN)
  clients ---+----------------+--------------------------+
             |                |                          |
     TP-Link BE19000    Raspberry Pi 5             3x Talos nodes
     default gateway    FRR 8.4, AS 64513          Cilium BGP, AS 64512
     no BGP support     192.168.1.2                192.168.1.100-102
             |                |                          |
             | static route   |  eBGP, one session       |
             | 192.168.100.0/24  per node                |
             | via 192.168.1.2  /32 per service VIP      |
             +----------------+--------------------------+
                              |
                    192.168.100.0/24
                    routed VIP prefix, no L2 segment
```

- Service VIPs are allocated from `192.168.100.0/24`. The prefix exists
  on no wire. It is reachable only through routing.
- Each Kubernetes node runs a BGP speaker (the Cilium CNI includes a
  BGP control plane; no extra daemon runs on the nodes). All nodes peer
  eBGP with FRR.
- FRR installs the received /32 host routes in the Linux kernel FIB and
  forwards between the LAN and the VIP prefix (`ip_forward=1`).
- The home router carries exactly one static route,
  `192.168.100.0/24 via 192.168.1.2`. That single route gives every LAN
  client access to every VIP, current and future.

## Why a routed VIP prefix

The previous design (MetalLB in layer 2 mode) placed VIPs inside the
LAN subnet. One elected node owned each VIP and answered ARP for it;
failover meant a new election plus gratuitous ARP, and convergence
depended on the ARP caches of every client. All traffic for a VIP also
funneled through that single node.

With BGP the VIP prefix moves out of the LAN. Ownership is expressed as
route advertisement instead of ARP: nodes that can serve a service
announce its /32, and failure is a route withdrawal with deterministic
timing. With multiple announcing nodes the design extends naturally to
ECMP.

## FRR configuration

The complete `/etc/frr/frr.conf`, deployed from `ansible/frr-router/`:

```text
frr defaults traditional
hostname frr-router
log syslog informational
service integrated-vtysh-config
!
router bgp 64513
 bgp router-id 192.168.1.2
 neighbor CILIUM peer-group
 neighbor CILIUM remote-as 64512
 neighbor CILIUM timers 3 9
 bgp listen range 192.168.1.0/24 peer-group CILIUM
 !
 address-family ipv4 unicast
  neighbor CILIUM route-map CILIUM-IN in
  neighbor CILIUM route-map DENY-ALL out
 exit-address-family
!
ip prefix-list LB-PREFIXES seq 10 permit 192.168.100.0/24 le 32
!
route-map CILIUM-IN permit 10
 match ip address prefix-list LB-PREFIXES
!
route-map DENY-ALL deny 10
```

Design notes:

- **Dynamic neighbors.** `bgp listen range` accepts any peer from the
  LAN subnet into the `CILIUM` peer group, the same mechanism as
  `bgp listen range ... peer-group` on IOS-XE. Adding a cluster node
  requires no FRR change. One caveat: FRR parses the file top down, and
  the peer group must exist before the listen range references it.
- **Policy required.** FRR ships with `ebgp-requires-policy`, the same
  posture as IOS-XR: an eBGP neighbor without inbound and outbound
  policy exchanges nothing. Inbound accepts only
  `192.168.100.0/24 le 32`. Outbound denies everything, because the
  cluster needs no routes from FRR; the nodes sit on the LAN and reach
  it directly.
- **Timers 3/9.** Cilium's open source BGP implementation has no BFD,
  so the hold timer bounds failure detection. 9 seconds fits this
  environment; the FRR defaults (60/180) do not.

## Cluster side

Four small custom resources in `apps/cilium-bgp/` configure the
speakers, the equivalent of the neighbor and address-family stanzas on
a Cisco box:

| Resource                   | Role                                            |
| -------------------------- | ----------------------------------------------- |
| CiliumBGPClusterConfig     | local AS 64512, peer 192.168.1.2 remote-as 64513 |
| CiliumBGPPeerConfig        | timers 3/9, graceful restart                    |
| CiliumBGPAdvertisement     | announce LoadBalancer /32s for selected services |
| CiliumLoadBalancerIPPool   | allocate VIPs from 192.168.100.0/24             |

The announcement respects Kubernetes service semantics. With
`externalTrafficPolicy: Local`, only nodes that host a backend pod
announce the /32. The route follows the workload: when the pod moves to
another node, the old node withdraws and the new node announces. In
this lab that reconvergence completes in under 10 seconds, most of it
pod scheduling time.

## Verification

FRR's `vtysh` uses the IOS command tree:

```text
frr-router# show bgp summary

Neighbor        V         AS   MsgRcvd   MsgSent   TblVer  InQ OutQ  Up/Down State/PfxRcd
*192.168.1.100  4      64512      1126      1119        0    0    0 00:55:50            0
*192.168.1.101  4      64512      1125      1123        0    0    0 00:56:02            1
*192.168.1.102  4      64512      1121      1124        0    0    0 00:08:04            0

* - dynamic neighbor
3 dynamic neighbor(s), limit 100
```

One VIP is active and its backend runs on the .101 node, so only that
neighbor advertises a prefix. The route in the kernel FIB:

```text
$ ip route | grep bgp
192.168.100.1 via 192.168.1.101 dev eth0 proto bgp metric 20
```

From any LAN client, through the router's static route:

```text
$ curl -s -o /dev/null -w '%{http_code}\n' http://192.168.100.1/
200
```

## Failure behavior

- Backend pod moves: immediate withdraw and announce, service
  reachable again in under 10 seconds.
- Node crash: no withdrawal is sent, so the hold timer (9 s) expires
  and FRR drops the routes through that peer.
- FRR host reboot: the VIP prefix is unreachable from the LAN while it
  is down; the cluster and the LAN itself are unaffected. Sessions
  re-establish without configuration on either side, because the nodes
  retry and FRR accepts dynamic neighbors.

## Translation table

| This lab                          | Cisco equivalent                        |
| --------------------------------- | --------------------------------------- |
| vtysh                             | IOS CLI (`show bgp summary`, `conf t`)  |
| `bgp listen range` + peer group   | IOS-XE dynamic neighbors                |
| `ebgp-requires-policy` default    | IOS-XR default eBGP policy behavior     |
| route-map + prefix-list           | identical concepts and syntax           |
| `/etc/frr/frr.conf`               | startup-config                          |
| Linux kernel FIB (`ip route`)     | RIB to FIB installation                 |
| Cilium BGP CRs                    | neighbor / address-family configuration |
| Raspberry Pi 5 + FRR              | the ToR this network does not have      |
