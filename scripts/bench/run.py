#!/usr/bin/env python3
"""Run local benchmarks for agentic coding workflows."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import random
import shutil
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from common import (
    append_jsonl,
    command_exists,
    first_existing,
    format_bytes_per_second,
    format_seconds,
    host_metadata,
    read_json,
    repo_root,
    run_capture,
    slug,
    stats,
    utc_stamp,
    write_json,
)

PROFILES: dict[str, dict[str, Any]] = {
    "quick": {
        "runs": 3,
        "warmup": 1,
        "fixture_files": 600,
        "fixture_dirs": 24,
        "small_files": 500,
        "edit_limit": 120,
        "fio_size": "128m",
        "fio_runtime": 3,
        "python_io_bytes": 128 * 1024 * 1024,
        "python_random_ops": 5000,
        "optional": False,
    },
    "balanced": {
        "runs": 8,
        "warmup": 2,
        "fixture_files": 3500,
        "fixture_dirs": 80,
        "small_files": 3000,
        "edit_limit": 500,
        "fio_size": "512m",
        "fio_runtime": 10,
        "python_io_bytes": 512 * 1024 * 1024,
        "python_random_ops": 40000,
        "optional": True,
    },
    "thorough": {
        "runs": 15,
        "warmup": 3,
        "fixture_files": 9000,
        "fixture_dirs": 160,
        "small_files": 9000,
        "edit_limit": 1200,
        "fio_size": "1g",
        "fio_runtime": 20,
        "python_io_bytes": 1024 * 1024 * 1024,
        "python_random_ops": 120000,
        "optional": True,
    },
    "cold": {
        "runs": 5,
        "warmup": 0,
        "fixture_files": 3500,
        "fixture_dirs": 80,
        "small_files": 3000,
        "edit_limit": 500,
        "fio_size": "512m",
        "fio_runtime": 10,
        "python_io_bytes": 512 * 1024 * 1024,
        "python_random_ops": 40000,
        "optional": True,
    },
}

FULL_TOOLS = ["git", "python3", "just", "jq", "yq", "hyperfine", "fio", "rg", "fd", "kustomize"]
OPTIONAL_TOOLS = ["go", "node", "cargo", "uv", "codex", "claude"]


class BenchRunner:
    def __init__(self, profile: str, root: Path, result_dir: Path, label: str | None) -> None:
        self.profile_name = profile
        self.profile = PROFILES[profile]
        self.root = root
        self.label = label or profile
        self.run_id = result_dir.name
        self.result_dir = result_dir
        self.work_dir = root / ".cache" / "bench" / "work" / self.run_id
        self.raw_dir = result_dir / "raw"
        self.events_path = result_dir / "raw.jsonl"
        self.benchmarks: list[dict[str, Any]] = []
        self.python = sys.executable
        self.fixture = self.work_dir / "fixture"

    def setup(self) -> None:
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        write_json(self.result_dir / "metadata.json", host_metadata(self.root, self.result_dir))
        self.generate_fixture()
        self.prepare_optional_projects()

    def record(self, event: dict[str, Any]) -> None:
        event.setdefault("profile", self.profile_name)
        self.benchmarks.append(event)
        append_jsonl(self.events_path, event)
        status = event.get("status")
        name = event.get("name")
        metric = event.get("metrics", {}).get("median_seconds")
        if metric is not None:
            print(f"{name}: {status}, median {format_seconds(metric)}")
        else:
            print(f"{name}: {status}")

    def skip(self, name: str, reason: str, bench_type: str = "command") -> None:
        self.record(
            {
                "name": name,
                "type": bench_type,
                "status": "skipped",
                "reason": reason,
                "lower_is_better": True,
                "unit": "seconds",
                "metrics": {},
            }
        )

    def generate_fixture(self) -> None:
        if self.fixture.exists():
            shutil.rmtree(self.fixture)
        self.fixture.mkdir(parents=True)
        random.seed(20260705)
        suffixes = [".py", ".yaml", ".md", ".ts", ".go", ".rs", ".json", ".sh"]
        total = int(self.profile["fixture_files"])
        dirs = int(self.profile["fixture_dirs"])
        for directory_index in range(dirs):
            (self.fixture / f"pkg-{directory_index:03d}" / "nested").mkdir(parents=True, exist_ok=True)
        for index in range(total):
            suffix = suffixes[index % len(suffixes)]
            directory = self.fixture / f"pkg-{index % dirs:03d}"
            if index % 5 == 0:
                directory = directory / "nested"
            name = directory / f"file-{index:05d}{suffix}"
            name.write_text(self.fixture_content(index, suffix), encoding="utf-8")
        (self.fixture / "README.md").write_text(
            "# Benchmark Fixture\n\nThis generated tree is safe to delete.\n", encoding="utf-8"
        )

    def fixture_content(self, index: int, suffix: str) -> str:
        token = f"bench_token_{index:05d}"
        if suffix == ".py":
            return (
                f"def handler_{index}(value):\n"
                f"    # TODO: inspect {token}\n"
                f"    return f'{token}:{{value}}'\n"
            )
        if suffix == ".yaml":
            return (
                "apiVersion: v1\n"
                "kind: ConfigMap\n"
                f"metadata:\n  name: bench-{index}\n"
                f"data:\n  token: {token}\n"
            )
        if suffix == ".md":
            return f"# Note {index}\n\nTODO {token} handler path and search text.\n"
        if suffix == ".ts":
            return f"export const value{index} = '{token}';\nexport function handler() {{ return value{index}; }}\n"
        if suffix == ".go":
            return f"package bench\n\nfunc Value{index}() string {{ return \"{token}\" }}\n"
        if suffix == ".rs":
            return f"pub fn value_{index}() -> &'static str {{ \"{token}\" }}\n"
        if suffix == ".json":
            return json.dumps({"index": index, "token": token, "todo": True}) + "\n"
        if suffix == ".sh":
            return f"#!/usr/bin/env sh\necho {shlex.quote(token)}\n"
        return token + "\n"

    def prepare_optional_projects(self) -> None:
        probes = self.work_dir / "probes"
        probes.mkdir(parents=True, exist_ok=True)

        py_proj = probes / "python"
        py_proj.mkdir(exist_ok=True)
        (py_proj / "probe.py").write_text(
            "def fib(n):\n"
            "    a, b = 0, 1\n"
            "    for _ in range(n):\n"
            "        a, b = b, a + b\n"
            "    return a\n\n"
            "assert fib(20) == 6765\n",
            encoding="utf-8",
        )

        node_proj = probes / "node"
        node_proj.mkdir(exist_ok=True)
        (node_proj / "probe.js").write_text(
            "let total = 0;\n"
            "for (let i = 0; i < 200000; i++) total += i % 17;\n"
            "if (total <= 0) process.exit(1);\n"
            "console.log(total);\n",
            encoding="utf-8",
        )

        go_proj = probes / "go"
        go_proj.mkdir(exist_ok=True)
        (go_proj / "go.mod").write_text("module benchprobe\n\ngo 1.22\n", encoding="utf-8")
        (go_proj / "probe_test.go").write_text(
            "package benchprobe\n\nimport \"testing\"\n\n"
            "func TestSum(t *testing.T) {\n"
            "\ttotal := 0\n"
            "\tfor i := 0; i < 10000; i++ { total += i % 19 }\n"
            "\tif total == 0 { t.Fatal(total) }\n"
            "}\n",
            encoding="utf-8",
        )

        rust_proj = probes / "rust"
        (rust_proj / "src").mkdir(parents=True, exist_ok=True)
        (rust_proj / "Cargo.toml").write_text(
            "[package]\nname = \"benchprobe\"\nversion = \"0.1.0\"\nedition = \"2021\"\n",
            encoding="utf-8",
        )
        (rust_proj / "src" / "lib.rs").write_text(
            "pub fn sum() -> usize { (0..10000).map(|i| i % 23).sum() }\n\n"
            "#[cfg(test)]\nmod tests {\n"
            "    #[test]\n    fn it_sums() { assert!(crate::sum() > 0); }\n}\n",
            encoding="utf-8",
        )

    def make_patch_file(self) -> tuple[Path, Path]:
        clone_dir = self.work_dir / "edit-clone"
        if clone_dir.exists():
            shutil.rmtree(clone_dir)
        subprocess.run(
            ["git", "clone", "--local", "--no-hardlinks", str(self.root), str(clone_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        readme = clone_dir / "README.md"
        original = readme.read_text(encoding="utf-8").splitlines(keepends=True)
        changed = list(original)
        changed[0] = changed[0].rstrip("\n") + " Scratch\n"
        patch = "".join(
            difflib.unified_diff(
                original,
                changed,
                fromfile="a/README.md",
                tofile="b/README.md",
            )
        )
        patch_path = self.work_dir / "readme.patch"
        patch_path.write_text(patch, encoding="utf-8")
        return clone_dir, patch_path

    def requirements_missing(self, requirements: list[str]) -> list[str]:
        missing: list[str] = []
        for requirement in requirements:
            if requirement == "fd":
                if first_existing(["fd", "fdfind"]) is None:
                    missing.append("fd or fdfind")
            elif not command_exists(requirement):
                missing.append(requirement)
        return missing

    def bench_command(
        self,
        name: str,
        command: str,
        cwd: Path,
        requirements: list[str] | None = None,
        runs: int | None = None,
        warmup: int | None = None,
    ) -> None:
        requirements = requirements or []
        missing = self.requirements_missing(requirements)
        if missing:
            self.skip(name, "missing " + ", ".join(missing))
            return
        runs = runs if runs is not None else int(self.profile["runs"])
        warmup = warmup if warmup is not None else int(self.profile["warmup"])
        if command_exists("hyperfine"):
            self.bench_hyperfine(name, command, cwd, runs, warmup)
        else:
            self.bench_internal_timer(name, command, cwd, runs, warmup)

    def bench_hyperfine(self, name: str, command: str, cwd: Path, runs: int, warmup: int) -> None:
        raw_path = self.raw_dir / f"hyperfine-{slug(name)}.json"
        hyperfine_command = [
            "hyperfine",
            "--runs",
            str(runs),
            "--export-json",
            str(raw_path),
            "--command-name",
            name,
        ]
        if warmup > 0:
            hyperfine_command += ["--warmup", str(warmup)]
        hyperfine_command.append(command)
        result = run_capture(hyperfine_command, cwd=cwd, timeout=60 * 60)
        if result["returncode"] != 0:
            self.record(
                {
                    "name": name,
                    "type": "command",
                    "status": "failed",
                    "command": command,
                    "cwd": str(cwd),
                    "runner": "hyperfine",
                    "raw_path": str(raw_path),
                    "lower_is_better": True,
                    "unit": "seconds",
                    "metrics": {},
                    "error": result,
                }
            )
            return
        data = read_json(raw_path)
        item = data["results"][0]
        run_stats = stats([float(value) for value in item.get("times", [])])
        metrics = {
            "median_seconds": float(item.get("median", run_stats["median"] or 0.0)),
            "mean_seconds": float(item.get("mean", run_stats["mean"] or 0.0)),
            "stdev_seconds": float(item.get("stddev", run_stats["stdev"] or 0.0)),
            "min_seconds": float(item.get("min", run_stats["min"] or 0.0)),
            "max_seconds": float(item.get("max", run_stats["max"] or 0.0)),
            "p95_seconds": run_stats["p95"],
            "runs": runs,
            "warmup": warmup,
        }
        self.record(
            {
                "name": name,
                "type": "command",
                "status": "ok",
                "command": command,
                "cwd": str(cwd),
                "runner": "hyperfine",
                "raw_path": str(raw_path),
                "lower_is_better": True,
                "unit": "seconds",
                "metrics": metrics,
            }
        )

    def bench_internal_timer(self, name: str, command: str, cwd: Path, runs: int, warmup: int) -> None:
        values: list[float] = []
        failures: list[dict[str, Any]] = []
        for index in range(warmup + runs):
            started = time.perf_counter()
            result = subprocess.run(
                command,
                cwd=cwd,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            elapsed = time.perf_counter() - started
            if index >= warmup:
                values.append(elapsed)
                if result.returncode != 0:
                    failures.append(
                        {
                            "returncode": result.returncode,
                            "stdout": result.stdout[-2000:],
                            "stderr": result.stderr[-2000:],
                        }
                    )
        run_stats = stats(values)
        self.record(
            {
                "name": name,
                "type": "command",
                "status": "failed" if failures else "ok",
                "command": command,
                "cwd": str(cwd),
                "runner": "python-timer",
                "lower_is_better": True,
                "unit": "seconds",
                "metrics": {
                    "median_seconds": run_stats["median"],
                    "mean_seconds": run_stats["mean"],
                    "stdev_seconds": run_stats["stdev"],
                    "min_seconds": run_stats["min"],
                    "max_seconds": run_stats["max"],
                    "p95_seconds": run_stats["p95"],
                    "runs": runs,
                    "warmup": warmup,
                },
                "failures": failures,
            }
        )

    def run_fio(self, name: str, fio_args: list[str]) -> None:
        if not command_exists("fio"):
            self.skip(name, "missing fio", bench_type="fio")
            return
        fio_dir = self.work_dir / "fio"
        fio_dir.mkdir(exist_ok=True)
        raw_path = self.raw_dir / f"fio-{slug(name)}.json"
        command = ["fio", "--output-format=json", f"--output={raw_path}"] + fio_args
        result = run_capture(command, cwd=fio_dir, timeout=60 * 60)
        if result["returncode"] != 0:
            self.record(
                {
                    "name": name,
                    "type": "fio",
                    "status": "failed",
                    "command": command,
                    "raw_path": str(raw_path),
                    "lower_is_better": False,
                    "unit": "bytes_per_second",
                    "metrics": {},
                    "error": result,
                }
            )
            return
        data = read_json(raw_path)
        jobs = data.get("jobs", [])
        read_bw = sum(float(job.get("read", {}).get("bw_bytes", 0.0)) for job in jobs)
        write_bw = sum(float(job.get("write", {}).get("bw_bytes", 0.0)) for job in jobs)
        read_iops = sum(float(job.get("read", {}).get("iops", 0.0)) for job in jobs)
        write_iops = sum(float(job.get("write", {}).get("iops", 0.0)) for job in jobs)
        elapsed_ms = max([float(job.get("elapsed", 0.0)) for job in jobs] or [0.0]) * 1000.0
        self.record(
            {
                "name": name,
                "type": "fio",
                "status": "ok",
                "command": command,
                "raw_path": str(raw_path),
                "lower_is_better": False,
                "unit": "bytes_per_second",
                "metrics": {
                    "read_bytes_per_second": read_bw,
                    "write_bytes_per_second": write_bw,
                    "read_iops": read_iops,
                    "write_iops": write_iops,
                    "elapsed_ms": elapsed_ms,
                },
            }
        )

    def run_python_io(self) -> None:
        io_dir = self.work_dir / "python-io"
        io_dir.mkdir(exist_ok=True)
        total_bytes = int(self.profile["python_io_bytes"])
        block = b"x" * (1024 * 1024)
        seq_file = io_dir / "seq.dat"

        started = time.perf_counter()
        with seq_file.open("wb") as file:
            remaining = total_bytes
            while remaining > 0:
                chunk = block if remaining >= len(block) else block[:remaining]
                file.write(chunk)
                remaining -= len(chunk)
            file.flush()
            os.fsync(file.fileno())
        write_seconds = time.perf_counter() - started
        self.record(
            {
                "name": "python_io_sequential_write",
                "type": "python_io",
                "status": "ok",
                "lower_is_better": False,
                "unit": "bytes_per_second",
                "metrics": {
                    "seconds": write_seconds,
                    "write_bytes_per_second": total_bytes / write_seconds if write_seconds else None,
                },
            }
        )

        started = time.perf_counter()
        bytes_read = 0
        with seq_file.open("rb") as file:
            while True:
                data = file.read(len(block))
                if not data:
                    break
                bytes_read += len(data)
        read_seconds = time.perf_counter() - started
        self.record(
            {
                "name": "python_io_sequential_read",
                "type": "python_io",
                "status": "ok",
                "lower_is_better": False,
                "unit": "bytes_per_second",
                "metrics": {
                    "seconds": read_seconds,
                    "read_bytes_per_second": bytes_read / read_seconds if read_seconds else None,
                },
            }
        )

        random_file = io_dir / "random.dat"
        random_file.write_bytes(b"0" * min(total_bytes, 128 * 1024 * 1024))
        file_size = random_file.stat().st_size
        ops = int(self.profile["python_random_ops"])
        rnd = random.Random(20260705)
        started = time.perf_counter()
        with random_file.open("r+b", buffering=0) as file:
            for index in range(ops):
                offset = rnd.randrange(0, max(1, file_size - 4096))
                file.seek(offset)
                if index % 3 == 0:
                    file.write(b"r" * 4096)
                else:
                    file.read(4096)
            os.fsync(file.fileno())
        random_seconds = time.perf_counter() - started
        self.record(
            {
                "name": "python_io_random_small_rw",
                "type": "python_io",
                "status": "ok",
                "lower_is_better": False,
                "unit": "iops",
                "metrics": {
                    "seconds": random_seconds,
                    "ops": ops,
                    "iops": ops / random_seconds if random_seconds else None,
                },
            }
        )

    def run_small_file_churn(self) -> None:
        base = self.work_dir / "small-files"
        if base.exists():
            shutil.rmtree(base)
        base.mkdir(parents=True)
        count = int(self.profile["small_files"])
        payload = b"small file payload for agentic coding benchmark\n"
        started = time.perf_counter()
        for index in range(count):
            directory = base / f"d-{index % 64:02d}"
            directory.mkdir(exist_ok=True)
            (directory / f"file-{index:05d}.txt").write_bytes(payload)
        create_seconds = time.perf_counter() - started

        started = time.perf_counter()
        size = 0
        for path in base.rglob("*.txt"):
            size += path.stat().st_size
            size += len(path.read_bytes())
        read_seconds = time.perf_counter() - started

        started = time.perf_counter()
        shutil.rmtree(base)
        delete_seconds = time.perf_counter() - started
        self.record(
            {
                "name": "small_file_create_stat_read_delete",
                "type": "small_files",
                "status": "ok",
                "lower_is_better": True,
                "unit": "seconds",
                "metrics": {
                    "files": count,
                    "bytes_touched": size,
                    "create_seconds": create_seconds,
                    "stat_read_seconds": read_seconds,
                    "delete_seconds": delete_seconds,
                    "median_seconds": create_seconds + read_seconds + delete_seconds,
                },
            }
        )

    def run_io(self) -> None:
        fio_dir = self.work_dir / "fio"
        fio_dir.mkdir(exist_ok=True)
        size = str(self.profile["fio_size"])
        runtime = str(self.profile["fio_runtime"])
        seq_file = fio_dir / "seq.dat"
        rand_file = fio_dir / "rand.dat"
        fsync_file = fio_dir / "fsync.dat"
        self.run_fio(
            "fio_sequential_write",
            [
                "--name=seq-write",
                f"--filename={seq_file}",
                "--rw=write",
                "--bs=1m",
                f"--size={size}",
                "--numjobs=1",
                "--iodepth=1",
                "--ioengine=sync",
                "--direct=0",
                "--end_fsync=1",
            ],
        )
        self.run_fio(
            "fio_sequential_read",
            [
                "--name=seq-read",
                f"--filename={seq_file}",
                "--rw=read",
                "--bs=1m",
                f"--size={size}",
                "--numjobs=1",
                "--iodepth=1",
                "--ioengine=sync",
                "--direct=0",
            ],
        )
        self.run_fio(
            "fio_random_mixed_rw",
            [
                "--name=random-rw",
                f"--filename={rand_file}",
                "--rw=randrw",
                "--rwmixread=70",
                "--bs=4k",
                f"--size={size}",
                f"--runtime={runtime}",
                "--time_based=1",
                "--numjobs=1",
                "--iodepth=1",
                "--ioengine=sync",
                "--direct=0",
                "--group_reporting=1",
            ],
        )
        self.run_fio(
            "fio_fsync_small_writes",
            [
                "--name=fsync-writes",
                f"--filename={fsync_file}",
                "--rw=write",
                "--bs=4k",
                "--size=64m",
                f"--runtime={runtime}",
                "--time_based=1",
                "--numjobs=1",
                "--iodepth=1",
                "--ioengine=sync",
                "--direct=0",
                "--fsync=1",
                "--group_reporting=1",
            ],
        )
        if not command_exists("fio"):
            self.run_python_io()
        self.run_small_file_churn()

    def run_command_benchmarks(self) -> None:
        q_root = shlex.quote(str(self.root))
        q_fixture = shlex.quote(str(self.fixture))
        q_work = shlex.quote(str(self.work_dir))
        q_python = shlex.quote(self.python)
        fd_command = first_existing(["fd", "fdfind"]) or "fd"
        script_scan = shlex.quote(str(self.root / "scripts/bench/workload_scan.py"))
        script_edit = shlex.quote(str(self.root / "scripts/bench/workload_edit.py"))
        script_mix = shlex.quote(str(self.root / "scripts/bench/workload_mix.py"))

        self.bench_command("repo_git_status", "git status --short >/dev/null", self.root, ["git"])
        self.bench_command(
            "repo_search_manifests",
            "rg -n 'apiVersion|kind|metadata' apps clusters talos >/dev/null",
            self.root,
            ["rg"],
        )
        self.bench_command(
            "repo_find_yaml",
            f"{shlex.quote(fd_command)} '\\.ya?ml$' apps clusters talos >/dev/null",
            self.root,
            ["fd"],
        )
        self.bench_command(
            "repo_scan_tracked_files",
            f"{q_python} {script_scan} --git-files {q_root} >/dev/null",
            self.root,
            ["python3", "git"],
        )
        self.bench_command(
            "repo_yq_all_tracked_yaml",
            "git ls-files '*.yaml' '*.yml' | xargs yq e 'true' >/dev/null",
            self.root,
            ["git", "yq"],
        )
        self.bench_command(
            "repo_kustomize_yq_validate",
            "kustomize build clusters/talos | yq e 'true' - >/dev/null",
            self.root,
            ["kustomize", "yq"],
        )
        self.bench_command("repo_just_validate", "just validate >/dev/null", self.root, ["just", "kustomize", "yq"])
        self.bench_command(
            "repo_local_clone_status",
            f"rm -rf local-clone && git clone --local --no-hardlinks {q_root} local-clone >/dev/null && git -C local-clone status --short >/dev/null",
            self.work_dir,
            ["git"],
            runs=max(2, min(5, int(self.profile["runs"]))),
            warmup=0 if self.profile_name == "cold" else 1,
        )

        clone_dir, patch_path = self.make_patch_file()
        self.bench_command(
            "repo_patch_apply_diff_reset",
            (
                f"git -C {shlex.quote(str(clone_dir))} reset --hard HEAD >/dev/null && "
                f"git -C {shlex.quote(str(clone_dir))} clean -fd >/dev/null && "
                f"git -C {shlex.quote(str(clone_dir))} apply {shlex.quote(str(patch_path))} && "
                f"git -C {shlex.quote(str(clone_dir))} diff --stat >/dev/null && "
                f"git -C {shlex.quote(str(clone_dir))} reset --hard HEAD >/dev/null"
            ),
            self.work_dir,
            ["git"],
        )

        self.bench_command(
            "fixture_search",
            f"rg -n 'TODO|handler|token' {q_fixture} >/dev/null",
            self.root,
            ["rg"],
        )
        self.bench_command(
            "fixture_find_source_files",
            f"{shlex.quote(fd_command)} '\\.(py|yaml|md|ts)$' {q_fixture} >/dev/null",
            self.root,
            ["fd"],
        )
        self.bench_command(
            "fixture_scan_hash",
            f"{q_python} {script_scan} {q_fixture} >/dev/null",
            self.root,
            ["python3"],
        )
        self.bench_command(
            "fixture_copy_and_edit",
            f"{q_python} {script_edit} {q_fixture} {q_work}/fixture-edit --limit {int(self.profile['edit_limit'])} >/dev/null",
            self.root,
            ["python3"],
            runs=max(2, min(6, int(self.profile["runs"]))),
        )
        self.bench_command(
            "fixture_git_init_add_commit",
            (
                f"rm -rf fixture-git && cp -R {q_fixture} fixture-git && "
                "git -C fixture-git init -q && git -C fixture-git add . && "
                "git -C fixture-git -c user.email=bench@example.invalid -c user.name=Bench commit -qm init"
            ),
            self.work_dir,
            ["git"],
            runs=max(2, min(5, int(self.profile["runs"]))),
        )
        self.bench_command(
            "concurrent_agentic_mix",
            f"{q_python} {script_mix} --repo {q_root} --fixture {q_fixture} >/dev/null",
            self.root,
            ["python3", "git"],
            runs=max(2, min(6, int(self.profile["runs"]))),
        )

    def run_optional_probes(self) -> None:
        if not bool(self.profile["optional"]):
            self.skip("optional_language_probes", "profile disables optional probes")
            return
        probes = self.work_dir / "probes"
        q_python = shlex.quote(self.python)
        self.bench_command(
            "probe_python_compileall",
            f"find {shlex.quote(str(probes / 'python'))} -name '__pycache__' -type d -prune -exec rm -rf {{}} + 2>/dev/null; {q_python} -m compileall -q {shlex.quote(str(probes / 'python'))}",
            self.root,
            ["python3"],
        )
        self.bench_command(
            "probe_node_startup",
            f"node {shlex.quote(str(probes / 'node' / 'probe.js'))} >/dev/null",
            self.root,
            ["node"],
        )
        self.bench_command(
            "probe_go_test",
            f"GOCACHE={shlex.quote(str(self.work_dir / '.cache' / 'go-build'))} go test ./... >/dev/null",
            probes / "go",
            ["go"],
        )
        self.bench_command(
            "probe_rust_cargo_test",
            f"CARGO_HOME={shlex.quote(str(self.work_dir / '.cache' / 'cargo-home'))} cargo test --offline --quiet >/dev/null",
            probes / "rust",
            ["cargo"],
            runs=max(2, min(5, int(self.profile["runs"]))),
        )
        self.bench_command("probe_uv_startup", "uv --version >/dev/null", self.root, ["uv"])

    def finalize(self) -> None:
        summary = {
            "profile": self.profile_name,
            "label": self.label,
            "result_dir": str(self.result_dir),
            "work_dir": str(self.work_dir),
            "benchmark_count": len(self.benchmarks),
            "ok_count": sum(1 for item in self.benchmarks if item.get("status") == "ok"),
            "skipped_count": sum(1 for item in self.benchmarks if item.get("status") == "skipped"),
            "failed_count": sum(1 for item in self.benchmarks if item.get("status") == "failed"),
            "benchmarks": self.benchmarks,
        }
        write_json(self.result_dir / "summary.json", summary)
        self.write_markdown(summary)
        print(f"\nResults: {self.result_dir}")

    def write_markdown(self, summary: dict[str, Any]) -> None:
        lines = [
            f"# Benchmark Summary: {self.label}",
            "",
            f"Profile: `{self.profile_name}`",
            f"Result directory: `{self.result_dir}`",
            "",
            f"OK: {summary['ok_count']}, skipped: {summary['skipped_count']}, failed: {summary['failed_count']}",
            "",
            "## Timed commands",
            "",
            "| Benchmark | Status | Median | p95 | Runner |",
            "| --- | --- | ---: | ---: | --- |",
        ]
        for item in self.benchmarks:
            metrics = item.get("metrics", {})
            median = metrics.get("median_seconds")
            p95 = metrics.get("p95_seconds")
            if median is not None or item.get("type") == "command":
                lines.append(
                    f"| {item['name']} | {item['status']} | {format_seconds(median)} | {format_seconds(p95)} | {item.get('runner', item.get('type', ''))} |"
                )
        lines += ["", "## IO throughput", "", "| Benchmark | Status | Read | Write | IOPS |", "| --- | --- | ---: | ---: | ---: |"]
        for item in self.benchmarks:
            if item.get("type") not in {"fio", "python_io"}:
                continue
            metrics = item.get("metrics", {})
            read_bw = metrics.get("read_bytes_per_second")
            write_bw = metrics.get("write_bytes_per_second")
            iops = metrics.get("iops") or metrics.get("read_iops") or metrics.get("write_iops")
            lines.append(
                f"| {item['name']} | {item['status']} | {format_bytes_per_second(read_bw)} | {format_bytes_per_second(write_bw)} | {iops if iops is not None else 'n/a'} |"
            )
        lines += ["", "## Skips and failures", ""]
        for item in self.benchmarks:
            if item.get("status") != "ok":
                lines.append(f"- `{item['name']}`: {item.get('reason') or item.get('error', {}).get('stderr', 'failed')}")
        (self.result_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run(self) -> None:
        self.setup()
        self.run_io()
        self.run_command_benchmarks()
        self.run_optional_probes()
        self.finalize()


def run_doctor() -> int:
    root = repo_root()
    print(f"Repo: {root}")
    print("\nFull benchmark tools:")
    for tool in FULL_TOOLS:
        if tool == "fd":
            command = first_existing(["fd", "fdfind"])
            found = shutil.which(command) if command else None
        else:
            found = shutil.which(tool)
        print(f"  {tool}: {found or 'missing'}")
    print("\nOptional tools:")
    for tool in OPTIONAL_TOOLS:
        found = shutil.which(tool)
        print(f"  {tool}: {found or 'missing'}")
    print("\nMissing full tools do not stop the runner. Related benchmarks are skipped or use a Python fallback.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run agentic coding benchmarks")
    parser.add_argument("profile", nargs="?", default="balanced", choices=sorted(PROFILES) + ["doctor"])
    parser.add_argument("--label", help="Short label used in the result directory")
    parser.add_argument("--out", type=Path, help="Write results to this directory")
    parser.add_argument("--repo", type=Path, help="Repository root. Defaults to git root")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.profile == "doctor":
        return run_doctor()
    root = args.repo.resolve() if args.repo else repo_root()
    label = slug(args.label or args.profile)
    hostname = slug(run_capture(["hostname", "-s"], timeout=5).get("stdout") or "host")
    result_dir = args.out.resolve() if args.out else root / ".cache" / "bench" / "results" / f"{utc_stamp()}-{hostname}-{label}"
    runner = BenchRunner(args.profile, root, result_dir, args.label)
    runner.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
