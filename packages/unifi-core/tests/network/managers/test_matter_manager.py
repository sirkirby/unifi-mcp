"""``MatterManager``: Network 11 Thread networks and Matter nodes (V2, read-only).

Shapes mirror Network 11.0.99 responses for ``/thread-networks`` and
``/matter/nodes`` with every value replaced by test data.
"""

import asyncio
import copy
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.models.api import ApiRequestV2
from unifi_core.exceptions import UniFiAuthError, UniFiOperationError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.matter_manager import (
    MATTER_NODES_PATH,
    THREAD_NETWORKS_PATH,
    MatterManager,
    matter_session_required_message,
)
from unifi_core.network.models.matter import (
    MUTABLE_FIELDS,
    matter_node_from_controller,
    thread_network_from_controller,
)

SENTINEL = "SENTINEL-Kitchen-Plug-fd00:db8::99"

THREAD_NETWORK = {
    "name": "TestNet",
    "extended_pan_id": "0011223344556677",
    "channel": 25,
    "devices": 1,
    "controller": "HOME_ASSISTANT",
    "controller_vendor_raw": None,
    "last_fresh_at": 1700000600000,
    "last_seen_at": 1700000600000,
    "fabrics": [
        {"label": "Fabric", "vendor_id": 4939, "vendor_name": None},
        {"label": "Second Fabric", "vendor_id": 5587, "vendor_name": "Example Vendor"},
    ],
    "border_routers": [
        {
            "name": "Border Router",
            "model_name": "Example Border Router",
            "vendor": "EXAMPLE",
            "vendor_name": "Example Vendor",
            "mac": "aa:bb:cc:00:00:10",
            "ip": "192.0.2.20",
            "host": "border-router.local.",
            "thread_version": "1.3.0",
            "network_name": "TestNet",
            "extended_address": "8899aabbccddeeff",
            "extended_pan_id": "0011223344556677",
            "reporter_mac": "aa:bb:cc:00:00:01",
            "reporter_interface": "br0",
            "fresh": True,
            "first_seen_at": 1700000000000,
            "last_seen_at": 1700000600000,
            "state_bitmap": "00000000",
            "fingerprint": {"dev_id": 1, "os_name": "SECRET-FINGERPRINT"},
        }
    ],
}

MATTER_NODE = {
    "node_id": 7,
    "client_id": "abc1234",
    "display_name": "Smart Plug",
    "device_name": "Plug 20EBO8301",
    "name": None,
    "status": "COMMISSIONED",
    "controller": "HOME_ASSISTANT",
    "controller_vendor_raw": None,
    "channel": 25,
    "has_identify": True,
    "identify_remaining_seconds": None,
    "error_code": None,
    "setup_code": "SECRET-SETUP-CODE",
    "ai_icon": {"id": 1},
    "created_at": 1700000000000,
    "started_at": 1700000000000,
    "finished_at": 1700000060000,
}


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.tls_env_prefix = "NETWORK"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._get_cache_generation = MagicMock(return_value=3)
    conn._update_cache_if_current = MagicMock(return_value=True)
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.ensure_session_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(return_value=None)
    return conn


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def test_read_models_are_read_only():
    assert MUTABLE_FIELDS == frozenset()


def test_thread_network_shape_is_an_allowlist():
    shaped = thread_network_from_controller(copy.deepcopy(THREAD_NETWORK)).model_dump()

    assert shaped == {
        "name": "TestNet",
        "extended_pan_id": "0011223344556677",
        "channel": 25,
        "device_count": 1,
        "controller": "HOME_ASSISTANT",
        "border_routers": [
            {
                "name": "Border Router",
                "model": "Example Border Router",
                "vendor": "Example Vendor",
                "mac": "aa:bb:cc:00:00:10",
                "ip": "192.0.2.20",
                "thread_version": "1.3.0",
                "network_name": "TestNet",
                "extended_address": "8899aabbccddeeff",
                "reporter_mac": "aa:bb:cc:00:00:01",
                "fresh": True,
                "first_seen": "2023-11-14T22:13:20+00:00",
                "last_seen": "2023-11-14T22:23:20+00:00",
            }
        ],
        "fabrics": [
            {"label": "Fabric", "vendor_id": 4939, "vendor_name": None},
            {"label": "Second Fabric", "vendor_id": 5587, "vendor_name": "Example Vendor"},
        ],
        "last_seen": "2023-11-14T22:23:20+00:00",
    }
    assert "SECRET" not in str(shaped)


def test_matter_node_shape_never_copies_the_setup_code():
    shaped = matter_node_from_controller(copy.deepcopy(MATTER_NODE)).model_dump()

    assert shaped == {
        "node_id": 7,
        "name": "Smart Plug",
        "device_name": "Plug 20EBO8301",
        "status": "COMMISSIONED",
        "controller": "HOME_ASSISTANT",
        "channel": 25,
        "thread_client_id": "abc1234",
        "has_identify": True,
        "error_code": None,
        "created_at": "2023-11-14T22:13:20+00:00",
        "finished_at": "2023-11-14T22:14:20+00:00",
    }
    assert "setup_code" not in shaped
    assert "SECRET-SETUP-CODE" not in str(shaped)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            {"device_name": "Fallback", "created_at": 1700000000},
            {"name": "Fallback", "created_at": "2023-11-14T22:13:20+00:00"},
        ),
        ({"error_code": 12, "node_id": True, "channel": "25"}, {"error_code": "12", "node_id": None, "channel": None}),
        ("not-a-record", {"name": None, "status": None}),
    ],
)
def test_matter_node_shape_tolerates_partial_and_odd_values(raw, expected):
    shaped = matter_node_from_controller(raw).model_dump()

    for key, value in expected.items():
        assert shaped[key] == value


