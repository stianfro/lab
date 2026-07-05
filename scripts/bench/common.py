#!/usr/bin/env python3
"""Shared helpers for the agentic coding benchmark suite."""

from __future__ import annotations

import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def slug(value: str) -> str:
    keep = []
    for char in value.lower():
        if char.isalnum():
            keep.append(char)
        elif char in {"-", "_", "."}:
            keep.append(char)
        else:
            keep.append("-")
    out = "".join(keep).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "run"


def repo_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return Path(result.stdout.strip()).resolve()


def command_exists(command: str) -> bool:
    return shutil.which(command) is not None


def first_existing(commands: Iterable[str]) -> str | None:
    for command in commands:
        if command_exists(command):
            return command
    return None


def run_capture(command: list[str], cwd: Path | None = None, timeout: int = 30) -> dict[str, Any]:
    try:
        started = time.perf_counter()
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        elapsed = time.perf_counter() - started
        return {
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "elapsed_seconds": elapsed,
        }
    except FileNotFoundError as exc:
        return {
            "command": command,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_seconds": None,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": command,
            "returncode": 124,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "timeout",
            "elapsed_seconds": timeout,
        }


def tool_versions() -> dict[str, Any]:
    commands: dict[str, list[str]] = {
        "python3": [sys.executable, "--version"],
        "git": ["git", "--version"],
        "just": ["just", "--version"],
        "yq": ["yq", "--version"],
        "jq": ["jq", "--version"],
        "hyperfine": ["hyperfine", "--version"],
        "fio": ["fio", "--version"],
        "rg": ["rg", "--version"],
        "fd": [first_existing(["fd", "fdfind"]) or "fd", "--version"],
        "kustomize": ["kustomize", "version"],
        "node": ["node", "--version"],
        "npm": ["npm", "--version"],
        "go": ["go", "version"],
        "cargo": ["cargo", "--version"],
        "rustc": ["rustc", "--version"],
        "uv": ["uv", "--version"],
        "codex": ["codex", "--version"],
        "claude": ["claude", "--version"],
    }
    versions: dict[str, Any] = {}
    for name, command in commands.items():
        versions[name] = run_capture(command, timeout=10)
    return versions


def host_metadata(root: Path, result_dir: Path) -> dict[str, Any]:
    stat = os.statvfs(result_dir)
    metadata: dict[str, Any] = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": sys.version,
        "repo": {
            "root": str(root),
            "head": run_capture(["git", "rev-parse", "HEAD"], cwd=root),
            "branch": run_capture(["git", "branch", "--show-current"], cwd=root),
            "status_short": run_capture(["git", "status", "--short"], cwd=root),
        },
        "filesystem": {
            "result_dir": str(result_dir),
            "block_size": stat.f_bsize,
            "blocks": stat.f_blocks,
            "blocks_available": stat.f_bavail,
            "bytes_available": stat.f_bavail * stat.f_bsize,
        },
        "tools": tool_versions(),
        "raw_system": {},
    }
    if platform.system() == "Linux":
        metadata["raw_system"]["uname"] = run_capture(["uname", "-a"])
        metadata["raw_system"]["lscpu"] = run_capture(["lscpu"], timeout=10)
        metadata["raw_system"]["memory"] = run_capture(["free", "-h"], timeout=10)
        metadata["raw_system"]["lsblk"] = run_capture(
            ["lsblk", "-o", "NAME,TYPE,SIZE,MODEL,ROTA,MOUNTPOINTS,FSTYPE"], timeout=10
        )
        metadata["raw_system"]["virt"] = run_capture(["systemd-detect-virt"], timeout=10)
        metadata["raw_system"]["mount"] = run_capture(["findmnt", "-T", str(result_dir)], timeout=10)
    elif platform.system() == "Darwin":
        metadata["raw_system"]["sw_vers"] = run_capture(["sw_vers"], timeout=10)
        metadata["raw_system"]["uname"] = run_capture(["uname", "-a"], timeout=10)
        metadata["raw_system"]["cpu"] = run_capture(
            ["sysctl", "-n", "machdep.cpu.brand_string"], timeout=10
        )
        metadata["raw_system"]["memory"] = run_capture(["sysctl", "-n", "hw.memsize"], timeout=10)
        metadata["raw_system"]["disk"] = run_capture(["df", "-h", str(result_dir)], timeout=10)
    else:
        metadata["raw_system"]["uname"] = run_capture(["uname", "-a"], timeout=10)
        metadata["raw_system"]["disk"] = run_capture(["df", "-h", str(result_dir)], timeout=10)
    return metadata


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
        file.write("\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def append_jsonl(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, sort_keys=True) + "\n")


def stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "max": None, "median": None, "mean": None, "stdev": None, "p95": None}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "median": statistics.median(ordered),
        "mean": statistics.mean(ordered),
        "stdev": statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        "p95": ordered[p95_index],
    }


def format_seconds(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value < 1:
        return f"{value * 1000:.1f} ms"
    return f"{value:.3f} s"


def format_bytes_per_second(value: float | None) -> str:
    if value is None:
        return "n/a"
    units = ["B/s", "KiB/s", "MiB/s", "GiB/s"]
    current = float(value)
    for unit in units:
        if current < 1024 or unit == units[-1]:
            return f"{current:.1f} {unit}"
        current /= 1024
    return f"{current:.1f} GiB/s"
