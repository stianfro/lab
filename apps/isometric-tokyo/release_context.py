"""Bounded, hash-checked build contexts with immutable asset retention."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath

MAX_FILES = 100_000
MAX_BYTES = 1024 * 1024 * 1024
MAX_RELEASES = 8
CONFIGS = ("Dockerfile", "nginx.conf", ".dockerignore")
WEB_ID = re.compile(r"web-[0-9a-f]{24}\Z")
PREVIEW_ID = re.compile(r"shinjuku-(?:preview|map)-[0-9a-f]{24}\Z")
PUBLIC_MARKER = re.compile(
    r"preview/releases/shinjuku-map-[0-9a-f]{24}/pyramid/\.chunk-pyramid\Z"
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def safe_path(name):
    path = PurePosixPath(name)
    if (
        not isinstance(name, str)
        or not name
        or path.is_absolute()
        or path.as_posix() != name
        or any(part in (".", "..") for part in path.parts)
        or (
            any(part.startswith(".") for part in path.parts)
            and not PUBLIC_MARKER.fullmatch(name)
        )
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", name)
    ):
        raise ValueError(f"Unsafe asset path: {name!r}")
    return path


def immutable(name):
    parts = safe_path(name).parts
    return (len(parts) > 1 and parts[0] == "assets") or (
        len(parts) > 3
        and parts[:2] == ("preview", "releases")
        and PREVIEW_ID.fullmatch(parts[2]) is not None
    )


def retained_path(name):
    parts = safe_path(name).parts
    return immutable(name) or (
        len(parts) == 3
        and parts[0] == "retained-notices"
        and WEB_ID.fullmatch(parts[1]) is not None
        and parts[2] in ("LICENSE", "SOFTWARE_LICENSES.txt", "web-release.json")
    )


def scan(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Inventory root must be a real directory")
    records = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise ValueError("Inventory cannot contain symlinks or special files")
        name = path.relative_to(root).as_posix()
        safe_path(name)
        if path.is_file():
            size = path.stat().st_size
            total += size
            if len(records) >= MAX_FILES or total > MAX_BYTES:
                raise ValueError("Retention budget exceeded, review archival policy")
            records.append(
                {"path": name, "bytes": size, "sha256": digest(path.read_bytes())}
            )
    return records


def bundle_inventory(root):
    records = scan(root)
    release = json.loads((root / "web-release.json").read_bytes())
    if not WEB_ID.fullmatch(release["id"]):
        raise ValueError("Invalid release identity")
    actual = [record for record in records if record["path"] != "web-release.json"]
    if actual != sorted(release["assets"], key=lambda record: record["path"]):
        raise ValueError("Bundle inventory does not match files")
    return release, records


def copy_asset(source, destination, record):
    payload = source.read_bytes()
    if len(payload) != record["bytes"] or digest(payload) != record["sha256"]:
        raise ValueError("Source changed while retaining immutable assets")
    if destination.exists():
        if payload != destination.read_bytes():
            raise ValueError(f"Immutable path collision: {destination.name}")
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)


def retain_bundle(bundle, retained):
    release, records = bundle_inventory(bundle)
    for record in records:
        if immutable(record["path"]):
            copy_asset(bundle / record["path"], retained / record["path"], record)
    for name in ("LICENSE", "SOFTWARE_LICENSES.txt", "web-release.json"):
        copy_asset(
            bundle / name,
            retained / "retained-notices" / release["id"] / name,
            next(record for record in records if record["path"] == name),
        )
    return release["id"]


def seal(
    context,
    summary,
    verifier_hash,
    sources,
    previous=None,
    other_bundle=None,
    stage=None,
):
    """Seal a fresh context. Retain history, but never retain mutable entrypoints."""
    site = context / "site"
    release, site_files = bundle_inventory(site)
    if summary["id"] != release["id"]:
        raise ValueError("Product verifier and inventory disagree")
    retained = context / "retained"
    retained.mkdir()
    releases = set()
    if previous:
        history = verify_context(previous)
        shutil.copytree(
            previous / "retained", retained, dirs_exist_ok=True, symlinks=True
        )
        if scan(retained) != history["retained"] or verify_context(previous) != history:
            raise ValueError("Previous context changed while retaining history")
        releases.update(history["retained_releases"])
    if other_bundle:
        releases.add(retain_bundle(other_bundle, retained))
    releases.discard(release["id"])
    # Current notices are available at their usual paths, not duplicated history.
    current_notices = retained / "retained-notices" / release["id"]
    if current_notices.exists():
        shutil.rmtree(current_notices)
    for record in site_files:
        old = retained / record["path"]
        if old.is_file():
            if old.read_bytes() != (site / record["path"]).read_bytes():
                raise ValueError(f"Immutable path collision: {record['path']}")
            old.unlink()
    retained_files = scan(retained)
    if any(not retained_path(record["path"]) for record in retained_files):
        raise ValueError("Retained files must have immutable paths")
    if len(releases) > MAX_RELEASES:
        raise ValueError("Retention budget exceeded, review archival policy")
    if (
        len(site_files) + len(retained_files) > MAX_FILES
        or sum(record["bytes"] for record in site_files + retained_files) > MAX_BYTES
    ):
        raise ValueError("Retention budget exceeded, review archival policy")
    for name in CONFIGS:
        shutil.copyfile(sources / name, context / name)
    report = {
        "schema_version": 2,
        **{key: summary[key] for key in ("id", "preview_id", "assets", "bytes")},
        "inventory_sha256": digest((site / "web-release.json").read_bytes()),
        "verifier_sha256": verifier_hash,
        "configuration": {
            name: digest((context / name).read_bytes()) for name in CONFIGS
        },
        "site": site_files,
        "retained": retained_files,
        "retained_releases": sorted(releases),
        "stage": stage,
    }
    report["context_id"] = "runtime-" + digest(canonical(report))[:24]
    (context / "runtime-release.json").write_text(json.dumps(report, indent=2) + "\n")
    verify_context(context)
    return report


def verify_context(context):
    if context.is_symlink():
        raise ValueError("Context cannot be a symlink")
    report_path = context / "runtime-release.json"
    if report_path.is_symlink():
        raise ValueError("Context manifest cannot be a symlink")
    report = json.loads(report_path.read_bytes())
    if report.get("schema_version") != 2:
        raise ValueError("A sealed version 2 context is required")
    identity = {key: value for key, value in report.items() if key != "context_id"}
    if report.get("context_id") != "runtime-" + digest(canonical(identity))[:24]:
        raise ValueError("Context identity mismatch")
    release, site_files = bundle_inventory(context / "site")
    retained_files = scan(context / "retained")
    if site_files != report["site"] or retained_files != report["retained"]:
        raise ValueError("Context inventory mismatch")
    if (
        release["id"] != report["id"]
        or digest((context / "site" / "web-release.json").read_bytes())
        != report["inventory_sha256"]
    ):
        raise ValueError("Context release mismatch")
    if any(not retained_path(record["path"]) for record in retained_files):
        raise ValueError("Retained files must have immutable paths")
    if len(report["retained_releases"]) > MAX_RELEASES:
        raise ValueError("Retention budget exceeded, review archival policy")
    if (
        len(site_files) + len(retained_files) > MAX_FILES
        or sum(record["bytes"] for record in site_files + retained_files) > MAX_BYTES
    ):
        raise ValueError("Retention budget exceeded, review archival policy")
    site_by_path = {record["path"]: record for record in site_files}
    for record in retained_files:
        if record["path"] in site_by_path:
            raise ValueError("Retained paths must not shadow canonical paths")
    if set(report["configuration"]) != set(CONFIGS):
        raise ValueError("Context configuration list mismatch")
    for name, expected in report["configuration"].items():
        path = context / name
        if path.is_symlink() or digest(path.read_bytes()) != expected:
            raise ValueError("Context configuration hash mismatch")
    return report


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", type=Path)
    args = parser.parse_args()
    report = verify_context(args.context)
    print(
        json.dumps(
            {key: report[key] for key in ("context_id", "id", "retained_releases")}
        )
    )