def test_thread_network_shape_tolerates_missing_lists():
    shaped = thread_network_from_controller({"name": "Bare", "border_routers": None, "fabrics": "x"}).model_dump()

    assert shaped["name"] == "Bare"
    assert shaped["border_routers"] == []
    assert shaped["fabrics"] == []


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "record", "cache_key"),
    [
        ("list_thread_networks", THREAD_NETWORKS_PATH, THREAD_NETWORK, "matter_thread_networks_default"),
        ("list_matter_nodes", MATTER_NODES_PATH, MATTER_NODE, "matter_nodes_default"),
    ],
)
async def test_reads_the_v2_list_and_caches_it(mock_connection, method, path, record, cache_key):
    mock_connection.request = AsyncMock(return_value=[copy.deepcopy(record), "not-a-record"])

    result = await getattr(MatterManager(mock_connection), method)()

    assert result == [record]
    mock_connection.request.assert_awaited_once()
    request = mock_connection.request.await_args.args[0]
    assert isinstance(request, ApiRequestV2)
    assert request.method == "get"
    assert request.path == path
    mock_connection._get_cache_generation.assert_called_once_with(cache_key)
    mock_connection._update_cache_if_current.assert_called_once_with(cache_key, result, 3)
    mock_connection._update_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list_thread_networks", "list_matter_nodes"])
async def test_empty_list_is_an_empty_success(mock_connection, method):
    mock_connection.request = AsyncMock(return_value=[])

    assert await getattr(MatterManager(mock_connection), method)() == []


@pytest.mark.asyncio
async def test_cached_result_skips_the_request(mock_connection):
    mock_connection.get_cached = MagicMock(return_value=[{"node_id": 1}])

    assert await MatterManager(mock_connection).list_matter_nodes() == [{"node_id": 1}]
    mock_connection.request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list_thread_networks", "list_matter_nodes"])
async def test_api_key_route_is_refused_without_a_request(mock_connection, method):
    mock_connection.ensure_session_connected = AsyncMock(return_value=False)

    with pytest.raises(UniFiAuthError, match="UNIFI_NETWORK_USERNAME"):
        await getattr(MatterManager(mock_connection), method)()
    mock_connection.request.assert_not_awaited()
    mock_connection.ensure_connected.assert_not_awaited()


def test_session_guidance_names_env_variables_only_with_a_prefix():
    assert "UNIFI_NETWORK_USERNAME" in matter_session_required_message("NETWORK")
    without = matter_session_required_message(None)
    assert "UNIFI_" not in without
    assert "controller's configuration" in without


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["list_thread_networks", "list_matter_nodes"])
async def test_request_failure_is_value_free(mock_connection, method):
    mock_connection.request = AsyncMock(side_effect=RuntimeError(f"controller said: {SENTINEL}"))

    with pytest.raises(UniFiOperationError) as excinfo:
        await getattr(MatterManager(mock_connection), method)()

    assert "RuntimeError" in str(excinfo.value)
    assert SENTINEL not in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    mock_connection._update_cache.assert_not_called()
    mock_connection._update_cache_if_current.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [None, {}, {"data": []}, "unexpected"])
async def test_malformed_response_raises_and_is_not_cached(mock_connection, response):
    mock_connection.request = AsyncMock(return_value=response)

    with pytest.raises(UniFiOperationError, match="unexpected response shape"):
        await MatterManager(mock_connection).list_thread_networks()
    mock_connection._update_cache.assert_not_called()
    mock_connection._update_cache_if_current.assert_not_called()


@pytest.mark.asyncio
async def test_connection_without_cache_generations_still_caches(mock_connection):
    """Lightweight fakes without the generation API keep the plain cache write."""
    del mock_connection._get_cache_generation
    del mock_connection._update_cache_if_current
    mock_connection.request = AsyncMock(return_value=[copy.deepcopy(MATTER_NODE)])

    result = await MatterManager(mock_connection).list_matter_nodes()

    assert result == [MATTER_NODE]
    mock_connection._update_cache.assert_called_once_with("matter_nodes_default", result)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "cache_key", "record", "invalidate"),
    [
        ("list_thread_networks", "matter_thread_networks_default", THREAD_NETWORK, "key"),
        ("list_matter_nodes", "matter_nodes_default", MATTER_NODE, "key"),
        ("list_matter_nodes", "matter_nodes_default", MATTER_NODE, "all"),
    ],
)
async def test_in_flight_read_cannot_restore_cache_after_invalidation(method, cache_key, record, invalidate):
    connection = ConnectionManager("controller.invalid", "user", "password")
    connection.ensure_session_connected = AsyncMock(return_value=True)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def delayed_read(_request):
        started.set()
        await finish.wait()
        return [copy.deepcopy(record)]

    connection.request = delayed_read
    read_task = asyncio.create_task(getattr(MatterManager(connection), method)())
    await started.wait()
    connection._invalidate_cache(cache_key if invalidate == "key" else None)
    finish.set()

    assert await read_task == [record]
    assert connection.get_cached(cache_key) is None


@pytest.mark.asyncio
async def test_uninterrupted_read_is_cached_on_a_real_connection():
    connection = ConnectionManager("controller.invalid", "user", "password")
    connection.ensure_session_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value=[copy.deepcopy(MATTER_NODE)])

    result = await MatterManager(connection).list_matter_nodes()

    assert connection.get_cached("matter_nodes_default") == [MATTER_NODE]
    assert result == [MATTER_NODE]
