"""Copy only a product-verifier-approved immutable bundle into a build context."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def verify(verifier: Path, directory: Path) -> dict:
    result = subprocess.run(
        [sys.executable, str(verifier), "--verify", str(directory)],
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(result.stdout)


def outside_repository(path: Path) -> Path:
    if path.is_symlink():
        raise ValueError("Build context cannot be a symlink")
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / ".git").exists():
            raise ValueError("Build context must be outside source repositories")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("verifier", type=Path)
    parser.add_argument("context", type=Path)
    args = parser.parse_args()
    sources = Path(__file__).resolve().parent
    runtime = outside_repository(args.context)
    bundle = args.bundle.resolve(strict=True)
    verifier = args.verifier.resolve(strict=True)
    runtime.mkdir(parents=True, exist_ok=True)
    before = verify(verifier, bundle)
    site = runtime / "site"
    if site.is_symlink():
        raise ValueError("Refusing a symlink build context")
    staging = Path(tempfile.mkdtemp(prefix=".site-stage-", dir=runtime))
    try:
        shutil.copytree(bundle, staging, dirs_exist_ok=True)
        after = verify(verifier, staging)
        if before != after or before != verify(verifier, bundle):
            raise ValueError("Bundle changed while preparing build context")
        if site.exists():
            if not site.is_dir():
                raise ValueError("Build context must be a directory")
            if not (site / "web-release.json").exists():
                files = sorted(
                    path.relative_to(site).as_posix()
                    for path in site.rglob("*")
                    if path.is_file()
                )
                if (
                    files != ["index.html"]
                    or "Fixture only" not in (site / "index.html").read_text()
                ):
                    raise ValueError("Refusing to replace an unknown build context")
            shutil.rmtree(site)
        staging.rename(site)
        for name in ("Dockerfile", "nginx.conf", ".dockerignore"):
            source = sources / name
            target = runtime / name
            if source.is_symlink() or target.is_symlink():
                raise ValueError("Runtime files cannot be symlinks")
            shutil.copyfile(source, target)
        report = before | {
            "inventory_sha256": hashlib.sha256(
                (site / "web-release.json").read_bytes()
            ).hexdigest(),
            "verifier_sha256": hashlib.sha256(verifier.read_bytes()).hexdigest(),
            "nginx_sha256": hashlib.sha256(
                (runtime / "nginx.conf").read_bytes()
            ).hexdigest(),
            "dockerfile_sha256": hashlib.sha256(
                (runtime / "Dockerfile").read_bytes()
            ).hexdigest(),
        }
        (runtime / "runtime-release.json").write_text(
            json.dumps(report, indent=2) + "\n"
        )
        print(json.dumps(report, indent=2))
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    main()
