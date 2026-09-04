"""One-shot connectivity probes for privacy-bounded support bundles."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import aiohttp
import pytest
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.support_bundle import connectivity_http_outcome, connectivity_probe_result
from yarl import URL


class _ResponseContext:
    def __init__(self, status: int) -> None:
        self.status = status
        self.exited = False
        self.body_read = False

    async def __aenter__(self) -> _ResponseContext:
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.exited = True

    async def read(self) -> bytes:
        self.body_read = True
        return b"private-response-canary"

    async def text(self) -> str:
        self.body_read = True
        return "private-response-canary"

    async def json(self) -> dict[str, str]:
        self.body_read = True
        return {"private": "response-canary"}


class _RaisingContext:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def __aenter__(self) -> None:
        raise self.error

    async def __aexit__(self, *_args: object) -> None:
        return None


class _BlockingContext:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def __aenter__(self) -> None:
        self.entered.set()
        await asyncio.Future()

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def __init__(self, context: Any) -> None:
        self.closed = False
        self.context = context
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def request(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        return self.context


def test_connectivity_result_uses_only_fixed_status_and_duration_vocabularies() -> None:
    assert connectivity_http_outcome(200) == "success"
    assert connectivity_http_outcome(401) == "authentication"
    assert connectivity_http_outcome(403) == "permission"
    assert connectivity_http_outcome(500) == "unknown"
    assert connectivity_probe_result("success", 99).model_dump(mode="json") == {
        "probe": "connectivity",
        "status": "available",
        "duration_bucket": "under_100ms",
        "outcome": "success",
    }
    assert connectivity_probe_result("timeout", 5_000).duration_bucket == "over_5s"
    assert connectivity_probe_result("connection", None).duration_bucket == "unknown"


@pytest.mark.asyncio
async def test_network_probe_uses_existing_session_once_without_reconnect() -> None:
    context = _ResponseContext(200)
    session = _Session(context)
    manager = ConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._initialized = True
    manager._aiohttp_session = session
    manager._unifi_os_override = True
    manager.controller = SimpleNamespace(connectivity=SimpleNamespace(is_unifi_os=True))
    manager.initialize = AsyncMock()

    result = await manager.support_connectivity_probe()

    assert result.outcome == "success"
    assert len(session.calls) == 1
    assert session.calls[0][0][1].endswith("/proxy/network/api/self/sites")
    assert session.calls[0][1]["timeout"].total == 10
    assert session.calls[0][1]["allow_redirects"] is False
    assert context.exited is True
    manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_protect_probe_uses_existing_private_session_without_sdk_retry() -> None:
    context = _ResponseContext(403)
    session = _Session(context)
    manager = ProtectConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._initialized = True
    manager._client = SimpleNamespace(
        _session=session,
        _url=URL("https://controller.example.invalid:443"),
        headers={"X-CSRF-Token": "private-token"},
    )
    manager.initialize = AsyncMock()

    result = await manager.support_connectivity_probe()

    assert result.outcome == "permission"
    assert len(session.calls) == 1
    assert str(session.calls[0][0][1]).endswith("/proxy/protect/api/nvr")
    assert session.calls[0][1]["timeout"].total == 10
    manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_probe_prefers_existing_developer_session_and_never_reauthenticates() -> None:
    context = _ResponseContext(401)
    session = _Session(context)
    manager = AccessConnectionManager(
        "controller.example.invalid",
        "private-user",
        "private-password",
        api_key="private-token",
    )
    manager._initialized = True
    manager._api_client_available = True
    manager._api_client = object()
    manager._api_session = session
    manager._proxy_available = True
    manager._proxy_session = _Session(_ResponseContext(200))
    manager._proxy_login = AsyncMock()
    manager.initialize = AsyncMock()

    result = await manager.support_connectivity_probe()

    assert result.outcome == "authentication"
    assert len(session.calls) == 1
    assert session.calls[0][0][1].endswith("/api/v1/developer/doors/settings/emergency")
    assert session.calls[0][1]["timeout"].total == 10
    assert context.body_read is False
    manager._proxy_login.assert_not_awaited()
    manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_probe_failure_logs_only_fixed_audit_fields(caplog: pytest.LogCaptureFixture) -> None:
    canary = "private-user private-password https://controller.example.invalid"
    session = _Session(_RaisingContext(aiohttp.ClientConnectionError(canary)))
    manager = ConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._initialized = True
    manager._aiohttp_session = session
    manager.controller = SimpleNamespace(connectivity=SimpleNamespace(is_unifi_os=False))

    with caplog.at_level(logging.INFO):
        result = await manager.support_connectivity_probe()

    assert result.outcome == "connection"
    assert canary not in caplog.text
    assert "private-user" not in caplog.text
    assert "private-password" not in caplog.text
    assert "Support connectivity audit product=network outcome=connection" in caplog.text


@pytest.mark.asyncio
async def test_native_request_timeout_is_reduced_without_retry() -> None:
    session = _Session(_RaisingContext(asyncio.TimeoutError("private timeout detail")))
    manager = ConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._initialized = True
    manager._aiohttp_session = session
    manager.controller = SimpleNamespace(connectivity=SimpleNamespace(is_unifi_os=False))

    result = await manager.support_connectivity_probe()

    assert result.outcome == "timeout"
    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_cancellation_propagates_without_closing_or_replacing_shared_session() -> None:
    context = _BlockingContext()
    session = _Session(context)
    manager = ConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._initialized = True
    manager._aiohttp_session = session
    manager.controller = SimpleNamespace(connectivity=SimpleNamespace(is_unifi_os=False))

    task = asyncio.create_task(manager.support_connectivity_probe())
    await context.entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.done()
    assert manager._aiohttp_session is session
    assert session.closed is False
