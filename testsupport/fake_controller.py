"""Loopback controller fakes for startup and reconnect tests. Test-only; no package ships it.

* :class:`FakeController` speaks just enough of the Network, Protect and
  Access login and read APIs for the real SDKs to connect and decode an empty
  inventory, over local TLS. A login can be held open, rejected or counted.
* :class:`SilentPort` accepts TCP connections and never answers, like a
  controller whose service hangs.
* :func:`closed_port` returns a loopback port with nothing listening.
* :func:`run_stdio_server` starts an app as an MCP stdio server in a subprocess
  pointed at a loopback port and drives it as a client, timing each reply.

Every address is loopback; credentials are obviously fake.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import ipaddress
import json
import os
import queue
import socket
import ssl
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

FAKE_USERNAME = "fake-user"
FAKE_PASSWORD = "fake-password-for-tests"

_PROTECT_BOOTSTRAP = {
    "authUserId": "fake-user-id",
    "accessKey": "fake-access-key",
    "lastUpdateId": "fake-update",
    "nvr": {
        "id": "fake-nvr",
        "modelKey": "nvr",
        "type": "UNVR",
        "firmwareVersion": "1.0.0",
        "mac": "02:00:00:00:00:01",
        "version": "5.0.0",
        "timezone": "UTC",
        "hosts": ["127.0.0.1"],
        "ports": {"rtsp": 7447, "rtsps": 7441},
        "isUpdating": False,
        "storageStats": {
            "utilization": 50,
            "recordingSpace": {"total": 2048, "used": 1024, "available": 1024},
            "capacity": 86400000,
            "remainingCapacity": 43200000,
        },
        "systemInfo": {
            "cpu": {"averageLoad": 0.1, "temperature": 30},
            "memory": {"available": 1024, "free": 512, "total": 2048},
            "storage": {"available": 1024, "size": 2048, "used": 1024, "type": "hdd", "isRecycling": False},
        },
    },
    **{
        key: []
        for key in (
            "cameras",
            "users",
            "groups",
            "liveviews",
            "viewers",
            "lights",
            "sensors",
            "chimes",
            "bridges",
            "ringtones",
            "aiports",
        )
    },
}


def tls_context(directory: Path) -> ssl.SSLContext:
    """A server TLS context with a throwaway self-signed certificate for 127.0.0.1."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "loopback-fake-controller")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "fake-cert.pem", directory / "fake-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(cert_path, key_path)
    return context


class FakeController:
    """An aiohttp app that answers one product's login and empty inventory reads.

    ``login_status`` other than 200 rejects every login. Clear ``release`` to
    hold logins open until it is set; ``login_started`` is set when one arrives.
    ``network_rows`` maps a Network path suffix (``"/stat/sta"``) to the rows
    that read returns instead of none.
    """

    def __init__(
        self, product: str, *, login_status: int = 200, network_rows: dict[str, list[dict[str, Any]]] | None = None
    ) -> None:
        from aiohttp import web

        self.product = product
        self.login_status = login_status
        self.network_rows = network_rows or {}
        self.login_started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.seen: list[str] = []
        self.app = web.Application()
        self.app.router.add_route("*", "/{tail:.*}", self._handle)
        self._server: Any = None

    @property
    def logins(self) -> int:
        return sum(1 for path in self.seen if path in ("/api/auth/login", "/api/login"))

    async def start(self, port: int, directory: Path) -> None:
        """Serve over TLS on 127.0.0.1:``port``."""
        from aiohttp.test_utils import TestServer

        self._server = TestServer(self.app, host="127.0.0.1", port=port)
        await self._server.start_server(ssl=tls_context(directory))

    async def close(self) -> None:
        self.release.set()
        if self._server is not None:
            await self._server.close()

    async def _handle(self, request):
        from aiohttp import web

        path = request.path
        self.seen.append(path)
        if path in ("/api/auth/login", "/api/login"):
            self.login_started.set()
            await self.release.wait()
            if self.login_status != 200:
                return web.json_response({"meta": {"rc": "error", "msg": "api.err.Invalid"}}, status=self.login_status)
            response = web.json_response({"unique_id": "fake-user-id", "meta": {"rc": "ok"}, "data": []})
            response.set_cookie("TOKEN", self._session_token())
            response.headers["x-csrf-token"] = "fake-csrf"
            return response
        if self.product == "protect":
            if path.endswith("/bootstrap"):
                return web.json_response(_PROTECT_BOOTSTRAP)
            return web.json_response([])
        if self.product == "access":
            return web.json_response({"code": 1, "msg": "success", "data": {"locations": []}})
        # Network, as a standalone (non-UniFi OS) controller.
        if path == "/":
            return web.Response(status=302, headers={"Location": "/manage"})
        rows = next((rows for suffix, rows in self.network_rows.items() if path.endswith(suffix)), [])
        return web.json_response({"meta": {"rc": "ok"}, "data": rows})

    def _session_token(self) -> str:
        if self.product != "protect":
            return "fake-session"
        import jwt

        return jwt.encode({"exp": time.time() + 3600}, "fake-signing-key-with-32-characters!", algorithm="HS256")


