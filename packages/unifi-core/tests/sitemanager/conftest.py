"""A loopback stand-in for the Site Manager API."""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from unifi_core.sitemanager.managers.connection_manager import SiteManagerConnectionManager

KEY = "synthetic-site-manager-key-0123456789"


@dataclass
class Recorded:
    method: str
    path: str
    query: list[tuple[str, str]]
    headers: dict[str, str]
    body: Any


@dataclass
class StubApi:
    """Scripted responses per ``(method, path)`` and a record of what arrived."""

    base_url: str = ""
    requests: list[Recorded] = field(default_factory=list)
    _scripts: dict[tuple[str, str], deque] = field(default_factory=lambda: defaultdict(deque))

    def reply(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
    ) -> None:
        self._scripts[(method, path)].append((status, payload, headers or {}, delay))

    def calls(self, method: str, path: str) -> list[Recorded]:
        return [request for request in self.requests if (request.method, request.path) == (method, path)]

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else None
        self.requests.append(
            Recorded(
                request.method, request.raw_path.split("?")[0], list(request.query.items()), dict(request.headers), body
            )
        )
        script = self._scripts[(request.method, request.raw_path.split("?")[0])]
        if not script:
            return web.json_response({"code": "UNSCRIPTED"}, status=599)
        status, payload, headers, delay = script.popleft()
        if delay:
            await asyncio.sleep(delay)
        if payload is None:
            return web.Response(status=status, headers=headers)
        return web.json_response(payload, status=status, headers=headers)


@pytest.fixture
async def api():
    stub = StubApi()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stub.handle)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    yield stub
    await server.close()


@pytest.fixture
async def connection(api):
    manager = SiteManagerConnectionManager(KEY, base_url=api.base_url, rate_limit_wait_seconds=5)
    yield manager
    await manager.close()
