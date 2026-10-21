"""Copy only a product-verifier-approved immutable bundle into a build context."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from release_context import digest, seal, verify_context


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


def prepare(bundle, verifier, context, previous=None, other_bundle=None, stage=None):
    context = outside_repository(context)
    context.parent.mkdir(parents=True, exist_ok=True)
    before = verify(verifier, bundle)
    verifier_hash = digest(verifier.read_bytes())
    temporary = Path(tempfile.mkdtemp(prefix=".runtime-stage-", dir=context.parent))
    try:
        shutil.copytree(bundle, temporary / "site", symlinks=True)
        after = verify(verifier, temporary / "site")
        if before != after or before != verify(verifier, bundle):
            raise ValueError("Bundle changed while preparing build context")
        report = seal(
            temporary,
            before,
            verifier_hash,
            Path(__file__).resolve().parent,
            previous=previous,
            other_bundle=other_bundle,
            stage=stage,
        )
        if context.exists():
            existing = verify_context(context)
            if existing != report:
                raise ValueError("Use a new context path for a different release")
        else:
            temporary.rename(context)
        return report
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("verifier", type=Path)
    parser.add_argument("context", type=Path)
    args = parser.parse_args()
    report = prepare(
        args.bundle.resolve(strict=True),
        args.verifier.resolve(strict=True),
        args.context,
    )
    print(
        json.dumps(
            {key: report[key] for key in ("context_id", "id", "retained_releases")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
