#!/usr/bin/env python3
"""Compare two benchmark result directories."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common import format_bytes_per_second, format_seconds, read_json, slug, utc_stamp, write_json


def load_summary(path: Path) -> dict[str, Any]:
    if path.is_dir():
        path = path / "summary.json"
    return read_json(path)


def metric_for(item: dict[str, Any]) -> tuple[str, float | None, bool, str]:
    metrics = item.get("metrics", {})
    if "median_seconds" in metrics and metrics["median_seconds"] is not None:
        return "median_seconds", float(metrics["median_seconds"]), True, "seconds"
    for key in ["read_bytes_per_second", "write_bytes_per_second", "iops", "read_iops", "write_iops"]:
        value = metrics.get(key)
        if value is not None:
            return key, float(value), False, key
    return "none", None, True, "none"


def better_text(left_value: float | None, right_value: float | None, lower_is_better: bool) -> str:
    if left_value is None or right_value is None or right_value == 0 or left_value == 0:
        return "n/a"
    spread = abs(left_value - right_value) / max(abs(left_value), abs(right_value))
    if spread < 0.02:
        return "similar"
    if lower_is_better:
        ratio = right_value / left_value
        if ratio > 1:
            return f"left {ratio:.2f}x faster"
        return f"right {1 / ratio:.2f}x faster"
    ratio = left_value / right_value
    if ratio > 1:
        return f"left {ratio:.2f}x higher"
    return f"right {1 / ratio:.2f}x higher"


def fmt(value: float | None, unit: str) -> str:
    if value is None:
        return "n/a"
    if unit == "seconds":
        return format_seconds(value)
    if "bytes_per_second" in unit:
        return format_bytes_per_second(value)
    return f"{value:.2f}"


def compare(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_items = {item["name"]: item for item in left.get("benchmarks", []) if item.get("status") == "ok"}
    right_items = {item["name"]: item for item in right.get("benchmarks", []) if item.get("status") == "ok"}
    rows: list[dict[str, Any]] = []
    for name in sorted(set(left_items) & set(right_items)):
        left_metric, left_value, left_lower, left_unit = metric_for(left_items[name])
        right_metric, right_value, right_lower, right_unit = metric_for(right_items[name])
        if left_metric != right_metric or left_unit != right_unit:
            continue
        lower_is_better = left_lower and right_lower
        rows.append(
            {
                "name": name,
                "metric": left_metric,
                "unit": left_unit,
                "lower_is_better": lower_is_better,
                "left": left_value,
                "right": right_value,
                "result": better_text(left_value, right_value, lower_is_better),
            }
        )
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "left": {"label": left.get("label"), "result_dir": left.get("result_dir")},
        "right": {"label": right.get("label"), "result_dir": right.get("result_dir")},
        "rows": rows,
        "left_only": sorted(set(left_items) - set(right_items)),
        "right_only": sorted(set(right_items) - set(left_items)),
    }


def write_markdown(path: Path, data: dict[str, Any]) -> None:
    lines = [
        "# Benchmark Comparison",
        "",
        f"Left: `{data['left'].get('label')}`",
        f"Right: `{data['right'].get('label')}`",
        "",
        "| Benchmark | Metric | Left | Right | Result |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for row in data["rows"]:
        lines.append(
            f"| {row['name']} | {row['metric']} | {fmt(row['left'], row['unit'])} | {fmt(row['right'], row['unit'])} | {row['result']} |"
        )
    if data["left_only"] or data["right_only"]:
        lines += ["", "## Missing matches", ""]
        for name in data["left_only"]:
            lines.append(f"- Left only: `{name}`")
        for name in data["right_only"]:
            lines.append(f"- Right only: `{name}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two benchmark result directories")
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--out", type=Path, help="Output directory for comparison files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    left = load_summary(args.left)
    right = load_summary(args.right)
    data = compare(left, right)
    out_dir = args.out or Path(".cache") / "bench" / "comparisons" / f"{utc_stamp()}-{slug(left.get('label') or 'left')}-vs-{slug(right.get('label') or 'right')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "comparison.json", data)
    write_markdown(out_dir / "comparison.md", data)
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