class SilentPort:
    """A loopback port that accepts TCP connections and never answers."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(64)
        self.port = self._sock.getsockname()[1]
        self._held: list[socket.socket] = []
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        self._sock.settimeout(0.2)
        while not self._closed.is_set():
            try:
                conn, _ = self._sock.accept()
            except (TimeoutError, OSError):
                continue
            self._held.append(conn)

    @property
    def connections(self) -> int:
        return len(self._held)

    def close(self) -> None:
        self._closed.set()
        self._thread.join(timeout=2)
        for conn in self._held:
            conn.close()
        self._sock.close()

    def __enter__(self) -> SilentPort:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def closed_port() -> int:
    """A loopback port with nothing listening on it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


_STDIO_PROBE = """\
import sys

import {module}.main as m

# Shorten the waits so the test runs in seconds; the behaviour is unchanged.
m.connection_manager._attempt.wait_seconds = {wait_seconds!r}
for name in ("unifi_core.network.managers.connection_manager",
             "unifi_core.protect.managers.connection_manager",
             "unifi_core.access.managers.connection_manager"):
    module = sys.modules.get(name)
    if module is not None and hasattr(module, "RetryPolicy"):
        policy = module.RetryPolicy
        module.RetryPolicy = lambda _policy=policy, **kw: _policy(**{{**kw, "base_delay": 0.0, "max_delay": 0.0}})
if hasattr(m.connection_manager, "_retry_delay"):
    m.connection_manager._retry_delay = 0
m.main()
"""


def run_stdio_server(
    tmp_path: Path,
    *,
    module: str,
    env_prefix: str,
    port: int,
    tool: str,
    wait_seconds: float,
    ready_marker: str = "in the background",
    before_call: float = 0.0,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run ``module`` over stdio against 127.0.0.1:``port`` and drive it as an MCP client.

    Waits until the server logs that it is connecting in the background (the
    process is ready), then sends ``initialize``, ``tools/list`` and one
    ``tools/call`` of ``tool`` with ``arguments``. Returns the replies and how long each took.
    The environment carries no inherited ``UNIFI_*`` variable.
    """
    probe = tmp_path / "stdio_probe.py"
    probe.write_text(_STDIO_PROBE.format(module=module, wait_seconds=wait_seconds), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_") and k != "CONFIG_PATH"}
    env.update(
        {
            f"UNIFI_{env_prefix}_HOST": "127.0.0.1",
            f"UNIFI_{env_prefix}_PORT": str(port),
            f"UNIFI_{env_prefix}_USERNAME": FAKE_USERNAME,
            f"UNIFI_{env_prefix}_PASSWORD": FAKE_PASSWORD,
            f"UNIFI_{env_prefix}_VERIFY_SSL": "false",
        }
    )
    started = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, str(probe)],
        cwd=tmp_path,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    replies: queue.Queue[str | None] = queue.Queue()
    stderr_lines: list[str] = []
    ready = threading.Event()

    def _read_stdout() -> None:
        for line in proc.stdout:
            replies.put(line)
        replies.put(None)

    def _read_stderr() -> None:
        for line in proc.stderr:
            stderr_lines.append(line)
            if ready_marker in line:
                ready.set()

    threading.Thread(target=_read_stdout, daemon=True).start()
    threading.Thread(target=_read_stderr, daemon=True).start()

    def request(msg_id: int, method: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], float]:
        sent = time.monotonic()
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}) + "\n")
        proc.stdin.flush()
        while True:
            line = replies.get(timeout=60)
            assert line is not None, f"server exited before answering {method}: {''.join(stderr_lines)[-2000:]}"
            reply = json.loads(line)
            if reply.get("id") == msg_id:
                assert "error" not in reply, reply
                return reply["result"], time.monotonic() - sent

    try:
        assert ready.wait(timeout=60), f"server never became ready: {''.join(stderr_lines)[-2000:]}"
        ready_after = time.monotonic() - started
        init, init_seconds = request(
            1,
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "probe", "version": "0"}},
        )
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        tools, list_seconds = request(2, "tools/list")
        if before_call:
            time.sleep(before_call)
        call, call_seconds = request(3, "tools/call", {"name": tool, "arguments": arguments or {}})
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return {
        "ready_after": ready_after,
        "initialize": init,
        "initialize_seconds": init_seconds,
        "tools": [entry["name"] for entry in tools["tools"]],
        "listed": tools["tools"],
        "list_seconds": list_seconds,
        "call": call,
        "call_seconds": call_seconds,
        "stderr": "".join(stderr_lines),
    }


def tool_payload(call_result: dict[str, Any]) -> dict[str, Any]:
    """The tool's response dict from a ``tools/call`` result."""
    structured = call_result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    return json.loads(call_result["content"][0]["text"])
