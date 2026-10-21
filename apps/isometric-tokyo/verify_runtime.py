"""Check the isolated static server without using browser UI."""

import argparse
import hashlib
import json
import subprocess
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def request(base, path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as response:
            return (
                response.status,
                {key.lower(): value for key, value in response.headers.items()},
                response.read(),
            )
    except urllib.error.HTTPError as error:
        return (
            error.code,
            {key.lower(): value for key, value in error.headers.items()},
            error.read(),
        )


def verify(base, context):
    for attempt in range(30):
        try:
            status, headers, body = request(base, "/healthz")
            if status == 200:
                break
        except (OSError, urllib.error.URLError):
            if attempt == 29:
                raise
        time.sleep(0.5)
    assert status == 200 and body == b"ok\n", (status, body)
    assert headers.get("cache-control") == "no-store", headers
    status, headers, body = request(base, "/")
    assert status == 200 and b"<html" in body.lower(), (status, body[:100])
    assert "no-cache" in headers.get("cache-control", ""), headers
    for key in (
        "content-security-policy",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
    ):
        assert key in headers, (key, headers)
    for path in (
        "/atlas/missing_files/20/0_0.webp",
        "/not-an-application-route",
        "/.env",
    ):
        status, headers, body = request(base, path)
        assert status in (403, 404), (path, status)
        assert b'<div id="root"' not in body, path
        assert headers.get("cache-control") == "no-store", (path, headers)
    payload = verify_payload(base, context)
    print(
        json.dumps(
            {
                "url": base,
                "health": "pass",
                "headers": "pass",
                "missing_files": "pass",
                **payload,
            }
        )
    )


def verify_payload(base, context):
    inventory = context / "site" / "web-release.json"
    expected_bytes = inventory.read_bytes()
    expected = json.loads(expected_bytes)
    status, headers, actual = request(base, "/web-release.json")
    assert status == 200 and actual == expected_bytes, "Release inventory mismatch"
    assert headers.get("cache-control") == "no-cache", headers

    def check_asset(record):
        status, headers, body = request(base, "/" + record["path"])
        assert status == 200, (record["path"], status)
        assert len(body) == record["bytes"], record["path"]
        assert hashlib.sha256(body).hexdigest() == record["sha256"], record["path"]
        if record["path"].startswith("assets/"):
            assert "immutable" in headers.get("cache-control", ""), record["path"]
        if record["path"].endswith(".json"):
            assert headers.get("cache-control") == "no-cache", record["path"]
        return len(body)

    with ThreadPoolExecutor(max_workers=6) as pool:
        sizes = list(pool.map(check_asset, expected["assets"]))
    return {
        "release": expected["id"],
        "verified_files": len(sizes) + 1,
        "verified_bytes": sum(sizes) + len(expected_bytes),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", type=Path)
    parser.add_argument("--url")
    args = parser.parse_args()
    if args.url:
        verify(args.url.rstrip("/"), args.context)
    else:
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
                "isometric-runtime-check:local",
            ],
            text=True,
        ).strip()
        try:
            mapping = subprocess.check_output(
                ["docker", "port", container, "8080/tcp"], text=True
            ).strip()
            verify("http://" + mapping, args.context)
        finally:
            subprocess.run(
                ["docker", "stop", container], check=True, stdout=subprocess.DEVNULL
            )
