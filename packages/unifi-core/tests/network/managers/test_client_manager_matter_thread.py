"""``ClientManager.get_matter_thread_clients``.

Thread end devices are absent from ``/stat/sta`` and ``/rest/user``; the
Network UI reads them from the V2 active-client list with
``includeMatterThreadClients=true``. The manager keeps only the
``MATTER_THREAD`` records from that response.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.models.api import ApiRequestV2
from unifi_core.network.managers.client_manager import (
    MATTER_THREAD_ACTIVE_CLIENTS_PATH,
    ClientManager,
)

THREAD_RECORD = {"type": "MATTER_THREAD", "id": "abc1234", "name": "Smart Plug", "channel": 25}
WIRED_RECORD = {"type": "WIRED", "mac": "aa:bb:cc:00:00:01", "is_wired": True}
WIRELESS_RECORD = {"type": "WIRELESS", "mac": "aa:bb:cc:00:00:02", "is_wired": False}


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(return_value=None)
    return conn


@pytest.mark.asyncio
async def test_returns_only_matter_thread_records_from_v2_active_list(mock_connection):
    mock_connection.request = AsyncMock(return_value=[WIRED_RECORD, THREAD_RECORD, WIRELESS_RECORD])

    result = await ClientManager(mock_connection).get_matter_thread_clients()

    assert result == [{"type": "MATTER_THREAD", "id": "abc1234", "name": "Smart Plug", "channel": 25}]
    mock_connection.request.assert_awaited_once()
    request = mock_connection.request.await_args.args[0]
    assert isinstance(request, ApiRequestV2)
    assert request.method == "get"
    assert request.path == MATTER_THREAD_ACTIVE_CLIENTS_PATH
    assert "includeMatterThreadClients=true" in request.path
    mock_connection._update_cache.assert_called_once_with("clients_matter_thread_default", result)


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"data": [THREAD_RECORD]}, [WIRED_RECORD]])
async def test_undecodable_or_thread_free_response_is_empty(mock_connection, response):
    mock_connection.request = AsyncMock(return_value=response)

    assert await ClientManager(mock_connection).get_matter_thread_clients() == []


@pytest.mark.asyncio
async def test_cached_result_skips_request(mock_connection):
    cached = [{"type": "MATTER_THREAD", "id": "cached1"}]
    mock_connection.get_cached = MagicMock(return_value=cached)

    assert await ClientManager(mock_connection).get_matter_thread_clients() == [
        {"type": "MATTER_THREAD", "id": "cached1"}
    ]
    mock_connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_not_connected_raises(mock_connection):
    mock_connection.ensure_connected = AsyncMock(return_value=False)

    with pytest.raises(ConnectionError):
        await ClientManager(mock_connection).get_matter_thread_clients()
    mock_connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_failure_propagates(mock_connection):
    mock_connection.request = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await ClientManager(mock_connection).get_matter_thread_clients()
    mock_connection._update_cache.assert_not_called()
