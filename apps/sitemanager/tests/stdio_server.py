"""Run the server as a real stdio process and drive it as an MCP client.

The process refuses every socket connection and name lookup, and records any
attempt in a marker file, so a test can assert the server made no request.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PROBE = """\
import socket, sys

def _refuse(what):
    def refused(*args, **kwargs):
        with open({marker!r}, "a", encoding="utf-8") as handle:
            handle.write(what + "\\n")
        raise OSError("test: network access refused")
    return refused

socket.socket.connect = _refuse("connect")
socket.socket.connect_ex = _refuse("connect_ex")
socket.getaddrinfo = _refuse("getaddrinfo")

from unifi_sitemanager_mcp.main import main

main()
"""


@dataclass
class StdioRun:
    instructions: str
    server_name: str
    tools: list[dict[str, Any]]
    calls: list[dict[str, Any]]
    stderr: str
    returncode: int
    network_attempts: str

    @property
    def tool_names(self) -> set[str]:
        return {tool["name"] for tool in self.tools}


def run_server(tmp_path: Path, env: dict[str, str], *, calls: tuple[tuple[str, dict[str, Any]], ...] = ()) -> StdioRun:
    """Start the server with exactly ``env`` for its UniFi settings and list its tools."""
    marker = tmp_path / "network-attempts"
    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE.format(marker=str(marker)), encoding="utf-8")
    process_env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_") and k != "CONFIG_PATH"}
    process_env.update(env)
    proc = subprocess.Popen(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=process_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None
    replies: queue.Queue[str | None] = queue.Queue()

    def _read() -> None:
        for line in proc.stdout:
            replies.put(line)
        replies.put(None)

    threading.Thread(target=_read, daemon=True).start()

    def request(msg_id: int, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        while True:
            line = replies.get(timeout=60)
            assert line is not None, f"server exited before answering {method}"
            reply = json.loads(line)
            if reply.get("id") == msg_id:
                assert "error" not in reply, reply
                return reply["result"]

    try:
        init = request(
            1,
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}},
        )
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        tools = request(2, "tools/list")["tools"]
        results = [
            request(3 + index, "tools/call", {"name": name, "arguments": arguments})
            for index, (name, arguments) in enumerate(calls)
        ]
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return StdioRun(
        instructions=init.get("instructions") or "",
        server_name=init["serverInfo"]["name"],
        tools=tools,
        calls=results,
        stderr=proc.stderr.read() if proc.stderr else "",
        returncode=proc.returncode,
        network_attempts=marker.read_text() if marker.exists() else "",
    )
