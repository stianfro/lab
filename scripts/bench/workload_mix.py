#!/usr/bin/env python3
"""Run several local developer commands at the same time."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path


def existing_command(name: str) -> str | None:
    return shutil.which(name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()

    repo = args.repo.resolve()
    fixture = args.fixture.resolve()
    commands: list[list[str]] = [["git", "-C", str(repo), "status", "--short"]]

    if existing_command("rg"):
        commands.append(["rg", "-n", "TODO|handler|apiVersion", str(fixture)])
        commands.append(["rg", "-n", "apiVersion|kind|metadata", str(repo / "apps"), str(repo / "clusters")])
    commands.append(["python3", str(repo / "scripts/bench/workload_scan.py"), "--git-files", str(repo)])

    if existing_command("yq"):
        commands.append([
            "sh",
            "-c",
            "git ls-files '*.yaml' '*.yml' | xargs yq e 'true' >/dev/null",
        ])

    started = time.perf_counter()
    procs = [
        subprocess.Popen(command, cwd=repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for command in commands
    ]
    failed = 0
    for proc in procs:
        stdout, stderr = proc.communicate()
        if proc.returncode != 0:
            failed += 1
            print(stderr.strip() or stdout.strip())
    elapsed = time.perf_counter() - started
    print(f"commands={len(commands)} failed={failed} elapsed_seconds={elapsed:.6f}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
