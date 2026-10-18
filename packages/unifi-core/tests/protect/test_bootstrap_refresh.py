"""The bootstrap is re-fetched while the connection lives.

``initialize()`` fetched the bootstrap once and nothing fetched it again, so
every field the websocket does not push stayed at its value from connect
time. After a console's UniFi OS update and reboot, the NVR still read
``firmware_version`` of the old release, ``is_updating: true`` and the
previous ``up_since`` until the process restarted, while the console itself
reported the new version. A periodic ``client.update()`` (what Home
Assistant's Protect integration does) bounds that staleness.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.protect.managers import connection_manager as module


def _client():
    client = MagicMock()
    client.update = AsyncMock()
    client.async_disconnect_ws = AsyncMock()
    client.close_session = AsyncMock()
    return client


async def _connected(monkeypatch, client, **kwargs):
    monkeypatch.setattr(module, "ProtectApiClient", MagicMock(return_value=client))
    manager = module.ProtectConnectionManager(host="controller.invalid", username="u", password="p", **kwargs)
    assert await manager.initialize() is True
    return manager


async def _until_updates(client, count, timeout=5.0):
    """Wait for ``count`` bootstrap fetches without depending on scheduler speed."""

    async def _wait():
        while client.update.await_count < count:
            await asyncio.sleep(0.005)

    await asyncio.wait_for(_wait(), timeout)


@pytest.mark.asyncio
async def test_the_bootstrap_is_fetched_again_on_an_interval(monkeypatch):
    client = _client()
    manager = await _connected(monkeypatch, client, bootstrap_refresh_seconds=0.01)
    try:
        await _until_updates(client, 3)  # the connect fetch, then at least two refreshes
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_a_failed_refresh_keeps_the_connection_and_tries_again(monkeypatch):
    client = _client()
    manager = await _connected(monkeypatch, client, bootstrap_refresh_seconds=0.01)
    client.update.side_effect = RuntimeError("console rebooting")
    try:
        await _until_updates(client, 3)  # a failure does not end the refreshing
        assert manager._client is client and manager._initialized
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_close_stops_the_refreshing(monkeypatch):
    client = _client()
    manager = await _connected(monkeypatch, client, bootstrap_refresh_seconds=0.01)
    await manager.close()
    count = client.update.await_count
    await asyncio.sleep(0.05)
    assert client.update.await_count == count


@pytest.mark.asyncio
async def test_zero_turns_the_refreshing_off(monkeypatch):
    client = _client()
    manager = await _connected(monkeypatch, client, bootstrap_refresh_seconds=0)
    try:
        await asyncio.sleep(0.03)
        assert client.update.await_count == 1, "only the connect fetch"
    finally:
        await manager.close()


def test_the_default_interval_is_a_minute():
    manager = module.ProtectConnectionManager(host="controller.invalid", username="u", password="p")
    assert manager._bootstrap_refresh_seconds == 60.0


@pytest.mark.asyncio
async def test_close_cancels_in_flight_refresh_before_disposing_client(monkeypatch):
    client = _client()
    entered = asyncio.Event()
    cleanup_order = []

    async def update():
        if client.update.await_count == 1:
            return
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_order.append("refresh_cancelled")

    async def disconnect():
        cleanup_order.append("disconnect")

    async def close_session():
        cleanup_order.append("close_session")

    client.update.side_effect = update
    client.async_disconnect_ws.side_effect = disconnect
    client.close_session.side_effect = close_session
    manager = await _connected(monkeypatch, client, bootstrap_refresh_seconds=0.001)
    task = manager._refresh_task
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        await asyncio.wait_for(manager.close(), timeout=1)
        assert task.cancelled()
        assert manager._refresh_task is None
        assert cleanup_order == ["refresh_cancelled", "disconnect", "close_session"]
        assert manager._client is None
        assert not manager._initialized
    finally:
        await manager.close()
    client.async_disconnect_ws.assert_awaited_once()
    client.close_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_repeated_initialize_keeps_one_client_and_refresh_task(monkeypatch):
    client = _client()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(module, "ProtectApiClient", factory)
    manager = module.ProtectConnectionManager(host="controller.invalid", username="u", password="p")
    try:
        assert await manager.initialize()
        task = manager._refresh_task
        assert task is not None
        assert await manager.initialize()
        assert manager._refresh_task is task
        factory.assert_called_once()
        client.update.assert_awaited_once()
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_reinitialize_after_close_starts_fresh_client_and_task(monkeypatch):
    first, second = _client(), _client()
    factory = MagicMock(side_effect=[first, second])
    monkeypatch.setattr(module, "ProtectApiClient", factory)
    manager = module.ProtectConnectionManager(host="controller.invalid", username="u", password="p")
    try:
        assert await manager.initialize()
        first_task = manager._refresh_task
        assert first_task is not None
        await manager.close()
        assert first_task.done()
        assert await manager.initialize()
        assert manager._client is second
        assert manager._refresh_task is not None
        assert manager._refresh_task is not first_task
        assert not manager._refresh_task.done()
        assert factory.call_count == 2
        first.update.assert_awaited_once()
        second.update.assert_awaited_once()
        first.close_session.assert_awaited_once()
    finally:
        await manager.close()
    second.close_session.assert_awaited_once()
