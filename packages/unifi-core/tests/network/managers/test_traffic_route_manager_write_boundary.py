"""Write-boundary tests for TrafficRouteManager."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager


def _connection(route):
    connection = MagicMock()
    connection.site = "default"
    connection.get_cached.return_value = None
    connection.request = AsyncMock(return_value={"data": [route]})
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


async def test_update_rejects_invalid_replacement_before_put():
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError):
        await manager.update_traffic_route("route-1", domains=[{"domain": "example.com", "unknown": True}])

    assert connection.request.await_count == 1
    connection._invalidate_cache.assert_not_called()


async def test_update_rejects_unknown_and_immutable_fields_before_put():
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError):
        await manager.update_traffic_route("route-1", network_id="network-2")

    assert connection.request.await_count == 1


async def test_enabled_update_preserves_malformed_legacy_fields_and_puts_merged_route():
    legacy_route = _route(domains=[{"domain": 1, "legacy": True}], target_devices="legacy")
    connection = _connection(legacy_route)
    manager = TrafficRouteManager(connection)

    assert await manager.update_traffic_route("route-1", enabled=False) is True

    assert connection.request.await_count == 2
    put = connection.request.await_args_list[1].args[0]
    assert put.method == "put"
    assert put.data == {**legacy_route, "enabled": False}


async def test_update_request_failure_invalidates_cache_without_leaking_controller_payload(caplog):
    route = _route()
    connection = _connection(route)
    marker = "controller-payload-marker"
    connection.request = AsyncMock(side_effect=[{"data": [route]}, RuntimeError({"marker": marker})])
    manager = TrafficRouteManager(connection)

    caplog.set_level(logging.ERROR, logger="unifi-network-mcp")

    with pytest.raises(RuntimeError, match=marker):
        await manager.update_traffic_route("route-1", enabled=False)

    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")
    assert marker not in caplog.text
    assert "route-1" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_get_failure_does_not_log_controller_payload(caplog):
    connection = _connection(_route())
    marker = "controller-payload-marker"
    connection.request = AsyncMock(side_effect=RuntimeError({"marker": marker}))
    manager = TrafficRouteManager(connection)

    caplog.set_level(logging.ERROR, logger="unifi-network-mcp")

    with pytest.raises(RuntimeError, match=marker):
        await manager.get_traffic_routes()

    assert marker not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_update_accepts_controller_description_alias_and_puts_merged_route():
    route = _route()
    connection = _connection(route)
    manager = TrafficRouteManager(connection)

    assert await manager.update_traffic_route("route-1", description="Renamed route") is True

    assert connection.request.await_count == 2
    put = connection.request.await_args_list[1].args[0]
    assert put.method == "put"
    assert put.data == {**route, "description": "Renamed route"}


async def test_update_success_does_not_log_route_identifier(caplog):
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    caplog.set_level(logging.INFO, logger="unifi-network-mcp")

    assert await manager.update_traffic_route("route-1", description="Renamed route") is True

    assert "route-1" not in caplog.text


async def test_update_rejects_overlong_controller_description_alias_before_put():
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError, match="at most 128 characters"):
        await manager.update_traffic_route("route-1", description="x" * 129)

    assert connection.request.await_count == 1
    connection._invalidate_cache.assert_not_called()


async def test_update_rejects_conflicting_public_and_controller_name_aliases_before_put():
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError, match="cannot include both name and description"):
        await manager.update_traffic_route("route-1", name="Public name", description="Controller name")

    assert connection.request.await_count == 1


async def test_update_allows_clearing_one_ip_selector_when_fetched_sibling_remains():
    route = _route(
        matching_target="IP",
        domains=[],
        ip_addresses=[{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4", "ports": [], "port_ranges": []}],
        ip_ranges=[{"ip_start": "203.0.113.2", "ip_stop": "203.0.113.3", "ip_version": "IPV4"}],
    )
    connection = _connection(route)
    manager = TrafficRouteManager(connection)

    assert await manager.update_traffic_route("route-1", ip_addresses=[]) is True

    put = connection.request.await_args_list[1].args[0]
    assert put.method == "put"
    assert put.data == {**route, "ip_addresses": []}
    assert route["ip_addresses"]


async def test_update_rejects_clearing_all_ip_selectors_before_put():
    route = _route(
        matching_target="IP",
        domains=[],
        ip_addresses=[{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4", "ports": [], "port_ranges": []}],
        ip_ranges=[{"ip_start": "203.0.113.2", "ip_stop": "203.0.113.3", "ip_version": "IPV4"}],
    )
    connection = _connection(route)
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError, match="IP Traffic Routes require ip_addresses or ip_ranges"):
        await manager.update_traffic_route("route-1", ip_addresses=[], ip_ranges=[])

    assert connection.request.await_count == 1


@pytest.mark.parametrize("matching_target", ["INTERNET", "legacy-malformed"])
async def test_enabled_update_preserves_legacy_target_and_puts_merged_route(matching_target):
    legacy_route = _route(matching_target=matching_target, domains=[{"domain": 1, "legacy": True}])
    connection = _connection(legacy_route)
    manager = TrafficRouteManager(connection)

    assert await manager.update_traffic_route("route-1", enabled=False) is True

    assert connection.request.await_count == 2
    put = connection.request.await_args_list[1].args[0]
    assert put.method == "put"
    assert put.data == {**legacy_route, "enabled": False}


@pytest.mark.parametrize(
    "updates",
    [
        {"enabled": True},
        {"next_hop": "10.0.0.1"},
        {"kill_switch_enabled": True},
    ],
)
async def test_update_rejects_routing_mutation_of_internet_route_before_put(updates):
    route = _route(matching_target="INTERNET", domains=[{"domain": 1, "legacy": True}])
    connection = _connection(route)
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError, match="only be renamed or disabled"):
        await manager.update_traffic_route("route-1", **updates)

    assert connection.request.await_count == 1
    connection._invalidate_cache.assert_not_called()


async def test_toggle_rejects_reenabling_internet_route_before_put():
    route = _route(matching_target="INTERNET", enabled=False, domains=[{"domain": 1, "legacy": True}])
    connection = _connection(route)
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError, match="only be renamed or disabled"):
        await manager.toggle_traffic_route("route-1")

    assert connection.request.await_count == 2
    assert all(call.args[0].method == "get" for call in connection.request.await_args_list)
    connection._invalidate_cache.assert_not_called()


async def test_create_validates_canonical_payload_before_post_and_invalidates_cache():
    connection = _connection(_route())
    connection.request = AsyncMock(return_value={"_id": "route-2"})
    manager = TrafficRouteManager(connection)

    created = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert created == {"_id": "route-2"}
    post = connection.request.await_args.args[0]
    assert post.method == "post"
    assert post.path == "/trafficroutes"
    assert post.data["target_devices"] == [{"type": "ALL_CLIENTS"}]
    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


async def test_create_does_not_recapture_a_get_started_before_the_write():
    connection = ConnectionManager("controller.invalid", "user", "password")
    get_started = asyncio.Event()
    release_get = asyncio.Event()
    stale_routes = [{"_id": "old-route"}]

    async def request(api_request):
        if api_request.method == "get":
            get_started.set()
            await release_get.wait()
            return {"data": stale_routes}
        if api_request.method == "post":
            return {"_id": "new-route"}
        raise AssertionError(f"Unexpected request: {api_request.method}")

    connection.request = AsyncMock(side_effect=request)
    manager = TrafficRouteManager(connection)

    in_flight_get = asyncio.create_task(manager.get_traffic_routes())
    await get_started.wait()
    assert await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    ) == {"_id": "new-route"}

    release_get.set()
    assert await in_flight_get == stale_routes
    assert connection.get_cached("traffic_routes_default") is None


async def test_create_unwraps_v2_singleton_data_envelope():
    connection = _connection(_route())
    connection.request = AsyncMock(return_value={"data": [{"_id": "route-2", "description": "Domain route"}]})
    manager = TrafficRouteManager(connection)

    created = await manager.create_traffic_route(
        {
            "description": "Domain route",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com"}],
        }
    )

    assert created["_id"] == "route-2"
    assert created["description"] == "Domain route"
    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


@pytest.mark.parametrize(
    "response",
    [
        None,
        {"data": []},
        [],
        {},
        {"data": [{}]},
        {"data": [{"_id": "route-2"}, {"_id": "route-3"}]},
        {"data": {"_id": ""}},
        {"data": "not-a-route"},
    ],
)
async def test_create_rejects_unusable_response_and_invalidates_cache(response):
    connection = _connection(_route())
    connection.request = AsyncMock(return_value=response)
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError, match="may have been created"):
        await manager.create_traffic_route(
            {
                "description": "Domain route",
                "matching_target": "DOMAIN",
                "network_id": "network-1",
                "domains": [{"domain": "example.com"}],
            }
        )

    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


async def test_create_request_failure_invalidates_cache():
    connection = _connection(_route())
    connection.request = AsyncMock(side_effect=RuntimeError("controller disconnected"))
    manager = TrafficRouteManager(connection)

    with pytest.raises(RuntimeError, match="controller disconnected"):
        await manager.create_traffic_route(
            {
                "description": "Domain route",
                "matching_target": "DOMAIN",
                "network_id": "network-1",
                "domains": [{"domain": "example.com"}],
            }
        )

    connection._invalidate_cache.assert_called_once_with("traffic_routes_default")


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
        {
            "description": "Malformed",
            "matching_target": "DOMAIN",
            "network_id": "network-1",
            "domains": [{"domain": "example.com", "unknown": True}],
        },
    ],
)
async def test_create_rejects_unsafe_payload_without_post(route_data):
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError):
        await manager.create_traffic_route(route_data)

    connection.request.assert_not_awaited()


async def test_kill_switch_uses_same_validation_boundary():
    connection = _connection(_route())
    manager = TrafficRouteManager(connection)

    with pytest.raises(ValueError):
        await manager.update_kill_switch("route-1", enabled="yes")

    assert connection.request.await_count == 1
