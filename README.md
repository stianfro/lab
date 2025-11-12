# Lab

My new homelab running Talos Linux.

![lab](https://github.com/user-attachments/assets/7610c388-37d5-419e-9917-5a834fe79f1c)

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

## Installation

Image used: [link](https://factory.talos.dev/?arch=amd64&cmdline-set=true&extensions=-&extensions=siderolabs%2Famdgpu&extensions=siderolabs%2Famd-ucode&extensions=siderolabs%2Fiscsi-tools&extensions=siderolabs%2Futil-linux-tools&platform=metal&target=metal&version=1.11.5)

```yaml
customization:
  systemExtensions:
    officialExtensions:
      - siderolabs/amd-ucode
      - siderolabs/amdgpu
      - siderolabs/iscsi-tools
      - siderolabs/util-linux-tools
```

## Bootstrap

After cluster installation, bootstrap Argo CD:

```bash
# install argo
just bootstrap

# create applicationset
just bootstrap-app
```
