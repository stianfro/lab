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
    process: subprocess.Popen[str] | None
    expires_at: float
    cancel_cmd: list[str] | None = None


class BridgeState:
    def __init__(
        self,
        target: str | None,
        forward_ttl: int,
        dry_run: bool,
        ssh_control_path: str | None,
    ) -> None:
        self.target = target
        self.forward_ttl = forward_ttl
        self.dry_run = dry_run
        self.ssh_control_path = ssh_control_path
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
            if existing and self.forward_active(existing):
                existing.expires_at = now + self.forward_ttl
                self.log(f"reusing localhost:{port} callback forward")
                return
            if existing:
                self.forwards.pop(port, None)

            if self.dry_run:
                if self.ssh_control_path:
                    self.log(
                        f"would request callback forward localhost:{port} "
                        f"through SSH control socket {self.ssh_control_path}",
                    )
                else:
                    self.log(f"would start background callback forward localhost:{port} to {self.target}")
                return

            forward = self.start_forward(port, now)
            if forward:
                self.forwards[port] = forward

    def forward_active(self, forward: Forward) -> bool:
        return forward.process is None or forward.process.poll() is None

    def forward_spec(self, port: int) -> str:
        return f"127.0.0.1:{port}:127.0.0.1:{port}"

    def start_forward(self, port: int, now: float) -> Forward | None:
        if self.ssh_control_path and self.target:
            forward = self.start_control_forward(port, now)
            if forward:
                return forward
            self.log(f"falling back to a background SSH callback forward for localhost:{port}")
        return self.start_background_forward(port, now)

    def start_control_forward(self, port: int, now: float) -> Forward | None:
        if not self.ssh_control_path or not self.target:
            return None

        cmd = [
            "ssh",
            "-S",
            self.ssh_control_path,
            "-O",
            "forward",
            "-L",
            self.forward_spec(port),
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=5",
            self.target,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
        except subprocess.TimeoutExpired:
            self.log(f"timed out requesting SSH control callback forward for localhost:{port}")
            return None
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if stderr:
                self.log(f"failed to request SSH control callback forward for localhost:{port}: {stderr}")
            else:
                self.log(f"failed to request SSH control callback forward for localhost:{port}")
            return None

        cancel_cmd = [
            "ssh",
            "-S",
            self.ssh_control_path,
            "-O",
            "cancel",
            "-L",
            self.forward_spec(port),
            "-o",
            "BatchMode=yes",
            self.target,
        ]
        self.log(f"forwarding localhost:{port} to devbox through existing SSH session")
        return Forward(process=None, expires_at=now + self.forward_ttl, cancel_cmd=cancel_cmd)

    def start_background_forward(self, port: int, now: float) -> Forward | None:
        if not self.target:
            return None

        cmd = [
            "ssh",
            "-N",
            "-L",
            self.forward_spec(port),
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
                self.log(f"failed to start background callback forward for localhost:{port}: {stderr}")
            else:
                self.log(f"failed to start background callback forward for localhost:{port}")
            return None

        self.log(f"forwarding localhost:{port} to devbox with background SSH process")
        return Forward(process=process, expires_at=now + self.forward_ttl)

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
        if forward.cancel_cmd:
            subprocess.run(forward.cancel_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if forward.process and forward.process.poll() is None:
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
    append_local_callback_port(url, ports)
    for redirect_uri in extract_redirect_uris(url):
        append_local_callback_port(redirect_uri, ports)
    return ports


def append_local_callback_port(uri: str, ports: list[int]) -> None:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        return
    if (parsed.hostname or "").lower() not in LOCAL_HOSTS:
        return
    try:
        port = parsed.port
    except ValueError:
        return
    if port and port not in ports:
        ports.append(port)


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
    parser.add_argument(
        "--ssh-control-path",
        help="SSH ControlPath for attaching callback forwards to the existing devbox session",
    )
    parser.add_argument("--dry-run", action="store_true", help="log actions without opening URLs or starting forwards")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="optional command to run while the bridge is active")
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args


def main() -> int:
    args = parse_args()
    state = BridgeState(
        target=args.target,
        forward_ttl=args.forward_ttl,
        dry_run=args.dry_run,
        ssh_control_path=args.ssh_control_path,
    )
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
