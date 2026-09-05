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
from unifi_core.support_transport import no_retry_support_request
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
@pytest.mark.parametrize("verify_ssl", [False, True])
@pytest.mark.parametrize("is_unifi_os", [False, True])
async def test_network_probe_uses_existing_session_once_without_reconnect(verify_ssl: bool, is_unifi_os: bool) -> None:
    context = _ResponseContext(200)
    session = _Session(context)
    manager = ConnectionManager("controller.example.invalid", "private-user", "private-password", verify_ssl=verify_ssl)
    manager._initialized = True
    manager._aiohttp_session = session
    manager._unifi_os_override = is_unifi_os
    manager.controller = SimpleNamespace(connectivity=SimpleNamespace(is_unifi_os=is_unifi_os))
    manager.initialize = AsyncMock()

    result = await manager.support_connectivity_probe()

    assert result.outcome == "success"
    assert len(session.calls) == 1
    path = "/proxy/network/api/self/sites" if is_unifi_os else "/api/self/sites"
    assert session.calls[0][0][1] == f"{manager.url_base}{path}"
    assert session.calls[0][1]["timeout"].total == 10
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["ssl"] is (None if verify_ssl else False)
    assert context.exited is True
    assert context.body_read is False
    manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("verify_ssl", [False, True])
async def test_protect_probe_uses_existing_private_session_without_sdk_retry(verify_ssl: bool) -> None:
    context = _ResponseContext(403)
    session = _Session(context)
    manager = ProtectConnectionManager(
        "controller.example.invalid", "private-user", "private-password", verify_ssl=verify_ssl
    )
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
    assert session.calls[0][1]["headers"] == {"X-CSRF-Token": "private-token"}
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["ssl"] is (None if verify_ssl else False)
    assert context.body_read is False
    assert context.exited is True
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
    assert session.calls[0][1]["headers"] == {"Authorization": "Bearer private-token", "Accept": "application/json"}
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["ssl"] is manager._ssl_context
    assert manager._proxy_session.calls == []
    assert context.body_read is False
    assert context.exited is True
    manager._proxy_login.assert_not_awaited()
    manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_access_probe_uses_existing_proxy_session_without_reading_body_or_reauthenticating() -> None:
    context = _ResponseContext(200)
    session = _Session(context)
    manager = AccessConnectionManager("controller.example.invalid", "private-user", "private-password")
    manager._initialized = True
    manager._proxy_available = True
    manager._proxy_session = session
    manager._csrf_token = "private-csrf-token"
    manager._proxy_login = AsyncMock()
    manager.initialize = AsyncMock()

    result = await manager.support_connectivity_probe()

    assert result.outcome == "success"
    assert len(session.calls) == 1
    assert session.calls[0][0][1].endswith("/proxy/access/api/v2/access/info")
    assert session.calls[0][1]["headers"] == {"X-CSRF-Token": "private-csrf-token"}
    assert session.calls[0][1]["timeout"].total == 10
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["ssl"] is manager._ssl_context
    assert context.body_read is False
    manager._proxy_login.assert_not_awaited()
    manager.initialize.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_probe_paths_emit_fixed_audit_events(caplog: pytest.LogCaptureFixture) -> None:
    managers = (
        ("network", ConnectionManager("controller.example.invalid", "private-user", "private-password")),
        ("protect", ProtectConnectionManager("controller.example.invalid", "private-user", "private-password")),
        ("access", AccessConnectionManager("controller.example.invalid", "private-user", "private-password")),
    )

    with caplog.at_level(logging.INFO):
        for product, manager in managers:
            result = await manager.support_connectivity_probe()
            assert result.outcome == "connection"
            assert result.duration_bucket == "unknown"
            assert f"Support connectivity audit product={product} outcome=connection duration=unknown" in caplog.text

    assert "private-user" not in caplog.text
    assert "private-password" not in caplog.text
    assert "controller.example.invalid" not in caplog.text


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


@pytest.mark.asyncio
@pytest.mark.parametrize("product", ["network", "protect", "access_developer", "access_proxy"])
@pytest.mark.parametrize("use_probe_middleware", [False, True])
async def test_aiohttp_stale_connection_has_one_wire_attempt_for_support_only(
    product: str, use_probe_middleware: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise real aiohttp retry logic, not a fake session's request count."""
    attempts = 0
    warm_writer: asyncio.StreamWriter | None = None
    probe_writers: list[asyncio.StreamWriter] = []
    handlers: set[asyncio.Task[None]] = set()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal attempts, warm_writer
        task = asyncio.current_task()
        assert task is not None
        handlers.add(task)
        try:
            while True:
                headers = await reader.readuntil(b"\r\n\r\n")
                path = headers.split(b" ", 2)[1]
                if path == b"/warm":
                    warm_writer = writer
                else:
                    attempts += 1
                    probe_writers.append(writer)
                    if attempts == 1:
                        # Drop the reused connection after receiving the GET.
                        break
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    try:
        async with server, aiohttp.ClientSession() as session:
            real_request = session.request

            def local_request(method: str, url: Any, **kwargs: Any) -> Any:
                # Redirect only the test transport to loopback; retain the actual
                # manager request options and aiohttp's complete request loop.
                if not use_probe_middleware:
                    kwargs.pop("middlewares", None)
                return real_request(method, f"{base}{URL(url).path}", **kwargs)

            monkeypatch.setattr(session, "request", local_request)
            if product == "network":
                manager = ConnectionManager("controller.example.invalid", "user", "password")
                manager._aiohttp_session = session
                manager.controller = SimpleNamespace(connectivity=SimpleNamespace(is_unifi_os=False))
            elif product == "protect":
                manager = ProtectConnectionManager("controller.example.invalid", "user", "password")
                manager._client = SimpleNamespace(_session=session, _url=URL(base), headers={})
            else:
                manager = AccessConnectionManager("controller.example.invalid", "user", "password")
                if product == "access_developer":
                    manager._api_client_available = True
                    manager._api_client = object()
                    manager._api_session = session
                else:
                    manager._proxy_available = True
                    manager._proxy_session = session
            manager._initialized = True
            warm_ssl = manager._ssl_context if product.startswith("access") else False
            async with session.get(f"{base}/warm", ssl=warm_ssl) as response:
                await response.read()
            result = await manager.support_connectivity_probe()

            assert probe_writers[0] is warm_writer
            assert attempts == (1 if use_probe_middleware else 2)
            assert result.outcome == ("connection" if use_probe_middleware else "success")
            assert not session.closed
            # The same session remains usable for ordinary controller calls.
            async with session.get(f"{base}/ordinary") as response:
                assert response.status == 200
    finally:
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.gather(*handlers)


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [aiohttp.ClientOSError, aiohttp.ServerDisconnectedError])
async def test_support_transport_reduces_retryable_errors_without_copying_details(error_type: type[Exception]) -> None:
    handler = AsyncMock(side_effect=error_type("private transport canary"))
    request = object()

    with pytest.raises(aiohttp.ClientConnectionError) as caught:
        await no_retry_support_request(request, handler)

    assert type(caught.value) is aiohttp.ClientConnectionError
    assert str(caught.value) == "Support connectivity transport failed"
    assert caught.value.__suppress_context__ is True
    handler.assert_awaited_once_with(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.CancelledError(), asyncio.TimeoutError()])
async def test_support_transport_preserves_cancellation_and_timeout(error: BaseException) -> None:
    with pytest.raises(type(error)) as caught:
        await no_retry_support_request(object(), AsyncMock(side_effect=error))
    assert caught.value is error
