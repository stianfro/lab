# Devbox

The primary devbox now runs on an external libvirt/KVM host. It owns the LAN
IP `192.168.1.51`. SSH, the static file server on port 80, the opencode web UI
on port 4096, and Node Exporter on port 9100 all run there. Ansible
(`just devbox-converge`) targets `stian@192.168.1.51` and works unchanged
against the libvirt VM.

The libvirt domain definition for the external VM lives in
`apps/devbox/libvirt/`.

## Cold standby

The KubeVirt VirtualMachine in this directory is a cold standby. Its
`runStrategy` is `Halted`, so Flux keeps the object reconciled but the VM does
not run. The `devbox-root` volume is retained. Take or verify a Longhorn
backup of `devbox-root` before you delete the standby or its volume.

Do not run the standby and the libvirt VM at the same time with the MetalLB
Service active. Both would answer on `192.168.1.51`.

To start the standby:

0. Confirm the libvirt VM is shut down, or remove or re-IP the `devbox-ssh`
   Service first. MetalLB runs in L2 mode: as soon as the standby pod backs
   the Service, the cluster answers ARP for `192.168.1.51` and fights the
   libvirt VM.

```bash
kubectl patch vm devbox -n devbox --type merge -p '{"spec":{"runStrategy":"Always"}}'
```

Or with virtctl:

```bash
virtctl start devbox -n devbox
```

Note: Flux reconciles `spec.runStrategy` back to `Halted` from Git. For more
than a short test, change the field in `vm.yaml` and commit, or suspend the
`devbox` Flux Kustomization first.

To stop it again, reverse the change (`runStrategy: Halted`, or
`virtctl stop devbox -n devbox`).

## Monitoring

Prometheus scrapes the Node Exporter endpoint through the
`devbox-node-exporter` Service and ServiceMonitor. This in-cluster scrape path
only produces data while the standby VM runs; with the VM halted, the Service
has no backing pod. Metrics from the primary devbox on the external host come
from the static `devbox` scrape job (`192.168.1.51:9100`) in
`apps/monitoring/helmrelease.yaml`.

The `Agent CLI Usage` Grafana dashboard reads aggregated Claude and Codex
usage from the devbox Node Exporter metrics.

The devbox systemd timer runs the local `usage-tracker.py metrics` command once
per minute. It writes `/var/lib/prometheus/node-exporter/usage.prom` atomically.
Node Exporter then publishes the file with its normal host metrics. The tracker
labels the four entry points as:

- `cla`, from `~/.claude/projects`
- `claude-personal`, from `~/.claude-personal/projects`
- `codex`, from interactive Codex rollouts
- `codex-exec`, from rollouts with the `codex_exec` origin

Raw transcript content stays on the devbox. Only token counts, model names,
estimated active time, session counts, and estimated costs reach Prometheus.

## Why this does not use OpenTelemetry

The existing cluster OpenTelemetry Collector receives OTLP traces and logs. It
does not parse Claude or Codex transcript formats. A devbox collector would
still need the same custom parser, another listener, and an OTLP metrics path.
The Node Exporter textfile collector is already installed and scraped, so it is
the smaller operational path for these host-owned metrics.

OpenTelemetry can be useful later if agent tools emit native spans. Those spans
can include request latency and tool timing without transcript estimates. Keep
that trace path separate from the transcript counter exporter.

## History

Prometheus range panels collect changes from the time this exporter starts.
The weekday/hour matrix is different: the tracker rebuilds it from all local
transcript history on each run, so it includes older activity immediately.
