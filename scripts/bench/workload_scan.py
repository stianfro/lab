#!/usr/bin/env python3
"""Read many files and hash their contents."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".go",
    ".hcl",
    ".ini",
    ".json",
    ".js",
    ".md",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".txt",
    ".yaml",
    ".yml",
}


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return [root / line for line in result.stdout.splitlines() if line]


def walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            files.append(path)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--git-files", action="store_true")
    args = parser.parse_args()

    root = args.path.resolve()
    files = tracked_files(root) if args.git_files else walk_files(root)
    digest = hashlib.sha256()
    bytes_read = 0
    for path in files:
        if not path.is_file():
            continue
        data = path.read_bytes()
        bytes_read += len(data)
        digest.update(str(path.relative_to(root)).encode("utf-8", errors="ignore"))
        digest.update(b"\0")
        digest.update(data)
    print(f"files={len(files)} bytes={bytes_read} sha256={digest.hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
