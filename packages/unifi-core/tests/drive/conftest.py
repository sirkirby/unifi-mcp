"""A loopback stand-in for a UniFi Drive console."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from unifi_core.drive.managers.connection_manager import DriveConnectionManager

USERNAME = "synthetic-user"
PASSWORD = "synthetic-password-0123456789"
CSRF = "csrf-1"
HOST = "192.0.2.10"


@dataclass
class Recorded:
    method: str
    path: str
    headers: dict[str, str]
    body: Any


@dataclass
class StubConsole:
    """Scripted responses per ``(method, path)``; logins succeed unless scripted otherwise."""

    base_url: str = ""
    requests: list[Recorded] = field(default_factory=list)
    _scripts: dict[tuple[str, str], deque] = field(default_factory=lambda: defaultdict(deque))
    _sticky: dict[tuple[str, str], tuple] = field(default_factory=dict)

    def reply(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        always: bool = False,
    ) -> None:
        entry = (status, payload, headers or {})
        if always:
            self._sticky[(method, path)] = entry
        else:
            self._scripts[(method, path)].append(entry)

    def calls(self, method: str, path: str | None = None) -> list[Recorded]:
        return [r for r in self.requests if r.method == method and (path is None or r.path == path)]

    @property
    def writes(self) -> list[Recorded]:
        return [
            r for r in self.requests if r.method in ("PUT", "POST", "DELETE") and not r.path.startswith("/api/auth")
        ]

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else None
        path = request.raw_path.split("?")[0]
        self.requests.append(Recorded(request.method, path, dict(request.headers), body))
        key = (request.method, path)
        if self._scripts[key]:
            status, payload, headers = self._scripts[key].popleft()
        elif key in self._sticky:
            status, payload, headers = self._sticky[key]
        elif key == ("POST", "/api/auth/login"):
            status, payload, headers = (
                200,
                {"username": USERNAME},
                {"x-csrf-token": CSRF, "Set-Cookie": "TOKEN=t; Path=/"},
            )
        elif key == ("POST", "/api/auth/logout"):
            status, payload, headers = 200, {}, {}
        else:
            return web.json_response({"err": {"msg": "unscripted"}}, status=599)
        if payload is None:
            return web.Response(status=status, headers=headers)
        return web.json_response(payload, status=status, headers=headers)


@pytest.fixture
async def console():
    stub = StubConsole()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stub.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    yield stub
    await server.close()


@pytest.fixture
async def connection(console):
    manager = DriveConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url, tls_env_prefix="DRIVE")
    yield manager
    await manager.close()
