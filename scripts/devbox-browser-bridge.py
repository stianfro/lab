#!/usr/bin/env python3
"""Open devbox browser URLs on the local workstation.

The devbox posts URLs to this local HTTP server through an SSH reverse forward.
For OAuth authorization-code redirects that use localhost, this script also
starts a temporary SSH local forward from the workstation back to the devbox so
the final browser redirect reaches the CLI callback listener.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Iterable

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Forward:
    process: subprocess.Popen[str]
    expires_at: float


class BridgeState:
    def __init__(self, target: str | None, forward_ttl: int, dry_run: bool) -> None:
        self.target = target
        self.forward_ttl = forward_ttl
        self.dry_run = dry_run
        self.forwards: dict[int, Forward] = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()

    def log(self, message: str) -> None:
        print(f"devbox-browser-bridge: {message}", file=sys.stderr, flush=True)

    def ensure_callback_forwards(self, url: str) -> None:
        for port in extract_redirect_ports(url):
            self.ensure_forward(port)

    def ensure_forward(self, port: int) -> None:
        if not self.target:
            self.log(f"not forwarding localhost:{port}, no SSH target configured")
            return

        now = time.time()
        with self.lock:
            existing = self.forwards.get(port)
            if existing and existing.process.poll() is None:
                existing.expires_at = now + self.forward_ttl
                self.log(f"reusing localhost:{port} callback forward")
                return
            if existing:
                self.forwards.pop(port, None)

            if self.dry_run:
                self.log(f"would forward localhost:{port} to {self.target}")
                return

            cmd = [
                "ssh",
                "-N",
                "-L",
                f"127.0.0.1:{port}:127.0.0.1:{port}",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "BatchMode=yes",
                self.target,
            ]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            time.sleep(0.25)
            if process.poll() is not None:
                stderr = (process.stderr.read() if process.stderr else "").strip()
                if stderr:
                    self.log(f"failed to forward localhost:{port}: {stderr}")
                else:
                    self.log(f"failed to forward localhost:{port}")
                return

            self.forwards[port] = Forward(process=process, expires_at=now + self.forward_ttl)
            self.log(f"forwarding localhost:{port} to devbox for OAuth callback")

    def cleanup_loop(self) -> None:
        while not self.stopping.wait(5):
            self.cleanup_expired()

    def cleanup_expired(self) -> None:
        now = time.time()
        with self.lock:
            expired = [port for port, forward in self.forwards.items() if forward.expires_at <= now]
        for port in expired:
            self.stop_forward(port, reason="expired")

    def stop_forward(self, port: int, reason: str) -> None:
        with self.lock:
            forward = self.forwards.pop(port, None)
        if not forward:
            return
        if forward.process.poll() is None:
            forward.process.terminate()
            try:
                forward.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                forward.process.kill()
                forward.process.wait(timeout=5)
        self.log(f"stopped localhost:{port} callback forward ({reason})")

    def stop_all(self) -> None:
        self.stopping.set()
        with self.lock:
            ports = list(self.forwards)
        for port in ports:
            self.stop_forward(port, reason="shutdown")

    def open_url(self, url: str) -> None:
        if self.dry_run:
            self.log(f"would open {url}")
            return

        system = platform.system()
        if system == "Darwin":
            cmd = ["open", url]
        elif system == "Linux":
            cmd = ["xdg-open", url]
        elif system == "Windows":
            cmd = ["cmd", "/c", "start", "", url]
        else:
            raise RuntimeError(f"unsupported local platform: {system}")

        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.log(f"opened {url}")


def extract_redirect_ports(url: str) -> list[int]:
    ports: list[int] = []
    for redirect_uri in extract_redirect_uris(url):
        parsed = urllib.parse.urlparse(redirect_uri)
        if parsed.scheme not in {"http", "https"}:
            continue
        if (parsed.hostname or "").lower() not in LOCAL_HOSTS:
            continue
        try:
            port = parsed.port
        except ValueError:
            continue
        if port and port not in ports:
            ports.append(port)
    return ports


def extract_redirect_uris(url: str) -> Iterable[str]:
    parsed = urllib.parse.urlparse(url)
    query_parts = [parsed.query]
    if parsed.fragment:
        fragment = urllib.parse.urlparse(parsed.fragment)
        query_parts.append(fragment.query or parsed.fragment)
    for query in query_parts:
        for key, value in urllib.parse.parse_qsl(query, keep_blank_values=True):
            if key == "redirect_uri" and value:
                yield value


def parse_url_from_request(path: str, body: bytes, content_type: str) -> str | None:
    parsed_path = urllib.parse.urlparse(path)
    query_url = urllib.parse.parse_qs(parsed_path.query).get("url", [None])[0]
    if query_url:
        return query_url

    if not body:
        return None

    if "application/json" in content_type:
        payload = json.loads(body.decode("utf-8"))
        url = payload.get("url")
        return url if isinstance(url, str) else None

    return body.decode("utf-8").strip()


def valid_browser_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def make_handler(state: BridgeState) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.handle_open(body=b"")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            self.handle_open(body=self.rfile.read(length))

        def handle_open(self, body: bytes) -> None:
            parsed_path = urllib.parse.urlparse(self.path)
            if parsed_path.path != "/open":
                self.send_error(404)
                return

            try:
                url = parse_url_from_request(
                    self.path,
                    body,
                    self.headers.get("Content-Type", ""),
                )
            except Exception as exc:  # noqa: BLE001
                self.send_error(400, f"invalid request: {exc}")
                return

            if not url or not valid_browser_url(url):
                self.send_error(400, "expected http or https URL")
                return

            try:
                state.ensure_callback_forwards(url)
                state.open_url(url)
            except Exception as exc:  # noqa: BLE001
                state.log(f"open failed: {exc}")
                self.send_error(500, str(exc))
                return

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")

        def log_message(self, format: str, *args: object) -> None:
            state.log(format % args)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Open devbox URLs on this workstation")
    parser.add_argument("--target", help="SSH target for callback forwards, such as stian@192.168.1.51")
    parser.add_argument("--port", type=int, default=48765, help="local browser bridge port")
    parser.add_argument("--forward-ttl", type=int, default=900, help="seconds to keep callback forwards")
    parser.add_argument("--dry-run", action="store_true", help="log actions without opening URLs or starting forwards")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="optional command to run while the bridge is active")
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args


def main() -> int:
    args = parse_args()
    state = BridgeState(target=args.target, forward_ttl=args.forward_ttl, dry_run=args.dry_run)
    handler = make_handler(state)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    cleanup_thread = threading.Thread(target=state.cleanup_loop, daemon=True)
    cleanup_thread.start()

    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    state.log(f"listening on 127.0.0.1:{args.port}")

    try:
        if args.command:
            return subprocess.run(args.command, check=False).returncode
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 130
    finally:
        server.shutdown()
        server.server_close()
        state.stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
