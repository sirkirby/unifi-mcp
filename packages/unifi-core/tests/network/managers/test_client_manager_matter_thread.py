"""``ClientManager.get_matter_thread_clients``.

Thread end devices are absent from ``/stat/sta`` and ``/rest/user``; the
Network UI reads them from the V2 active-client list with
``includeMatterThreadClients=true``. The manager keeps only the
``MATTER_THREAD`` records from that response, requires a Network session, and
never lets controller text through its errors.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.models.api import ApiRequestV2
from unifi_core.exceptions import UniFiAuthError, UniFiOperationError
from unifi_core.network.managers.client_manager import (
    MATTER_THREAD_ACTIVE_CLIENTS_PATH,
    ClientManager,
)

THREAD_RECORD = {"type": "MATTER_THREAD", "id": "abc1234", "name": "Smart Plug", "channel": 25}
WIRED_RECORD = {"type": "WIRED", "mac": "aa:bb:cc:00:00:01", "is_wired": True}
WIRELESS_RECORD = {"type": "WIRELESS", "mac": "aa:bb:cc:00:00:02", "is_wired": False}
SENTINEL = "SENTINEL-Kitchen-Plug-fd00:db8::99"


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.ensure_session_connected = AsyncMock(return_value=True)
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
@pytest.mark.parametrize("response", [[], [WIRED_RECORD, WIRELESS_RECORD], ["not-a-record", None]])
async def test_valid_list_without_thread_records_is_empty_success(mock_connection, response):
    mock_connection.request = AsyncMock(return_value=response)

    assert await ClientManager(mock_connection).get_matter_thread_clients() == []
    mock_connection._update_cache.assert_called_once_with("clients_matter_thread_default", [])


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"data": [THREAD_RECORD]}, "unexpected"])
async def test_malformed_response_raises_and_is_not_cached(mock_connection, response):
    mock_connection.request = AsyncMock(return_value=response)

    with pytest.raises(UniFiOperationError, match="unexpected response shape"):
        await ClientManager(mock_connection).get_matter_thread_clients()
    mock_connection._update_cache.assert_not_called()


@pytest.mark.asyncio
async def test_cached_result_skips_request(mock_connection):
    cached = [{"type": "MATTER_THREAD", "id": "cached1"}]
    mock_connection.get_cached = MagicMock(return_value=cached)

    assert await ClientManager(mock_connection).get_matter_thread_clients() == [
        {"type": "MATTER_THREAD", "id": "cached1"}
    ]
    mock_connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_key_only_route_is_refused_without_a_request(mock_connection):
    mock_connection.ensure_session_connected = AsyncMock(return_value=False)

    with pytest.raises(UniFiAuthError, match="requires Network session authentication"):
        await ClientManager(mock_connection).get_matter_thread_clients()
    mock_connection.request.assert_not_awaited()
    mock_connection.ensure_connected.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_failure_raises_value_free_error(mock_connection):
    mock_connection.request = AsyncMock(side_effect=RuntimeError(f"controller said: {SENTINEL}"))

    with pytest.raises(UniFiOperationError) as excinfo:
        await ClientManager(mock_connection).get_matter_thread_clients()

    assert "RuntimeError" in str(excinfo.value)
    assert SENTINEL not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    mock_connection._update_cache.assert_not_called()
