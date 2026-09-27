"""Safety validation for TrafficRouteManager mutations."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.auth import UniFiAuth
from unifi_core.exceptions import UniFiAuthError, UniFiNotFoundError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager, TrafficRoutePreflightError

VALID_TARGET = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
VALID_DOMAIN_ROUTE = {
    "description": "Domain route",
    "matching_target": "DOMAIN",
    "network_id": "vpn-target",
    "domains": [{"domain": "example.com"}],
}


def _manager(*, purpose: str = "wan") -> tuple[TrafficRouteManager, MagicMock, MagicMock]:
    connection = MagicMock()
    connection.site = "default"
    connection.request = AsyncMock(return_value={"data": {"_id": "route-new"}})
    network_manager = MagicMock()
    network_manager.get_network_details = AsyncMock(return_value={"_id": "wan-target", "purpose": purpose})
    manager = TrafficRouteManager(connection, network_manager=network_manager)
    return manager, connection, network_manager


def _seed_both_traffic_route_caches(connection: MagicMock) -> dict[str, object]:
    """Populate the guarded and legacy route caches with distinct representations."""
    cache: dict[str, object] = {
        f"traffic_routes_{connection.site}": [{"_id": "guarded-route"}],
        f"legacy_traffic_routes_{connection.site}": ["legacy-route-wrapper"],
    }
    connection.get_cached.side_effect = cache.get
    connection._update_cache.side_effect = cache.__setitem__

    def invalidate(prefix: str) -> None:
        for key in list(cache):
            if key.startswith(prefix):
                del cache[key]

    connection._invalidate_cache.side_effect = invalidate
    return cache


@pytest.mark.parametrize(
    "changes",
    [
        {"domains": [{"domain": " "}]},
        {"domains": [{"domain": "example.com", "ports": [True]}]},
        {"domains": [{"domain": "example.com", "port_ranges": [{"port_start": 900, "port_stop": 100}]}]},
        {"target_devices": [{"type": "CLIENT", "client_mac": "not-a-mac"}]},
        {"target_devices": [{"type": "ALL_CLIENTS"}, {"type": "NETWORK", "network_id": "n"}]},
        {"enabled": "false"},
        {"unknown_field": True},
        {"unknown_field": None},
    ],
)
@pytest.mark.asyncio
async def test_create_rejects_invalid_domain_write_before_post(changes: dict) -> None:
    manager, connection, _ = _manager()
    with pytest.raises(ValueError):
        await manager.create_traffic_route({**VALID_DOMAIN_ROUTE, **changes})
    connection.request.assert_not_awaited()


@pytest.mark.parametrize(
    "route",
    [
        {"matching_target": "IP", "ip_addresses": [{"ip_or_subnet": "2001:db8::1", "ip_version": "IPV4"}]},
        {
            "matching_target": "IP",
            "ip_ranges": [{"ip_start": "203.0.113.9", "ip_stop": "203.0.113.1", "ip_version": "IPV4"}],
        },
        {"matching_target": "REGION", "regions": [""]},
    ],
)
@pytest.mark.asyncio
async def test_create_rejects_invalid_other_selector_before_post(route: dict) -> None:
    manager, connection, _ = _manager()
    with pytest.raises(ValueError):
        await manager.create_traffic_route({"description": "Route", "network_id": "vpn-target", **route})
    connection.request.assert_not_awaited()


@pytest.mark.parametrize(
    "route",
    [
        {"matching_target": "IP", "ip_addresses": [{"ip_or_subnet": "2001:db8::1", "ip_version": "IPV6"}]},
        {"matching_target": "REGION", "regions": ["US"]},
    ],
)
@pytest.mark.asyncio
async def test_create_accepts_valid_ip_and_region_selectors(route: dict) -> None:
    manager, connection, _ = _manager()
    created = await manager.create_traffic_route({"description": "Route", "network_id": "vpn-target", **route})
    assert created == {"_id": "route-new"}
    sent = connection.request.await_args.args[0].data
    assert sent["matching_target"] == route["matching_target"]
    assert "target_devices" not in sent


@pytest.mark.parametrize(
    ("field", "item"),
    [
        ("ip_addresses", {"ip_or_subnet": "203.0.113.10", "ip_version": "v4", "ports": [], "port_ranges": []}),
        ("ip_ranges", {"ip_start": "2001:db8::1", "ip_stop": "2001:db8::9", "ip_version": "v6"}),
    ],
)
@pytest.mark.asyncio
async def test_create_posts_controller_ip_versions(field: str, item: dict) -> None:
    manager, connection, _ = _manager()
    await manager.create_traffic_route(
        {
            "description": "IP route",
            "matching_target": "IP",
            "network_id": "vpn-target",
            field: [item],
        }
    )
    sent = connection.request.await_args.args[0].data
    assert sent[field][0]["ip_version"] == item["ip_version"]
    assert "ip_version" not in sent


@pytest.mark.asyncio
async def test_unrelated_update_preserves_fetched_ip_selector_spelling() -> None:
    manager, connection, _ = _manager()
    current = {
        "_id": "route-1",
        "description": "Older IP route",
        "matching_target": "IP",
        "network_id": "vpn-target",
        "ip_addresses": [{"ip_or_subnet": "203.0.113.10", "ip_version": "IPV4", "legacy": True}],
    }
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert await manager.update_traffic_route("route-1", description="Renamed") is True
    assert connection.request.await_args.args[0].data == {**current, "description": "Renamed"}


@pytest.mark.asyncio
async def test_submitted_ip_range_alias_normalizes_without_rewriting_fetched_selector() -> None:
    manager, connection, _ = _manager()
    current = {
        "_id": "route-1",
        "description": "IP route",
        "matching_target": "IP",
        "network_id": "vpn-target",
        "ip_addresses": [{"ip_or_subnet": "203.0.113.10", "ip_version": "IPV4", "legacy": True}],
        "ip_ranges": [],
    }
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert (
        await manager.update_traffic_route(
            "route-1", ip_ranges=[{"ip_start": "2001:db8::1", "ip_stop": "2001:db8::9", "ip_version": "IPV6"}]
        )
        is True
    )
    sent = connection.request.await_args.args[0].data
    assert sent["ip_addresses"] == current["ip_addresses"]
    assert sent["ip_ranges"] == [{"ip_start": "2001:db8::1", "ip_stop": "2001:db8::9", "ip_version": "v6"}]


@pytest.mark.asyncio
async def test_create_normalizes_explicit_client_target_without_changing_scope() -> None:
    manager, connection, _ = _manager()
    await manager.create_traffic_route(
        {
            **VALID_DOMAIN_ROUTE,
            "target_devices": [{"type": "CLIENT", "client_mac": "AA-BB-CC-DD-EE-FE"}],
        }
    )
    assert connection.request.await_args.args[0].data["target_devices"] == [
        {"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:fe"}
    ]


@pytest.mark.asyncio
async def test_update_rejects_unknown_immutable_and_invalid_submissions_before_put() -> None:
    manager, connection, _ = _manager()
    manager.get_traffic_route_details = AsyncMock(return_value={**VALID_DOMAIN_ROUTE, "_id": "route-1", "legacy": 42})
    for changes in (
        {"unknown_field": True},
        {"unknown_field": None},
        {"_id": "replacement"},
        {"matching_target": "IP"},
        {"enabled": "false"},
        {"domains": [{"domain": " "}]},
    ):
        with pytest.raises(ValueError):
            await manager.update_traffic_route("route-1", **changes)
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_preserves_existing_imperfect_fields_when_disabling() -> None:
    manager, connection, _ = _manager()
    current = {**VALID_DOMAIN_ROUTE, "_id": "route-1", "domains": [{"legacy": True}], "opaque": {"keep": True}}
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert await manager.update_traffic_route("route-1", enabled=False) is True
    assert connection.request.await_args.args[0].data == {**current, "enabled": False}


@pytest.mark.asyncio
async def test_update_can_rename_imperfect_existing_route() -> None:
    manager, connection, _ = _manager()
    current = {**VALID_DOMAIN_ROUTE, "_id": "route-1", "domains": [{"legacy": True}]}
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert await manager.update_traffic_route("route-1", description="Safer name") is True
    assert connection.request.await_args.args[0].data == {**current, "description": "Safer name"}


@pytest.mark.asyncio
async def test_update_accepts_empty_inactive_selectors_and_preserves_fetched_fields() -> None:
    manager, connection, _ = _manager()
    current = {**VALID_DOMAIN_ROUTE, "_id": "route-1", "legacy": {"keep": True}}
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert await manager.update_traffic_route("route-1", regions=[], ip_addresses=[]) is True
    assert connection.request.await_args.args[0].data == {**current, "regions": [], "ip_addresses": []}


@pytest.mark.asyncio
async def test_update_uses_normalized_known_target_and_safe_unknown_target_error() -> None:
    manager, connection, _ = _manager()
    current = {**VALID_DOMAIN_ROUTE, "_id": "route-1", "matching_target": "domain"}
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert await manager.update_traffic_route("route-1", domains=[{"domain": "example.org"}]) is True
    connection.request.reset_mock()
    current["matching_target"] = "secret-controller-value"
    with pytest.raises(ValueError, match="matching_target") as error:
        await manager.update_traffic_route("route-1", domains=[{"domain": "example.org"}])
    assert "secret-controller-value" not in str(error.value)
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabling_internet_route_with_equivalent_mac_does_not_lookup_wan() -> None:
    manager, connection, network_manager = _manager()
    current = {
        "_id": "route-1",
        "description": "Internet route",
        "matching_target": "INTERNET",
        "network_id": "legacy-vpn",
        "enabled": True,
        "target_devices": [{"type": "CLIENT", "client_mac": "AA-BB-CC-DD-EE-FE"}],
    }
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert (
        await manager.update_traffic_route(
            "route-1",
            enabled=False,
            target_devices=[{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:fe"}],
        )
        is True
    )
    network_manager.get_network_details.assert_not_awaited()
    assert connection.request.await_args.args[0].data["enabled"] is False


@pytest.mark.asyncio
async def test_internet_create_rejects_extra_target_key_before_wan_lookup_or_post() -> None:
    manager, connection, network_manager = _manager()
    with pytest.raises(TrafficRoutePreflightError, match="no network_id"):
        await manager.create_traffic_route(
            {
                "description": "Internet route",
                "matching_target": "INTERNET",
                "network_id": "wan-target",
                "target_devices": [
                    {
                        "type": "CLIENT",
                        "client_mac": "02:11:22:33:44:55",
                        "network_id": {"bad": True},
                    }
                ],
            }
        )
    network_manager.get_network_details.assert_not_awaited()
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_missing_wan_preflight_is_not_route_not_found() -> None:
    manager, connection, network_manager = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-1",
            "description": "Internet route",
            "matching_target": "INTERNET",
            "network_id": "wan-old",
            "target_devices": VALID_TARGET,
            "enabled": True,
        }
    )
    network_manager.get_network_details = AsyncMock(side_effect=UniFiNotFoundError("network", "wan-gone"))
    with pytest.raises(TrafficRoutePreflightError, match="Target network was not found"):
        await manager.update_traffic_route("route-1", network_id="wan-gone")
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_ip_selector_retains_existing_other_selector() -> None:
    manager, connection, _ = _manager()
    current = {
        "_id": "route-1",
        "matching_target": "IP",
        "network_id": "vpn-target",
        "ip_addresses": [{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4"}],
        "ip_ranges": [{"legacy": True}],
    }
    manager.get_traffic_route_details = AsyncMock(return_value=current)
    assert await manager.update_traffic_route("route-1", ip_addresses=[]) is True
    assert connection.request.await_args.args[0].data == {**current, "ip_addresses": []}


@pytest.mark.asyncio
async def test_internet_wan_validation_requires_session_before_public_inventory_lookup() -> None:
    connection = ConnectionManager("controller.invalid", "", "", auth=UniFiAuth(api_key="test-key"))
    connection._initialized = True
    connection._key_mode = True
    network_manager = MagicMock()
    network_manager.get_network_details = AsyncMock(
        return_value={"source_api": "integration", "integration_id": "public-uuid", "_id": None}
    )
    manager = TrafficRouteManager(connection, network_manager=network_manager)

    with pytest.raises(UniFiAuthError, match="Network session authentication"):
        await manager.validate_internet_route_target(VALID_TARGET, "legacy-wan-id")

    network_manager.get_network_details.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejects_internet_route_with_non_wan_target() -> None:
    manager, connection, network_manager = _manager(purpose="remote-user-vpn")

    with pytest.raises(ValueError, match="WAN network"):
        await manager.create_traffic_route(
            {
                "description": "Desktop route",
                "matching_target": "INTERNET",
                "network_id": "vpn-target",
                "target_devices": VALID_TARGET,
                "enabled": True,
            }
        )

    network_manager.get_network_details.assert_awaited_once_with("vpn-target", force_refresh=True)
    connection.request.assert_not_awaited()


@pytest.mark.parametrize("client_mac", ["01:00:5e:00:00:01", "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"])
@pytest.mark.asyncio
async def test_create_rejects_non_unicast_internet_route_client_mac(client_mac: str) -> None:
    manager, connection, network_manager = _manager()

    with pytest.raises(ValueError, match="valid unicast client MAC address"):
        await manager.create_traffic_route(
            {
                "description": "Unsafe route",
                "matching_target": "INTERNET",
                "network_id": "wan-target",
                "target_devices": [{"type": "CLIENT", "client_mac": client_mac}],
                "enabled": True,
            }
        )

    network_manager.get_network_details.assert_not_awaited()
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rejects_disabled_internet_route_with_non_wan_target() -> None:
    manager, connection, _ = _manager(purpose="remote-user-vpn")

    with pytest.raises(ValueError, match="WAN network"):
        await manager.create_traffic_route(
            {
                "description": "Disabled unsafe route",
                "matching_target": "INTERNET",
                "network_id": "vpn-target",
                "target_devices": VALID_TARGET,
                "enabled": False,
            }
        )

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cannot_enable_unsafe_legacy_internet_route() -> None:
    manager, connection, _ = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-unsafe",
            "description": "Unsafe legacy route",
            "matching_target": "INTERNET",
            "network_id": "vpn-target",
            "target_devices": [{"type": "ALL_CLIENTS"}],
            "enabled": False,
        }
    )

    with pytest.raises(ValueError, match="exactly one explicit CLIENT"):
        await manager.update_traffic_route("route-unsafe", enabled=True)

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cannot_enable_multicast_legacy_internet_route() -> None:
    manager, connection, network_manager = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-multicast",
            "description": "Unsafe legacy route",
            "matching_target": "INTERNET",
            "network_id": "wan-target",
            "target_devices": [{"type": "CLIENT", "client_mac": "01:00:5e:00:00:01"}],
            "enabled": False,
        }
    )

    with pytest.raises(ValueError, match="valid unicast client MAC address"):
        await manager.update_traffic_route("route-multicast", enabled=True)

    network_manager.get_network_details.assert_not_awaited()
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_cannot_enable_unsafe_legacy_internet_route() -> None:
    manager, connection, _ = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-unsafe",
            "description": "Unsafe legacy route",
            "matching_target": "INTERNET",
            "network_id": "vpn-target",
            "target_devices": [{"type": "ALL_CLIENTS"}],
            "enabled": False,
        }
    )

    with pytest.raises(ValueError, match="exactly one explicit CLIENT"):
        await manager.toggle_traffic_route("route-unsafe")

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_toggle_revalidates_the_route_refetched_for_mutation() -> None:
    manager, connection, _ = _manager()
    safe_disabled_route = {
        "_id": "route-race",
        "description": "Initially safe route",
        "matching_target": "INTERNET",
        "network_id": "wan-target",
        "target_devices": VALID_TARGET,
        "enabled": False,
    }
    unsafe_disabled_route = {
        **safe_disabled_route,
        "network_id": "vpn-target",
        "target_devices": [{"type": "ALL_CLIENTS"}],
    }
    manager.get_traffic_route_details = AsyncMock(side_effect=[safe_disabled_route, unsafe_disabled_route])

    with pytest.raises(ValueError, match="exactly one explicit CLIENT"):
        await manager.toggle_traffic_route("route-race")

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_ignores_cached_route_before_write() -> None:
    manager, connection, network_manager = _manager()
    stale_cached_route = {
        "_id": "route-fresh",
        "description": "Stale unsafe route",
        "matching_target": "INTERNET",
        "network_id": "vpn-target",
        "target_devices": [{"type": "ALL_CLIENTS"}],
        "enabled": True,
    }
    fresh_controller_route = {
        "_id": "route-fresh",
        "description": "Fresh disabled route",
        "matching_target": "INTERNET",
        "network_id": "wan-target",
        "target_devices": VALID_TARGET,
        "enabled": False,
    }
    connection.get_cached = MagicMock(return_value=[stale_cached_route])
    connection.request = AsyncMock(side_effect=[{"data": [fresh_controller_route]}, {}])

    updated = await manager.update_traffic_route("route-fresh", enabled=False)

    assert updated is True
    connection.get_cached.assert_not_called()
    assert connection.request.await_count == 2
    get_request, put_request = [call.args[0] for call in connection.request.await_args_list]
    assert get_request.method == "get"
    assert get_request.path == "/trafficroutes"
    assert put_request.method == "put"
    assert put_request.data["description"] == "Fresh disabled route"
    network_manager.get_network_details.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_cannot_make_disabled_internet_route_unsafe() -> None:
    manager, connection, _ = _manager(purpose="remote-user-vpn")
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-disabled",
            "description": "Safe disabled route",
            "matching_target": "INTERNET",
            "network_id": "wan-target",
            "target_devices": VALID_TARGET,
            "enabled": False,
        }
    )

    with pytest.raises(ValueError, match="WAN network"):
        await manager.update_traffic_route("route-disabled", network_id="vpn-target")

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_can_retarget_valid_internet_route_without_expanding_scope() -> None:
    manager, connection, network_manager = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-safe",
            "description": "Safe route",
            "matching_target": "INTERNET",
            "network_id": "wan-original",
            "target_devices": VALID_TARGET,
            "enabled": True,
        }
    )
    replacement_target = [{"type": "CLIENT", "client_mac": "12:22:33:44:55:66"}]

    updated = await manager.update_traffic_route(
        "route-safe",
        network_id="wan-target",
        target_devices=replacement_target,
    )

    assert updated is True
    network_manager.get_network_details.assert_awaited_once_with("wan-target", force_refresh=True)
    put_request = connection.request.await_args.args[0]
    assert put_request.method == "put"
    assert put_request.data["network_id"] == "wan-target"
    assert put_request.data["target_devices"] == replacement_target


@pytest.mark.asyncio
async def test_update_cannot_expand_enabled_internet_route() -> None:
    manager, connection, network_manager = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-safe",
            "description": "Safe route",
            "matching_target": "INTERNET",
            "network_id": "wan-target",
            "target_devices": VALID_TARGET,
            "enabled": True,
        }
    )

    with pytest.raises(ValueError, match="exactly one explicit CLIENT"):
        await manager.update_traffic_route(
            "route-safe",
            target_devices=[
                {"type": "CLIENT", "client_mac": "12:22:33:44:55:66"},
                {"type": "CLIENT", "client_mac": "22:33:44:55:66:77"},
            ],
        )

    network_manager.get_network_details.assert_not_awaited()
    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_can_disable_unsafe_legacy_internet_route() -> None:
    manager, connection, network_manager = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-unsafe",
            "description": "Unsafe legacy route",
            "matching_target": "INTERNET",
            "network_id": "vpn-target",
            "target_devices": [{"type": "ALL_CLIENTS"}],
            "enabled": True,
        }
    )

    updated = await manager.update_traffic_route("route-unsafe", enabled=False)

    assert updated is True
    network_manager.get_network_details.assert_not_awaited()
    connection.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_kill_switch_rejects_unsafe_enabled_internet_route() -> None:
    manager, connection, _ = _manager()
    manager.get_traffic_route_details = AsyncMock(
        return_value={
            "_id": "route-unsafe",
            "description": "Unsafe legacy route",
            "matching_target": "INTERNET",
            "network_id": "vpn-target",
            "target_devices": [{"type": "ALL_CLIENTS"}],
            "enabled": True,
        }
    )

    with pytest.raises(ValueError, match="exactly one explicit CLIENT"):
        await manager.update_kill_switch("route-unsafe", enabled=True)

    connection.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_allows_valid_single_client_wan_route() -> None:
    manager, connection, network_manager = _manager()
    payload = {
        "description": "Desktop route",
        "matching_target": "INTERNET",
        "network_id": "wan-target",
        "target_devices": VALID_TARGET,
        "enabled": True,
    }

    created = await manager.create_traffic_route(payload)

    assert created == {"_id": "route-new"}
    network_manager.get_network_details.assert_awaited_once_with("wan-target", force_refresh=True)
    connection.request.assert_awaited_once()


@pytest.mark.parametrize(
    "response",
    [
        {"data": []},
        {},
        {"data": {}},
        {"data": {"description": "missing id"}},
        {"data": {"_id": ""}},
        {"data": {"_id": None}},
        {"data": [{"_id": "route-one"}, {"_id": "route-two"}]},
    ],
)
@pytest.mark.asyncio
async def test_create_rejects_ambiguous_response_without_route_id(response: object) -> None:
    manager, connection, _ = _manager()
    cache = _seed_both_traffic_route_caches(connection)
    connection.request = AsyncMock(return_value=response)

    with pytest.raises(ValueError, match="traffic route create response"):
        await manager.create_traffic_route(VALID_DOMAIN_ROUTE)

    assert cache == {}


class TestTrafficRouteCacheCoherence:
    """Every mutation clears both dictionary and legacy-wrapper route caches."""

    @pytest.mark.asyncio
    async def test_create_invalidates_both_route_cache_representations(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)

        await manager.create_traffic_route(VALID_DOMAIN_ROUTE)

        assert cache == {}

    @pytest.mark.asyncio
    async def test_create_invalidates_route_caches_when_response_is_lost(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        connection.request = AsyncMock(side_effect=RuntimeError("response lost"))

        with pytest.raises(RuntimeError, match="response lost"):
            await manager.create_traffic_route(VALID_DOMAIN_ROUTE)

        assert cache == {}

    @pytest.mark.asyncio
    async def test_update_invalidates_both_route_cache_representations(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        route = {"_id": "route-update", "matching_target": "DOMAIN", "enabled": True}
        connection.request = AsyncMock(side_effect=[{"data": [route]}, {}])

        assert await manager.update_traffic_route("route-update", description="Updated") is True

        assert cache == {}

    @pytest.mark.asyncio
    async def test_update_invalidates_route_caches_when_response_is_lost(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        route = {"_id": "route-update", "matching_target": "DOMAIN", "enabled": True}
        connection.request = AsyncMock(side_effect=[{"data": [route]}, RuntimeError("response lost")])

        with pytest.raises(RuntimeError, match="response lost"):
            await manager.update_traffic_route("route-update", description="Updated")

        assert cache == {}

    @pytest.mark.asyncio
    async def test_toggle_invalidates_both_route_cache_representations(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        route = {"_id": "route-toggle", "matching_target": "DOMAIN", "enabled": True}
        connection.request = AsyncMock(side_effect=[{"data": [route]}, {"data": [route]}, {}])

        assert await manager.toggle_traffic_route("route-toggle") is True

        assert cache == {}

    @pytest.mark.asyncio
    async def test_toggle_invalidates_route_caches_when_response_is_lost(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        route = {"_id": "route-toggle", "matching_target": "DOMAIN", "enabled": True}
        connection.request = AsyncMock(
            side_effect=[{"data": [route]}, {"data": [route]}, RuntimeError("response lost")]
        )

        with pytest.raises(RuntimeError, match="response lost"):
            await manager.toggle_traffic_route("route-toggle")

        assert cache == {}

    @pytest.mark.asyncio
    async def test_kill_switch_update_invalidates_both_route_cache_representations(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        route = {"_id": "route-kill-switch", "matching_target": "DOMAIN", "enabled": True}
        connection.request = AsyncMock(side_effect=[{"data": [route]}, {}])

        assert await manager.update_kill_switch("route-kill-switch", enabled=True) is True

        assert cache == {}

    @pytest.mark.asyncio
    async def test_kill_switch_update_invalidates_route_caches_when_response_is_lost(self) -> None:
        manager, connection, _ = _manager()
        cache = _seed_both_traffic_route_caches(connection)
        route = {"_id": "route-kill-switch", "matching_target": "DOMAIN", "enabled": True}
        connection.request = AsyncMock(side_effect=[{"data": [route]}, RuntimeError("response lost")])

        with pytest.raises(RuntimeError, match="response lost"):
            await manager.update_kill_switch("route-kill-switch", enabled=True)

        assert cache == {}
