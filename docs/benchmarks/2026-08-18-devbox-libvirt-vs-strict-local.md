# Devbox Libvirt Host vs Strict-Local KubeVirt Benchmark

Date: August 18, 2026

This page compares the new libvirt devbox with the previous in-cluster
KubeVirt devbox. The migration happened after the node 102 NVMe failure. Both
runs used the balanced profile at repo commit `f80d9760d852`, the same commit
as the July strict-local run.

## Machines and runs

| Run | Relevant spec | Result directory |
| --- | --- | --- |
| Devbox strict-local (July 5) | KubeVirt VM, 8 vCPU, 32 GiB, Ubuntu ext4 on a strict-local Longhorn root disk, lab node with 2.5GbE | `.cache/bench/results/20260705T125145Z-devbox-balanced` (old VM, raw data not migrated) |
| Devbox libvirt (this run) | libvirt VM on the external host, 8 vCPU on a shared Ryzen 5 5500 (6c/12t), 20 GiB, Ubuntu ext4 on a raw vdisk (`cache=none`, `io=native`) on a Crucial T500 1 TB NVMe (btrfs) | `.cache/bench/results/20260818T032816Z-devbox-balanced` |

The old run had 32 GiB of guest memory; the new VM has 20 GiB. The July raw
result files lived in `.cache` on the old VM and were excluded from the home
directory copy, so the July numbers below come from the recorded benchmark
document.

## Main result

The move trades interactive command latency for bulk IO throughput.

- Bulk and random IO: the libvirt VM is about 2x to 4x faster.
- fsync-heavy small writes: the libvirt VM is about 2.5x slower.
- Agent-shaped command loops: the libvirt VM is about 1.5x slower by
  geometric mean across the 13 shared command benchmarks.

Compared with the M3 Pro Mac from the July report, the devbox remains the
faster machine for agent-shaped command loops, now by roughly 1.9x instead of
2.8x.

## Command benchmarks

Lower is better.

| Benchmark | Strict-local (July) | Libvirt (now) | Change |
| --- | ---: | ---: | --- |
| Fixture Git init, add, commit | 516 ms | 823 ms | 1.6x slower |
| Repo local clone and status | 48.2 ms | 125.2 ms | 2.6x slower |
| Small-file create, stat, read, delete | 191 ms | 344.7 ms | 1.8x slower |
| Fixture copy and edit | 401 ms | 635.2 ms | 1.6x slower |
| Concurrent agentic mix | 70.6 ms | 135.3 ms | 1.9x slower |
| Go test probe | 47.2 ms | 66.1 ms | 1.4x slower |
| Repo yq all tracked YAML | 45.5 ms | 63.0 ms | 1.4x slower |
| `just validate` | 72.9 ms | 97.3 ms | 1.3x slower |
| Repo Kustomize plus yq validate | 72.4 ms | 94.8 ms | 1.3x slower |
| Fixture search | 16.6 ms | 20.9 ms | 1.3x slower |
| Repo Git status | 2.8 ms | 3.5 ms | 1.3x slower |
| Repo manifest search | 4.8 ms | 5.9 ms | 1.2x slower |
| Fixture scan and hash | 189 ms | 223.7 ms | 1.2x slower |

## IO benchmarks

Higher is better.

| Benchmark | Strict-local (July) | Libvirt (now) | Change |
| --- | ---: | ---: | --- |
| Sequential write | 262.6 MiB/s | 1015.9 MiB/s | 3.9x faster |
| Sequential read | 594.0 MiB/s | 1101.1 MiB/s | 1.9x faster |
| Random mixed read | 10.8 MiB/s | 32.7 MiB/s | 3.0x faster |
| Random mixed write | 4.6 MiB/s | 14.0 MiB/s | 3.0x faster |
| fsync-heavy small writes | 2.5 MiB/s | ~1.0 MiB/s | 2.5x slower |

## Reading the result

The two regressions have concrete causes:

- fsync latency. The vdisk uses `cache=none`, so every guest flush becomes a
  real device flush on the Crucial T500. Consumer NVMe without power-loss
  protection completes flushes slowly (about 254 fsync IOPS here). The old
  Longhorn engine acknowledged fsyncs faster than the raw consumer device
  does. Git commits fsync, so the git-heavy loops inherit this cost.
- CPU and scheduling. The command loops are dominated by process startup and
  single-thread speed. The new VM runs 8 vCPUs on a shared 6-core host that
  also serves Docker and array workloads, and the host may run a power-saving
  CPU governor. The old VM had a dedicated lab node.

The bulk IO wins are the raw NVMe path with no Longhorn engine, no iSCSI hop,
and no network in the path.

## Tuning candidates

In expected order of impact, benchmark again after each:

1. Set the host CPU governor to performance. Short commands suffer most from
   frequency ramp latency.
2. Switch the vdisk to `cache=writeback`. Guest flushes then hit the host page
   cache first. This narrows the fsync gap at the cost of a small data-loss
   window on host power loss. The daily restic backups bound that risk.
3. Reduce the VM to 6 vCPUs to match physical cores, and measure the
   concurrent mix. Oversubscribed SMT sharing can cost more than the two
   extra vCPUs return.
4. A future NVMe with power-loss protection (see the drive research brief)
   would fix the fsync gap properly; enterprise drives complete flushes
   nearly for free.

## Notes

- All 25 benchmarks passed (`OK: 25, skipped: 0, failed: 0`).
- The new VM ran the benchmark with the backup timer idle and no other guest
  load.
- The 20 GiB guest (vs 32 GiB) shrinks the page cache, which can affect the
  cached-read side of the command loops; the IO wins stand despite it.
- Re-run the balanced profile after host governor or vdisk cache changes, and
  after the node 102 drive replacement if the standby VM is ever measured
  again.
