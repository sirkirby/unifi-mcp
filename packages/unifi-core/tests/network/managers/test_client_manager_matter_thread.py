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


# ---------------------------------------------------------------------------
# get_client_inventory + shape_client_inventory: the composition the MCP tool
# and the API action share.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inventory_thread_reads_only_thread_clients(mock_connection):
    manager = ClientManager(mock_connection)
    manager.get_clients = AsyncMock(return_value=[WIRED_RECORD])
    manager.get_matter_thread_clients = AsyncMock(return_value=[THREAD_RECORD])

    inventory = await manager.get_client_inventory(filter_type="thread")

    assert inventory == {"clients": [], "thread_clients": [THREAD_RECORD]}
    manager.get_clients.assert_not_awaited()


@pytest.mark.asyncio
async def test_inventory_all_adds_thread_clients_best_effort(mock_connection):
    manager = ClientManager(mock_connection)
    manager.get_clients = AsyncMock(return_value=[WIRED_RECORD])
    manager.get_matter_thread_clients = AsyncMock(side_effect=ConnectionError("no V2"))

    inventory = await manager.get_client_inventory(filter_type="all", include_offline=True)

    assert inventory == {"clients": [WIRED_RECORD], "thread_clients": None}
    manager.get_clients.assert_awaited_once_with(include_offline=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("filter_type", ["wired", "wireless"])
async def test_inventory_connection_filters_skip_the_thread_read(mock_connection, filter_type):
    manager = ClientManager(mock_connection)
    manager.get_clients = AsyncMock(return_value=[WIRED_RECORD])
    manager.get_matter_thread_clients = AsyncMock(return_value=[THREAD_RECORD])

    inventory = await manager.get_client_inventory(filter_type=filter_type)

    assert inventory["thread_clients"] is None
    manager.get_matter_thread_clients.assert_not_awaited()


@pytest.mark.asyncio
async def test_inventory_all_skips_thread_read_on_integration_only_inventory(mock_connection):
    mock_connection.has_api_key = True
    mock_connection.integration_inventory_only = True
    manager = ClientManager(mock_connection)
    manager.get_clients = AsyncMock(return_value=[WIRED_RECORD])
    manager.get_matter_thread_clients = AsyncMock(return_value=[THREAD_RECORD])

    inventory = await manager.get_client_inventory(filter_type="all")

    assert inventory["thread_clients"] is None
    manager.get_matter_thread_clients.assert_not_awaited()


def test_shape_inventory_all_reports_thread_count_without_mixing_records():
    from unifi_core.network.read_views import shape_client_inventory

    result = shape_client_inventory(
        {"clients": [WIRED_RECORD, WIRELESS_RECORD], "thread_clients": [THREAD_RECORD]},
        site="default",
        filter_type="all",
    )

    assert result["success"] is True
    assert [client.get("mac") for client in result["clients"]] == [WIRED_RECORD["mac"], WIRELESS_RECORD["mac"]]
    assert result["thread_client_count"] == 1
    assert result["included_connection_types"] == ["Wired", "Wireless"]


def test_shape_inventory_thread_and_invalid_filter():
    from unifi_core.network.read_views import shape_client_inventory

    thread = shape_client_inventory(
        {"clients": [], "thread_clients": [THREAD_RECORD]}, site="default", filter_type="thread"
    )
    assert thread["filter_type"] == "thread"
    assert thread["clients"][0]["thread_client_id"] == "abc1234"

    invalid = shape_client_inventory({"clients": [], "thread_clients": None}, site="default", filter_type="zigbee")
    assert invalid["success"] is False
    assert "thread" in str(invalid)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("env_prefix", "expected", "absent"),
    [("NETWORK", "UNIFI_NETWORK_USERNAME", None), (None, "this controller's configuration", "UNIFI_")],
)
async def test_session_required_names_where_credentials_go(mock_connection, env_prefix, expected, absent):
    from unifi_core.exceptions import UniFiAuthError

    mock_connection.ensure_session_connected = AsyncMock(return_value=False)
    mock_connection.tls_env_prefix = env_prefix

    with pytest.raises(UniFiAuthError) as excinfo:
        await ClientManager(mock_connection).get_matter_thread_clients()

    assert expected in str(excinfo.value)
    if absent:
        assert absent not in str(excinfo.value)
