#!/usr/bin/env python3
"""Copy a fixture and apply deterministic small edits."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    parser.add_argument("--limit", type=int, default=400)
    args = parser.parse_args()

    if args.dest.exists():
        shutil.rmtree(args.dest)
    shutil.copytree(args.source, args.dest)

    edited = 0
    for path in sorted(args.dest.rglob("*.py"))[: args.limit]:
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "\n# bench edit\n", encoding="utf-8")
        edited += 1
    for path in sorted(args.dest.rglob("*.yaml"))[: args.limit // 2]:
        text = path.read_text(encoding="utf-8")
        path.write_text(text + "benchEdit: true\n", encoding="utf-8")
        edited += 1
    print(f"edited={edited}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
