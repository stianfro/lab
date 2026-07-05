# Devbox vs M3 Pro Mac Agentic Coding Benchmark

Date: July 5, 2026

This run compared the lab KubeVirt devbox with a MacBook-class Apple M3 Pro workstation for local work that matters to terminal coding agents. The suite does not run Codex or Claude prompts. It measures local disk, filesystem, Git, search, validation, small edits, and concurrent command behavior.

## Machines

| Machine | Relevant spec | Result directory |
| --- | --- | --- |
| Lab devbox | KubeVirt VM, 4 vCPU, 16 GiB memory request, Ubuntu on ext4, 140 GiB Longhorn root disk | `.cache/bench/results/20260705T095308Z-devbox-balanced` |
| Mac | Apple M3 Pro, 36 GB RAM, macOS 26.5.2, APFS on internal SSD | `.cache/bench/results/20260705T095309Z-aa-imc-g6gvmhkyht-balanced` |

Both runs used the same repo commit, `ef4fa9c1de9d`. The Git working tree was clean in both runs.

## Summary

Across the 20 shared timed command benchmarks, the devbox was faster in 17 and the Mac was faster in 3. The geometric mean of command timing ratios was about 2.8x in favor of the devbox.

This result looks surprising because the Mac has much faster raw storage. The IO tests confirm that: the Mac wins bulk sequential and random IO by 16x to 29x. The devbox wins the agentic coding shape because the workload is dominated by small files, metadata, Git, process startup, search, and copy/edit loops. Linux on ext4 handles this pattern much better than macOS/APFS in this run.

## Command benchmarks

Lower is better.

| Benchmark | Devbox | Mac | Winner |
| --- | ---: | ---: | --- |
| Fixture Git init, add, commit | 525 ms | 13.2 s | Devbox, 25.2x |
| Repo local clone and status | 47 ms | 762 ms | Devbox, 16.1x |
| Small-file create, stat, read, delete | 190 ms | 1.76 s | Devbox, 9.3x |
| Repo Git status | 2.1 ms | 13.7 ms | Devbox, 6.6x |
| Fixture search | 24.6 ms | 137.7 ms | Devbox, 5.6x |
| Fixture copy and edit | 494 ms | 2.39 s | Devbox, 4.8x |
| Go test probe | 44.4 ms | 147.7 ms | Devbox, 3.3x |
| Fixture scan and hash | 189 ms | 494 ms | Devbox, 2.6x |
| Concurrent agentic mix | 90.1 ms | 211 ms | Devbox, 2.4x |
| Repo manifest search | 4.7 ms | 9.8 ms | Devbox, 2.1x |
| Repo Kustomize plus yq validate | 69.9 ms | 56.5 ms | Mac, 1.2x |
| Repo yq all tracked YAML | 47.8 ms | 37.7 ms | Mac, 1.3x |
| `just validate` | 74.4 ms | 65.9 ms | Mac, 1.1x |

The Mac wins a few tight YAML and Kustomize validation commands, which fits the M3 Pro CPU expectation. Those wins are small compared with the devbox wins in Git and small-file operations.

## IO benchmarks

Higher is better.

| Benchmark | Devbox | Mac | Winner |
| --- | ---: | ---: | --- |
| Sequential write | 117 MiB/s | 3.3 GiB/s | Mac, 29.2x |
| Sequential read | 254 MiB/s | 5.4 GiB/s | Mac, 21.9x |
| Random mixed read | 6.8 MiB/s | 110 MiB/s | Mac, 16.2x |
| Random mixed write | 2.9 MiB/s | 47.5 MiB/s | Mac, 16.4x |
| fsync-heavy small writes | 1.5 MiB/s | 1.1 MiB/s | Devbox, 1.4x |

These numbers show the Longhorn-backed VM disk is much slower than the Mac SSD for raw throughput. The devbox result is still better for agent work because most agent loops do not stream multi-GiB files. They touch many small files and run many short commands.

## Reading the result

The right conclusion is not that the VM has faster storage. It does not. The result says that for this repo and synthetic agent-shaped workloads, the devbox is faster at the file and process patterns that coding agents use most often.

Likely contributors:

- Linux plus ext4 has low metadata overhead for many small files.
- macOS/APFS has higher small-file and metadata costs in this workload.
- macOS may also pay extra for file monitoring, Spotlight, endpoint security, and developer tooling hooks.
- The devbox is a headless server with fewer desktop background tasks.

The practical result is that the current devbox is already the better primary environment for Codex and Claude Code work in this lab, even before increasing its VM size.

## Notes

- The devbox Rust probe failed because the generated offline Cargo test did not complete successfully in this run.
- The Mac Rust probe was skipped because `cargo` was not installed.
- The Rust probe is excluded from the shared timing summary above.
- Re-run the balanced profile after major macOS, Talos, KubeVirt, Longhorn, or VM sizing changes.
