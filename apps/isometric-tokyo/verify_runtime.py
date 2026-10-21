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
    request = urllib.request.Request(
        base + path,
        headers={
            "User-Agent": "isometric-tokyo-release-verifier/1.0 (+https://github.com/stianfro/isometric-tokyo)",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
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


def cache_directives(headers):
    return {part.strip() for part in headers.get("cache-control", "").split(",")}


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
    assert {"no-store", "no-transform"}.issubset(cache_directives(headers)), headers
    status, headers, body = request(base, "/")
    assert status == 200 and b"<html" in body.lower(), (status, body[:100])
    assert {"no-cache", "no-transform"}.issubset(cache_directives(headers)), headers
    for key in (
        "content-security-policy",
        "x-content-type-options",
        "x-frame-options",
        "referrer-policy",
    ):
        assert key in headers, (key, headers)
    status, headers, body = request(base, "/favicon.ico")
    assert status == 204 and body == b"", (status, body)
    assert "no-transform" in cache_directives(headers), headers
    for path in (
        "/atlas/missing_files/20/0_0.webp",
        "/not-an-application-route",
        "/.env",
    ):
        status, headers, body = request(base, path)
        assert status in (403, 404), (path, status)
        assert b'<div id="root"' not in body, path
        assert {"no-store", "no-transform"}.issubset(cache_directives(headers)), (
            path,
            headers,
        )
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
    assert {"no-cache", "no-transform"}.issubset(cache_directives(headers)), headers

    def check_asset(record):
        status, headers, body = request(base, "/" + record["path"])
        assert status == 200, (record["path"], status)
        assert len(body) == record["bytes"], record["path"]
        assert hashlib.sha256(body).hexdigest() == record["sha256"], record["path"]
        refreshed_policy = 0
        if "no-transform" not in cache_directives(headers):
            # Previously cached immutable bytes can retain an earlier policy.
            # Keep validating canonical bytes, then separately check fresh headers.
            is_cached_asset = record["path"].startswith("assets/") or record[
                "path"
            ].lower().endswith((".png", ".webp", ".jpg", ".jpeg"))
            assert is_cached_asset and int(headers.get("age", "-1")) >= 0, record[
                "path"
            ]
            policy = hashlib.sha256((context / "nginx.conf").read_bytes()).hexdigest()[
                :16
            ]
            fresh_status, fresh_headers, fresh_body = request(
                base, "/" + record["path"] + "?runtime-policy=" + policy
            )
            assert fresh_status == 200, (record["path"], fresh_status)
            assert len(fresh_body) == record["bytes"], record["path"]
            assert hashlib.sha256(fresh_body).hexdigest() == record["sha256"], record[
                "path"
            ]
            assert "no-transform" in cache_directives(fresh_headers), record["path"]
            refreshed_policy = 1
        if record["path"].startswith("assets/"):
            assert "immutable" in headers.get("cache-control", ""), record["path"]
        if record["path"].endswith(".json"):
            assert "no-cache" in cache_directives(headers), record["path"]
        return len(body), refreshed_policy

    with ThreadPoolExecutor(max_workers=6) as pool:
        sizes = list(pool.map(check_asset, expected["assets"]))
    return {
        "release": expected["id"],
        "verified_files": len(sizes) + 1,
        "verified_bytes": sum(size for size, _ in sizes) + len(expected_bytes),
        "refreshed_policy_files": sum(refreshed for _, refreshed in sizes),
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
