#!/usr/bin/env python3
"""Validate the agent-browser core MCP server over stdio."""

import json
import select
import subprocess
import sys
import tempfile
import time

COMMAND = ["/usr/local/bin/agent-browser", "mcp", "--tools", "core"]
READ_TIMEOUT_SECONDS = 10


class CheckError(RuntimeError):
    """A health-check failure."""


def send_message(process, message):
    """Send one newline-delimited JSON-RPC message."""
    assert process.stdin is not None
    process.stdin.write(json.dumps(message) + "\n")
    process.stdin.flush()


def read_message(process, deadline):
    """Read and parse one message before the monotonic deadline."""
    assert process.stdout is not None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CheckError("timed out while waiting for MCP output")
    readable, _, _ = select.select([process.stdout], [], [], remaining)
    if not readable:
        raise CheckError("timed out while waiting for MCP output")
    line = process.stdout.readline()
    if not line:
        raise CheckError("MCP server closed stdout before replying")
    try:
        message = json.loads(line)
    except json.JSONDecodeError as error:
        raise CheckError(f"MCP server returned invalid JSON: {error}") from error
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        raise CheckError(f"invalid JSON-RPC message: {message!r}")
    return message


def read_response(process, request_id, label):
    """Skip notifications and return the matching response."""
    deadline = time.monotonic() + READ_TIMEOUT_SECONDS
    while True:
        message = read_message(process, deadline)
        if "id" not in message:
            if "method" not in message:
                raise CheckError(f"invalid notification before {label}: {message!r}")
            continue
        if message["id"] != request_id:
            raise CheckError(
                f"{label} response ID mismatch, expected {request_id!r}, "
                f"got {message['id']!r}"
            )
        if "error" in message:
            raise CheckError(f"{label} returned an error: {message['error']!r}")
        if "result" not in message or not isinstance(message["result"], dict):
            raise CheckError(f"{label} response has no object result: {message!r}")
        return message["result"]


def stderr_text(stderr_file):
    """Read captured child stderr without blocking."""
    stderr_file.flush()
    stderr_file.seek(0)
    return stderr_file.read().strip()


def main():
    """Run the initialize handshake and list all core tools."""
    with tempfile.TemporaryFile(mode="w+") as stderr_file:
        process = subprocess.Popen(
            COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr_file,
            text=True,
            bufsize=1,
        )
        try:
            send_message(
                process,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "clientInfo": {"name": "mcp-check", "version": "1.0.0"},
                    },
                },
            )
            initialized = read_response(process, 1, "initialize")
            server_info = initialized.get("serverInfo")
            if not isinstance(server_info, dict):
                raise CheckError("initialize result has no serverInfo object")
            print(
                f"Server: {server_info.get('name', 'unknown')} "
                f"{server_info.get('version', '?')}"
            )

            send_message(
                process,
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
            )

            tool_names = []
            cursor = None
            request_id = 2
            seen_cursors = set()
            while True:
                request = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "tools/list",
                }
                if cursor is not None:
                    request["params"] = {"cursor": cursor}
                send_message(process, request)
                result = read_response(process, request_id, "tools/list")
                tools = result.get("tools")
                if not isinstance(tools, list) or not all(
                    isinstance(tool, dict) and isinstance(tool.get("name"), str)
                    for tool in tools
                ):
                    raise CheckError("tools/list result contains an invalid tools array")
                tool_names.extend(tool["name"] for tool in tools)
                cursor = result.get("nextCursor")
                if cursor is None:
                    break
                if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                    raise CheckError(f"tools/list returned an invalid cursor: {cursor!r}")
                seen_cursors.add(cursor)
                request_id += 1

            print(f"Tools ({len(tool_names)}): {', '.join(tool_names)}")
            if "agent_browser_open" not in tool_names:
                raise CheckError("agent_browser_open is not in the core tool list")
            print("PASS: agent_browser_open is available")
        except (BrokenPipeError, CheckError) as error:
            print(f"FAIL: {error}", file=sys.stderr)
            captured = stderr_text(stderr_file)
            if captured:
                print(f"MCP server stderr:\n{captured}", file=sys.stderr)
            return 1
        finally:
            if process.stdin is not None:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return 0


if __name__ == "__main__":
    sys.exit(main())
