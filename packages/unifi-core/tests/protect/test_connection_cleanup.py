"""Failed bootstrap attempts must release their SDK clients before retrying."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.protect.managers import connection_manager as module


@pytest.mark.asyncio
async def test_failed_retries_close_every_client(monkeypatch):
    clients = [MagicMock() for _ in range(3)]
    for client in clients:
        client.update = AsyncMock(side_effect=RuntimeError("bootstrap failed"))
        client.async_disconnect_ws = AsyncMock()
        client.close_session = AsyncMock()
    monkeypatch.setattr(module, "ProtectApiClient", MagicMock(side_effect=clients))

    async def retry(call, **kwargs):
        for _ in range(3):
            try:
                await call()
            except RuntimeError:
                continue
        raise RuntimeError("retries exhausted")

    monkeypatch.setattr(module, "retry_with_backoff", retry)
    manager = module.ProtectConnectionManager(host="controller.invalid", username="test", password="test")
    assert await manager.initialize() is False
    assert manager._client is None
    for client in clients:
        client.async_disconnect_ws.assert_awaited_once()
        client.close_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_bootstrap_closes_client_and_fails_the_attempt(monkeypatch):
    # The connect runs as the manager's shared attempt: cancelling it ends that
    # attempt, and the caller waiting on it sees a failed connect.
    client = MagicMock()
    client.update = AsyncMock(side_effect=asyncio.CancelledError())
    client.async_disconnect_ws = AsyncMock()
    client.close_session = AsyncMock()
    monkeypatch.setattr(module, "ProtectApiClient", MagicMock(return_value=client))
    manager = module.ProtectConnectionManager(host="controller.invalid", username="test", password="test")
    assert await manager.initialize() is False
    client.async_disconnect_ws.assert_awaited_once()
    client.close_session.assert_awaited_once()
    assert manager._client is None
