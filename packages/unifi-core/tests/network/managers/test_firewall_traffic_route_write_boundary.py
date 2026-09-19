"""Write-boundary tests for FirewallManager traffic-route creation."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.models.traffic_route import TrafficRoute
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.firewall_manager import FirewallManager


def _connection():
    connection = MagicMock()
    connection.site = "default"
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.request = AsyncMock(return_value={"_id": "route-2"})
    return connection


def _route(**overrides):
    route = {
        "_id": "route-1",
        "description": "Domain route",
        "matching_target": "DOMAIN",
        "network_id": "network-1",
        "enabled": True,
        "domains": [{"domain": "example.com", "ports": [], "port_ranges": []}],
        "ip_addresses": [],
        "ip_ranges": [],
        "regions": [],
        "target_devices": [{"type": "ALL_CLIENTS"}],
    }
    route.update(overrides)
    return route


async def test_create_traffic_route_posts_normalized_canonical_payload(caplog):
    connection = _connection()
    manager = FirewallManager(connection)

    caplog.set_level(logging.INFO, logger="unifi-network-mcp")

    result = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert result == {"success": True, "route_id": "route-2"}
    post = connection.request.await_args.args[0]
    assert post.method == "post"
    assert post.path == "/trafficroutes"
    assert post.data["target_devices"] == [{"type": "ALL_CLIENTS"}]
    assert "route-2" not in caplog.text


async def test_create_traffic_route_unwraps_v2_data_envelope_and_invalidates_cache():
    connection = _connection()
    connection.request.return_value = {"data": [{"_id": "route-v2"}]}
    manager = FirewallManager(connection)

    result = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert result == {"success": True, "route_id": "route-v2"}
    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


async def test_create_does_not_recapture_a_get_started_before_the_write():
    connection = ConnectionManager("controller.invalid", "user", "password")
    connection.ensure_connected = AsyncMock(return_value=True)
    get_started = asyncio.Event()
    release_get = asyncio.Event()
    stale_route = _route(_id="old-route")

    async def request(api_request):
        if api_request.method == "get":
            get_started.set()
            await release_get.wait()
            return {"data": [stale_route]}
        if api_request.method == "post":
            return {"_id": "new-route"}
        raise AssertionError(f"Unexpected request: {api_request.method}")

    connection.request = AsyncMock(side_effect=request)
    manager = FirewallManager(connection)

    in_flight_get = asyncio.create_task(manager.get_traffic_routes())
    await get_started.wait()
    assert await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    ) == {"success": True, "route_id": "new-route"}

    release_get.set()
    assert [route.raw for route in await in_flight_get] == [stale_route]
    assert connection.get_cached("traffic_routes_default") is None


async def test_get_failure_does_not_log_controller_payload(caplog):
    connection = _connection()
    connection.get_cached.return_value = None
    marker = "controller-payload-marker"
    connection.request = AsyncMock(side_effect=RuntimeError({"marker": marker}))
    manager = FirewallManager(connection)

    caplog.set_level(logging.ERROR, logger="unifi-network-mcp")

    with pytest.raises(RuntimeError, match=marker):
        await manager.get_traffic_routes()

    assert marker not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_create_invalidates_cache_after_transport_failure_without_leaking_controller_payload(caplog):
    connection = _connection()
    marker = "controller-payload-marker"
    connection.request = AsyncMock(side_effect=RuntimeError({"data": [{"marker": marker}]}))
    manager = FirewallManager(connection)
    caplog.set_level(logging.ERROR, logger="unifi-network-mcp")

    result = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert result == {
        "success": False,
        "error": "Controller returned no created traffic route; the route may have been created. "
        "List traffic routes before retrying.",
    }
    assert marker not in str(result)
    assert marker not in caplog.text
    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


async def test_create_reports_ambiguous_response_without_echoing_it():
    connection = _connection()
    connection.request.return_value = {"data": []}
    manager = FirewallManager(connection)

    result = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert result == {
        "success": False,
        "error": "Controller returned no created traffic route; the route may have been created. "
        "List traffic routes before retrying.",
    }


@pytest.mark.parametrize(
    "response",
    [
        {"data": [{}]},
        {"data": [None]},
        {"data": [{"_id": 1}]},
        {"data": [{"_id": " "}]},
        {"data": [{"_id": "route-2"}, {"_id": "route-3"}]},
    ],
)
async def test_create_rejects_noncanonical_response_shapes(response):
    connection = _connection()
    connection.request.return_value = response
    manager = FirewallManager(connection)

    result = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert result == {
        "success": False,
        "error": "Controller returned no created traffic route; the route may have been created. "
        "List traffic routes before retrying.",
    }


@pytest.mark.parametrize(
    "route_data",
    [
        {"description": "Catch all", "matching_target": "INTERNET", "network_id": "network-1"},
        {
            "description": "Empty targets",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
            "target_devices": [],
        },
        {"name": "legacy", "interface": "vpn"},
    ],
)
async def test_create_traffic_route_rejects_invalid_or_legacy_payload_without_post(route_data):
    connection = _connection()
    manager = FirewallManager(connection)

    with pytest.raises(ValueError):
        await manager.create_traffic_route(route_data)

    connection.request.assert_not_awaited()


async def test_update_rejects_invalid_selector_replacement_without_put():
    connection = _connection()
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route(matching_target="INTERNET"))])

    with pytest.raises(ValueError):
        await manager.update_traffic_route("route-1", {"domains": [{"domain": "example.com"}]})

    connection.request.assert_not_awaited()
    connection._invalidate_cache.assert_not_called()


async def test_update_request_failure_invalidates_cache_without_leaking_controller_payload(caplog):
    connection = _connection()
    marker = "controller-payload-marker"
    connection.request = AsyncMock(side_effect=RuntimeError({"marker": marker}))
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route())])

    caplog.set_level(logging.ERROR, logger="unifi-network-mcp")

    with pytest.raises(RuntimeError, match=marker):
        await manager.update_traffic_route("route-1", {"enabled": False})

    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")
    assert marker not in caplog.text
    assert "route-1" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_empty_update_does_not_log_route_identifier(caplog):
    connection = _connection()
    manager = FirewallManager(connection)

    caplog.set_level(logging.WARNING, logger="unifi-network-mcp")

    assert await manager.update_traffic_route("route-1", {}) is True

    assert "route-1" not in caplog.text


async def test_update_allows_clearing_one_ip_selector_when_fetched_sibling_remains(caplog):
    connection = _connection()
    raw_route = _route(
        description="controller-route-marker",
        matching_target="IP",
        domains=[],
        ip_addresses=[{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4", "ports": [], "port_ranges": []}],
        ip_ranges=[{"ip_start": "203.0.113.2", "ip_stop": "203.0.113.3", "ip_version": "IPV4"}],
    )
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(raw_route)])

    caplog.set_level(logging.INFO, logger="unifi-network-mcp")

    assert await manager.update_traffic_route("route-1", {"ip_ranges": []}) is True

    put = connection.request.await_args.args[0]
    assert put.method == "put"
    assert put.data == {**raw_route, "ip_ranges": []}
    assert raw_route["ip_ranges"]
    assert "controller-route-marker" not in caplog.text
    assert "route-1" not in caplog.text


async def test_toggle_does_not_log_route_identifier(caplog):
    connection = _connection()
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route())])
    manager.update_traffic_route = AsyncMock(return_value=True)

    caplog.set_level(logging.INFO, logger="unifi-network-mcp")

    assert await manager.toggle_traffic_route("route-1") is True

    assert "route-1" not in caplog.text


async def test_delete_failure_invalidates_cache_without_leaking_controller_payload(caplog):
    connection = _connection()
    marker = "controller-payload-marker"
    connection.request = AsyncMock(side_effect=RuntimeError({"marker": marker}))
    manager = FirewallManager(connection)

    caplog.set_level(logging.ERROR, logger="unifi-network-mcp")

    with pytest.raises(RuntimeError, match=marker):
        await manager.delete_traffic_route("route-1")

    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")
    assert marker not in caplog.text
    assert "route-1" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_delete_success_does_not_log_route_identifier(caplog):
    connection = _connection()
    manager = FirewallManager(connection)

    caplog.set_level(logging.INFO, logger="unifi-network-mcp")

    assert await manager.delete_traffic_route("route-1") is True

    assert "route-1" not in caplog.text


async def test_update_validates_controller_description_alias_before_put():
    connection = _connection()
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route())])

    with pytest.raises(ValueError, match="name must be a non-empty string"):
        await manager.update_traffic_route("route-1", {"description": " "})

    connection.request.assert_not_awaited()


async def test_update_rejects_overlong_controller_description_alias_before_put():
    connection = _connection()
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route())])

    with pytest.raises(ValueError, match="at most 128 characters"):
        await manager.update_traffic_route("route-1", {"description": "x" * 129})

    connection.request.assert_not_awaited()
    connection._invalidate_cache.assert_not_called()


async def test_update_rejects_conflicting_name_and_description_aliases_without_put():
    connection = _connection()
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route())])

    with pytest.raises(ValueError, match="cannot include both name and description"):
        await manager.update_traffic_route("route-1", {"name": "Public", "description": "Controller"})

    connection.request.assert_not_awaited()


async def test_update_allows_scalar_legacy_internet_route_and_puts_merged_payload():
    connection = _connection()
    raw_route = _route(matching_target="INTERNET", domains=[{"domain": 1, "legacy": True}])
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(raw_route)])

    assert await manager.update_traffic_route("route-1", {"enabled": False}) is True

    put = connection.request.await_args.args[0]
    assert put.method == "put"
    assert put.path == "/trafficroutes/route-1"
    assert put.data == {**raw_route, "enabled": False}
    assert raw_route["enabled"] is True
    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


@pytest.mark.parametrize(
    "updates",
    [
        {"enabled": True},
        {"next_hop": "10.0.0.1"},
        {"kill_switch_enabled": True},
    ],
)
async def test_update_rejects_routing_mutation_of_internet_route_before_put(updates):
    connection = _connection()
    raw_route = _route(matching_target="INTERNET", domains=[{"domain": 1, "legacy": True}])
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(raw_route)])

    with pytest.raises(ValueError, match="only be renamed or disabled"):
        await manager.update_traffic_route("route-1", updates)

    connection.request.assert_not_awaited()
    connection._invalidate_cache.assert_not_called()


async def test_toggle_rejects_reenabling_internet_route_before_put():
    connection = _connection()
    raw_route = _route(matching_target="INTERNET", enabled=False, domains=[{"domain": 1, "legacy": True}])
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(raw_route)])

    with pytest.raises(ValueError, match="only be renamed or disabled"):
        await manager.toggle_traffic_route("route-1")

    connection.request.assert_not_awaited()
    connection._invalidate_cache.assert_not_called()


@pytest.mark.parametrize("updates", [{"network_id": "network-2"}, {"unknown": "value"}])
async def test_update_rejects_immutable_or_unknown_fields_without_put(updates):
    connection = _connection()
    manager = FirewallManager(connection)
    manager.get_traffic_routes = AsyncMock(return_value=[TrafficRoute(_route())])

    with pytest.raises(ValueError):
        await manager.update_traffic_route("route-1", updates)

    connection.request.assert_not_awaited()
