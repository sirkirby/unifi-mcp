"""A loopback stand-in for a UniFi OS console serving InnerSpace.

Shared by the core and app tests; each test package's conftest imports the fixtures by name.

Plain HTTP on 127.0.0.1. Logins issue session ``N`` (cookie ``TOKEN=session-N``)
and a fresh CSRF token ``csrf-N``; any other route first checks both, the way
the console does, and answers an invalid session with 403 ``errors.api.access``
(or 401 when a test asks for it), except ``GET /api/system``, which answers a
missing or invalid session with 200 and a public payload without the app list,
as UniFi OS Server does on InnerSpace 1.4.3. Scripted replies are served after that check.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from unifi_core.innerspace.managers.connection_manager import SYSTEM_PATH, InnerSpaceConnectionManager

HOST = "192.0.2.10"
USERNAME = "synthetic-admin"
PASSWORD = "synthetic-password-0123456789"
LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"
ACCESS_DENIED = {"error": {"code": "errors.api.access", "errors": [], "message": "Headers missing", "type": "access"}}
# What /api/system serves without a valid session: console facts, no ``apps.controllers`` list, no cookie.
PUBLIC_SYSTEM = {"name": "Synthetic Console", "hardware": {"shortname": "SYNTH"}, "isSetup": True}


@dataclass
class Recorded:
    method: str
    path: str
    query: list[tuple[str, str]]
    headers: dict[str, str]
    body: Any


@dataclass
class StubConsole:
    """Scripted replies per ``(method, path)``, a session check, and a record of what arrived."""

    base_url: str = ""
    requests: list[Recorded] = field(default_factory=list)
    logins: int = 0
    held: int = 0
    streamed: int = 0
    stream_done: asyncio.Event = field(default_factory=asyncio.Event)
    _scripts: dict[tuple[str, str], deque] = field(default_factory=lambda: defaultdict(deque))
    _session: int = 0
    _sessions_issued: int = 0
    _expired_status: int | None = None
    _reject_logins: bool = False
    _hold_until: int = 0
    _release: asyncio.Event = field(default_factory=asyncio.Event)
    _csrf: str | None = None
    _token: str | None = None
    _login_gate: asyncio.Event | None = None
    login_arrived: asyncio.Event = field(default_factory=asyncio.Event)

    def reply(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
        body_bytes: bytes | None = None,
        stream: tuple[int, int] | None = None,
        declared: int | None = None,
        gate: tuple[asyncio.Event, asyncio.Event] | None = None,
    ) -> None:
        """``stream=(chunks, size)`` answers chunked, with no Content-Length, and counts bytes sent.

        ``declared`` sends a Content-Length of that many bytes and then no body at all.
        ``gate=(arrived, release)`` sets ``arrived`` when the request is in and answers once ``release`` is set.
        """
        self._scripts[(method, path)].append(
            (status, payload, headers or {}, delay, body_bytes, stream, declared, gate)
        )

    def redirect(self, path: str, location: str, *, method: str = "GET") -> None:
        self.reply(method, path, status=302, headers={"Location": location})

    def expire_session(self, status: int = 403) -> None:
        """Make the current session invalid; requests carrying it get ``status``."""
        self._session = 0
        self._expired_status = status

    def reject_logins(self, reject: bool = True) -> None:
        self._reject_logins = reject

    def hold_401_until(self, count: int) -> None:
        """Hold requests refused for their session until ``count`` of them arrived."""
        self._hold_until = count
        self._release = asyncio.Event()

    def rotate_token(self, value: str) -> None:
        """Accept ``value`` as the current session's TOKEN cookie from now on."""
        self._token = value

    def rotate_csrf(self, value: str) -> None:
        """Accept ``value`` as the current session's CSRF token from now on."""
        self._csrf = value

    def hold_logins(self) -> asyncio.Event:
        """Hold every login until the returned event is set; ``login_arrived`` is set when one arrives."""
        self._login_gate = asyncio.Event()
        return self._login_gate

    def calls(self, method: str, path: str) -> list[Recorded]:
        return [request for request in self.requests if (request.method, request.path) == (method, path)]

    async def handle(self, request: web.Request) -> web.StreamResponse:
        raw = await request.read()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        path = request.raw_path.split("?")[0]
        self.requests.append(Recorded(request.method, path, list(request.query.items()), dict(request.headers), body))
        script = self._scripts[(request.method, path)]
        if path == LOGIN:
            self.logins += 1
            if self._login_gate is not None:
                self.login_arrived.set()
                await self._login_gate.wait()
            if script:
                return await self._scripted(request, script)
            return self._login(body)
        if not self._session_valid(request):
            return await self._refuse_session(
                hold=path != LOGOUT, public=(request.method, path) == ("GET", SYSTEM_PATH)
            )
        if path == LOGOUT and not script:
            self._session = 0
            return web.json_response({})
        if not script:
            return web.json_response({"code": "UNSCRIPTED"}, status=599)
        return await self._scripted(request, script)

    async def _stream(
        self, request: web.Request, status: int, headers: dict[str, str], chunks: int, size: int
    ) -> web.StreamResponse:
        response = web.StreamResponse(status=status, headers=headers)
        response.enable_chunked_encoding()
        await response.prepare(request)
        try:
            for _ in range(chunks):
                await response.write(b"\x00" * size)
                self.streamed += size
        except ConnectionError:
            pass
        finally:
            self.stream_done.set()
        return response

    def _login(self, body: Any) -> web.Response:
        if self._reject_logins:
            # A console that echoes what it was sent: the client must never repeat it.
            return web.json_response({"error": {"code": "AUTHENTICATION_FAILED", "echo": body}}, status=401)
        self._sessions_issued += 1
        self._session = self._sessions_issued
        self._expired_status = None
        self._csrf = None
        self._token = None
        response = web.json_response({"unique_id": "synthetic-user"})
        response.set_cookie("TOKEN", f"session-{self._session}")
        response.headers["X-Csrf-Token"] = f"csrf-{self._session}"
        return response

    def _session_valid(self, request: web.Request) -> bool:
        return bool(self._session) and (
            request.cookies.get("TOKEN") == (self._token or f"session-{self._session}")
            and request.headers.get("X-CSRF-Token") == (self._csrf or f"csrf-{self._session}")
        )

    async def _refuse_session(self, *, hold: bool, public: bool = False) -> web.Response:
        status = self._expired_status or 403
        if hold and self._hold_until:
            self.held += 1
            if self.held >= self._hold_until:
                self._release.set()
            await self._release.wait()
        if public:
            return web.json_response(PUBLIC_SYSTEM)
        if status == 401:
            return web.json_response({"error": {"code": "errors.api.unauthorized"}}, status=401)
        return web.json_response(ACCESS_DENIED, status=status)

    async def _scripted(self, request: web.Request, script: deque) -> web.StreamResponse:
        status, payload, headers, delay, body_bytes, stream, declared, gate = script.popleft()
        if gate is not None:
            arrived, release = gate
            arrived.set()
            await release.wait()
        if delay:
            await asyncio.sleep(delay)
        if declared is not None:
            response = web.StreamResponse(status=status, headers=headers)
            response.content_length = declared
            await response.prepare(request)
            return response
        if stream:
            return await self._stream(request, status, headers, *stream)
        if body_bytes is not None:
            return web.Response(status=status, headers=headers, body=body_bytes)
        if payload is None:
            return web.Response(status=status, headers=headers)
        return web.json_response(payload, status=status, headers=headers)


async def start_stub(port: int | None = None) -> tuple[StubConsole, TestServer]:
    """Start the stub on a free loopback port, or on ``port`` (one a test found closed)."""
    stub = StubConsole()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stub.handle)
    server = TestServer(app, host="127.0.0.1", port=port)
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    return stub, server


@pytest.fixture
async def console():
    stub, server = await start_stub()
    yield stub
    await server.close()


@pytest.fixture
async def manager(console):
    cm = InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url)
    yield cm
    await cm.close()


@pytest.fixture
async def connected(manager):
    assert await manager.initialize() is True
    return manager
