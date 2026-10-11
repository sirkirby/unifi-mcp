"""Event managers over the SDKs' real decode path, answered from the shared controller fixture.

Only the HTTP exchange is replaced: each request is decoded by ``aiounifi``'s or
``uiprotect``'s own code, so API tests see the same per-source outcomes the Core
collectors produce against a controller.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
from uiprotect.api import ProtectApiClient
from uiprotect.exceptions import NotAuthorized, NvrError
from unifi_core.incident_evidence import parse_utc
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.event_manager import EventManager as NetworkEventManager
from unifi_core.protect.managers.event_manager import EventManager as ProtectEventManager

CORPUS_DIR = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "incident_evidence"
SCHEMA_PATH = CORPUS_DIR / "incident-evidence.v1.schema.json"
RESPONSES = json.loads((CORPUS_DIR / "collection" / "controller_responses.json").read_text())
SCHEMA = json.loads(SCHEMA_PATH.read_text())
NOW = parse_utc(RESPONSES["now"])
REQUEST = RESPONSES["request"]
PRIVATE = "fixture-private-controller-text"
PROTECT_URL = "https://controller.invalid/proxy/protect/api/events"


class FrozenDatetime(datetime):
    """Stands in for ``datetime`` in the collectors' clock so the fixture window is current."""

    @classmethod
    def now(cls, tz=None):  # noqa: D102
        return NOW


def sdk_network_events(*bodies: Any) -> NetworkEventManager:
    """Answer successive requests with ``bodies`` (the last one repeats); an exception body is raised."""
    connection = ConnectionManager("controller.invalid", "fixture-user", "fixture-password")
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.controller = MagicMock()
    remaining = list(bodies)

    async def transport(api_request: Any) -> Any:
        body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(body, BaseException):
            raise body
        return api_request.decode(json.dumps(body).encode())

    connection.controller.request = transport
    manager = NetworkEventManager(connection)
    manager._use_v2 = True
    return manager


def sdk_protect_events(*bodies: Any) -> ProtectEventManager:
    """Answer successive requests with ``bodies`` (the last one repeats); an exception body is raised."""
    client = ProtectApiClient("controller.invalid", 443, "fixture-user", "fixture-password", store_sessions=False)
    remaining = list(bodies)

    async def api_request_raw(url: str, method: str = "get", **kwargs: Any) -> bytes:
        body = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if isinstance(body, BaseException):
            raise body
        return json.dumps(body).encode()

    client.api_request_raw = api_request_raw  # type: ignore[method-assign]
    return ProtectEventManager(SimpleNamespace(client=client), {})


def _status_error(cls: type, status: int) -> BaseException:
    return cls(f"Request failed: {PROTECT_URL} - Status: {status} - Reason: {PRIVATE}")


def _network_body(response: Any) -> Any:
    if isinstance(response, dict) and "raise" in response:
        return {"timeout": asyncio.TimeoutError(), "unavailable": aiohttp.ClientConnectionError(PRIVATE)}[
            response["raise"]
        ]
    return response


def _protect_body(response: Any) -> Any:
    if isinstance(response, dict) and "raise" in response:
        return {
            "auth_failure": lambda: _status_error(NotAuthorized, 401),
            "permission_denied": lambda: _status_error(NotAuthorized, 403),
            "timeout": lambda: TimeoutError(),
            "unavailable": lambda: _status_error(NvrError, 503),
        }[response["raise"]]()
    return response


def network_scenario(name: str) -> NetworkEventManager:
    return sdk_network_events(*[_network_body(r) for r in RESPONSES["network"][name]["responses"]])


def protect_scenario(name: str) -> ProtectEventManager:
    return sdk_protect_events(*[_protect_body(r) for r in RESPONSES["protect"][name]["responses"]])


def network_page_rows(count: int) -> list[dict]:
    stamp = int(NOW.timestamp() * 1000) - 600_000
    return [{"id": f"evt-{i}", "key": "K", "timestamp": stamp - i} for i in range(count)]


def network_pages(count: int, total: int | None = None) -> list[dict]:
    rows = network_page_rows(count)
    return [{"data": rows[i : i + 100], "total_element_count": total or count} for i in range(0, count, 100)]


def protect_page_rows(count: int) -> list[dict]:
    start = int(NOW.timestamp() * 1000) - 3_000_000
    return [
        {"id": f"evt-{i}", "type": "motion", "camera": "cam-fixture-000a", "start": start + i} for i in range(count)
    ]
