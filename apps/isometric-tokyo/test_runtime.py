"""Offline contract tests for the isolated runtime packaging and probes."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare_bundle
import verify_runtime


class RuntimeTests(unittest.TestCase):
    def test_probe_identifies_its_client(self):
        with patch.object(verify_runtime.urllib.request, "urlopen") as opener:
            response = opener.return_value.__enter__.return_value
            response.status = 200
            response.headers = {"Cache-Control": "no-store"}
            response.read.return_value = b"ok\n"
            status, headers, body = verify_runtime.request(
                "http://fixture.invalid", "/healthz"
            )
        request = opener.call_args.args[0]
        self.assertIn(
            "isometric-tokyo-release-verifier", request.get_header("User-agent")
        )
        self.assertEqual(
            (status, headers, body), (200, {"cache-control": "no-store"}, b"ok\n")
        )

    def test_cache_directive_parser_is_order_independent(self):
        directives = verify_runtime.cache_directives(
            {"cache-control": "public, no-cache, no-transform"}
        )
        self.assertEqual(directives, {"public", "no-cache", "no-transform"})

    def test_context_must_be_outside_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            with self.assertRaisesRegex(ValueError, "outside source repositories"):
                prepare_bundle.outside_repository(root / "context")

    def test_context_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                prepare_bundle.outside_repository(root / "link")

    def test_empty_context_outside_repository_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "context"
            self.assertEqual(
                prepare_bundle.outside_repository(target), target.resolve()
            )

    def test_payload_checks_every_file_and_cache_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = Path(temporary)
            (context / "site").mkdir()
            payload = b"export const fixture = true;"
            metadata = {
                "id": "web-fixture",
                "assets": [
                    {
                        "path": "assets/app-hash.js",
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
            inventory = json.dumps(metadata).encode()
            (context / "site" / "web-release.json").write_bytes(inventory)
            responses = {
                "/web-release.json": (
                    200,
                    {"cache-control": "public, no-cache, no-transform"},
                    inventory,
                ),
                "/assets/app-hash.js": (
                    200,
                    {
                        "cache-control": "public, max-age=31536000, immutable, no-transform"
                    },
                    payload,
                ),
            }
            with patch.object(
                verify_runtime,
                "request",
                side_effect=lambda base, path: responses[path],
            ):
                result = verify_runtime.verify_payload(
                    "http://fixture.invalid", context
                )
            self.assertEqual(result["verified_files"], 2)
            self.assertEqual(result["verified_bytes"], len(inventory) + len(payload))
            responses["/assets/app-hash.js"] = (
                200,
                {"cache-control": "public, immutable, no-transform"},
                b"wrong",
            )
            with (
                patch.object(
                    verify_runtime,
                    "request",
                    side_effect=lambda base, path: responses[path],
                ),
                self.assertRaises(AssertionError),
            ):
                verify_runtime.verify_payload("http://fixture.invalid", context)

    def test_old_cached_headers_require_fresh_policy_and_identical_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            context = Path(temporary)
            (context / "site").mkdir()
            (context / "nginx.conf").write_text("fixture policy")
            payload = b"fixture"
            metadata = {
                "id": "web-fixture",
                "assets": [
                    {
                        "path": "assets/app.js",
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
            inventory = json.dumps(metadata).encode()
            (context / "site" / "web-release.json").write_bytes(inventory)
            fresh_cache = "public, immutable, no-transform"

            def response(base, path):
                if path == "/web-release.json":
                    return (
                        200,
                        {"cache-control": "public, no-cache, no-transform"},
                        inventory,
                    )
                if "?runtime-policy=" in path:
                    return 200, {"cache-control": fresh_cache}, payload
                return 200, {"cache-control": "public, immutable", "age": "32"}, payload

            with patch.object(verify_runtime, "request", side_effect=response):
                result = verify_runtime.verify_payload(
                    "http://fixture.invalid", context
                )
            self.assertEqual(result["refreshed_policy_files"], 1)
            self.assertEqual(result["verified_files"], 2)
            fresh_cache = "public, immutable"
            with (
                patch.object(verify_runtime, "request", side_effect=response),
                self.assertRaises(AssertionError),
            ):
                verify_runtime.verify_payload("http://fixture.invalid", context)

    def test_missing_inventory_is_not_success(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaises(FileNotFoundError),
        ):
            verify_runtime.verify_payload("http://fixture.invalid", Path(temporary))


if __name__ == "__main__":
    unittest.main()
