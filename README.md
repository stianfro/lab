# Lab

My new homelab running Talos Linux.

## Hardware

- 3x Minisforum UM790 Pro Mini-PC
- 1x TP-Link TL-SG108-M2 8-Port 2.5G Switch

## Network

| Hostname | IP            | MAC               |
| -------- | ------------- | ----------------- |
| talos-0  | 192.168.1.100 | 58-47-CA-7F-C3-47 |
| talos-1  | 192.168.1.101 | 58-47-CA-7F-C2-9C |
| talos-2  | 192.168.1.102 | 58-47-CA-7F-C3-46 |

## DNS

```
talos.froystein.jp  IN  A  192.168.1.100
talos.froystein.jp  IN  A  192.168.1.101
talos.froystein.jp  IN  A  192.168.1.102
```

## Bootstrap

After cluster installation, bootstrap Argo CD:

```bash
# install argo
just bootstrap

# create applicationset
just bootstrap-app
```
