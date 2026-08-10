# Devbox monitoring

Prometheus scrapes the Node Exporter endpoint through the `devbox-node-exporter`
Service and ServiceMonitor. The `Agent CLI Usage` Grafana dashboard reads
aggregated Claude and Codex usage from that target.

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
