# Agentic Coding Benchmarks

This benchmark suite compares machines for local work that affects Codex, Claude Code, and similar terminal agents. It does not send prompts to agent CLIs. The goal is to measure the machine, disk, filesystem, and local toolchain, not model or network speed.

## What it measures

- Host metadata: OS, CPU, memory, filesystem, Git commit, and tool versions.
- Disk and filesystem behavior: sequential IO, random mixed IO, fsync-heavy small writes, and small-file churn.
- Repository loops: `git status`, local clone, patch apply and reset, manifest search, YAML parsing with `yq`, and Kustomize validation.
- Generated fixture loops: fixed synthetic code tree search, scan, copy, edit, and Git indexing.
- Concurrent tool use: a small mix of Git, search, scan, and YAML work running at once.
- Optional local probes: tiny Python, Node, Go, Rust, and uv startup or test loops when those tools are installed.

Results are written under `.cache/bench/results/` and are not tracked by Git.

## Install tools

On the devbox, converge Ansible after pulling the benchmark changes:

```bash
just devbox-converge
```

On macOS, install the matching command line tools with Homebrew:

```bash
brew install just hyperfine fio jq yq ripgrep fd kustomize git python
```

Optional probes use these tools if present:

```bash
brew install node go rust uv
```

Check tool availability:

```bash
just bench-doctor
```

Missing tools do not stop the runner. Benchmarks that need a missing tool are skipped, and basic Python IO tests run when `fio` is missing.

## Run benchmarks

Use the balanced profile for normal comparisons:

```bash
just bench
```

For a faster smoke test:

```bash
just bench-quick
```

For a longer run:

```bash
just bench-thorough
```

For a cold-ish run with no warmup and fresh work directories:

```bash
just bench-cold
```

Each run creates a directory like this:

```text
.cache/bench/results/20260705T120000Z-devbox-balanced/
```

Important files:

- `metadata.json`: host facts and tool versions.
- `summary.json`: parsed metrics used by comparisons.
- `summary.md`: readable summary.
- `raw.jsonl`: one event per benchmark.
- `raw/`: raw `hyperfine` and `fio` output.

## Compare Mac and devbox results

Run the same profile on both machines. Copy one result directory to the other machine, then compare:

```bash
just bench-compare .cache/bench/results/devbox-run .cache/bench/results/mac-run
```

The comparison tool writes Markdown and JSON under `.cache/bench/comparisons/`.

Lower is better for command timings. Higher is better for IO throughput and IOPS. Treat small differences as noise, especially on laptops, busy VMs, and machines doing background updates.

## Notes for fair runs

- Run on AC power on the Mac.
- Close heavy background jobs before a measured run.
- Keep the repo on the normal disk for each machine, not on a network share.
- Run each profile at least twice if the first result looks odd.
- Compare the same Git commit on both machines.
- Do not compare a warm balanced run with a cold run.

Clean generated files with:

```bash
just bench-clean
```
