"""Opt-in container regression: both rollout stages serve both release versions."""

import argparse
import json
import subprocess
from pathlib import Path

from prepare_bundle import outside_repository
from release_context import verify_context
from stage_release import stage
from test_retention import bundle, verifier
from verify_runtime import request, verify


def main(directory):
    directory = outside_repository(directory)
    directory.mkdir(parents=True, exist_ok=False)
    current = bundle(directory, "a")
    upcoming = bundle(directory, "b", kind="map")
    product_verifier = verifier(directory)
    transition = directory / "transition"
    stage(current, product_verifier, upcoming, product_verifier, transition)
    summaries = []
    for role in ("compatibility", "activation"):
        context = transition / role
        report = verify_context(context)
        image = "isometric-runtime-fixture:" + role
        subprocess.run(
            [
                "docker",
                "buildx",
                "build",
                "--load",
                "--build-arg",
                "RUNTIME_CONTEXT_ID=" + report["context_id"],
                "-t",
                image,
                str(context),
            ],
            check=True,
        )
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--entrypoint",
                "nginx",
                image,
                "-t",
            ],
            check=True,
        )
        container = subprocess.check_output(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--read-only",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16m",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "-p",
                "127.0.0.1::8080",
                image,
            ],
            text=True,
        ).strip()
        try:
            base = (
                "http://"
                + subprocess.check_output(
                    ["docker", "port", container, "8080/tcp"], text=True
                ).strip()
            )
            verify(base, context)
            for letter in ("a", "b"):
                status, _, body = request(base, "/assets/app-" + letter + ".js")
                assert status == 200 and body == letter.encode()
            for path in (
                "/assets/.env",
                "/assets/missing.js",
                "/retained-notices/missing/LICENSE",
            ):
                assert request(base, path)[0] in (403, 404)
            assert (
                request(base, "/preview/manifest.json")[2]
                == (context / "site/preview/manifest.json").read_bytes()
            )
            assert request(base, "/")[2] == (context / "site/index.html").read_bytes()
            summaries.append(
                {
                    "stage": role,
                    "context_id": report["context_id"],
                    "both_versions_available": True,
                }
            )
        finally:
            subprocess.run(
                ["docker", "stop", container], check=True, stdout=subprocess.DEVNULL
            )
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    main(parser.parse_args().output)
