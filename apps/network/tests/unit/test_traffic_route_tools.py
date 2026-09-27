"""Tests for unifi_update_traffic_route editing route-match fields (target_devices, domains, etc.)."""

import copy
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiAuthError, UniFiNotFoundError
from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager, TrafficRoutePreflightError
from unifi_core.network.models.traffic_routes import TrafficRouteValidationError

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_ROUTE = {
    "_id": "route-001",
    "description": "secondlife-staging.com",
    "enabled": True,
    "kill_switch_enabled": False,
    "network_id": "net-vpn",
    "matching_target": "DOMAIN",
    "domains": [{"domain": "secondlife-staging.com", "ports": [], "port_ranges": []}],
    "ip_addresses": [],
    "ip_ranges": [],
    "regions": [],
    "target_devices": [{"type": "CLIENT", "client_mac": "dc:cc:e6:66:86:2b"}],
    "next_hop": "",
}

NEW_TARGETS = [{"type": "CLIENT", "client_mac": "fe:38:bd:88:e9:c5"}]


def _mock_manager():
    """Return a mock TrafficRouteManager with async get/update methods."""
    mgr = MagicMock()
    mgr.get_traffic_route_details = AsyncMock(return_value=copy.deepcopy(SAMPLE_ROUTE))
    mgr.update_traffic_route = AsyncMock(return_value=True)
    mgr.create_traffic_route = AsyncMock(return_value={"_id": "route-new", "description": "YouTube via VPN"})
    mgr.toggle_traffic_route = AsyncMock(return_value=True)
    mgr.validate_internet_route_target = AsyncMock(return_value=None)
    return mgr


def _reject_internet_target(mgr, message: str) -> None:
    """Configure the manager mock to return a canonical validation error."""
    mgr.validate_internet_route_target = AsyncMock(side_effect=TrafficRouteValidationError(message))


class TestCreateTrafficRoute:
    @pytest.mark.asyncio
    async def test_ip_preview_and_confirm_emit_controller_ip_versions(self):
        mgr = _mock_manager()
        selectors = {
            "ip_addresses": [{"ip_or_subnet": "203.0.113.10", "ip_version": "IPV4"}],
            "ip_ranges": [{"ip_start": "2001:db8::1", "ip_stop": "2001:db8::9", "ip_version": "v6"}],
        }
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            preview = await create_traffic_route(name="IP route", matching_target="IP", network_id="vpn-1", **selectors)
            applied = await create_traffic_route(
                name="IP route", matching_target="IP", network_id="vpn-1", confirm=True, **selectors
            )

        assert applied["success"] is True
        for payload in (preview["preview"]["will_create"], mgr.create_traffic_route.await_args.args[0]):
            assert payload["ip_addresses"][0]["ip_version"] == "v4"
            assert payload["ip_ranges"][0]["ip_version"] == "v6"
            assert "ip_version" not in payload

    @pytest.mark.parametrize(
        "selector",
        [
            {"matching_target": "DOMAIN", "domains": [{"domain": "example.com"}]},
            {"matching_target": "IP", "ip_addresses": [{"ip_or_subnet": "203.0.113.1", "ip_version": "IPV4"}]},
            {"matching_target": "REGION", "regions": ["US"]},
        ],
    )
    @pytest.mark.asyncio
    async def test_omitted_targets_keep_mcp_all_clients_default_in_preview_and_write(self, selector):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            preview = await create_traffic_route(name="Route", network_id="vpn-1", **selector)
            applied = await create_traffic_route(name="Route", network_id="vpn-1", confirm=True, **selector)

        assert preview["preview"]["will_create"]["target_devices"] == [{"type": "ALL_CLIENTS"}]
        assert applied["success"] is True
        assert mgr.create_traffic_route.await_args.args[0]["target_devices"] == [{"type": "ALL_CLIENTS"}]

    @pytest.mark.asyncio
    async def test_internet_omitted_targets_never_default_or_post(self):
        connection = MagicMock()
        connection.site = "default"
        connection.request = AsyncMock(return_value={"data": {"_id": "route-new"}})
        network_manager = MagicMock()
        network_manager.get_network_details = AsyncMock(return_value={"purpose": "wan"})
        mgr = TrafficRouteManager(connection, network_manager)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            preview = await create_traffic_route(name="Route", matching_target="INTERNET", network_id="wan-1")
            applied = await create_traffic_route(
                name="Route", matching_target="INTERNET", network_id="wan-1", confirm=True
            )

        for result in (preview, applied):
            assert result["success"] is False
            assert "explicit CLIENT" in result["error"]
        network_manager.get_network_details.assert_not_awaited()
        connection.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unknown_nested_domain_key_rejected_with_real_manager_before_post(self):
        connection = MagicMock()
        connection.site = "default"
        connection.request = AsyncMock(return_value={"data": {"_id": "route-new"}})
        network_manager = MagicMock()
        network_manager.get_network_details = AsyncMock(return_value={"purpose": "wan"})
        manager = TrafficRouteManager(connection, network_manager)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", manager):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Example",
                matching_target="DOMAIN",
                network_id="vpn-1",
                domains=[{"domain": "example.com", "port": 443}],
                confirm=True,
            )

        assert result["success"] is False
        assert "port" in result["error"]
        connection.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_nested_create_preview_rejected_before_wan_lookup(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Example",
                matching_target="DOMAIN",
                network_id="vpn-1",
                domains=[{"domain": "example.com", "ports": [True]}],
            )

        assert result["success"] is False
        assert "integer ports" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_domain_route_preview_does_not_mutate(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="YouTube via VPN",
                matching_target="DOMAIN",
                network_id="vpn-albania",
                domains=[{"domain": "youtube.com", "ports": [], "port_ranges": []}],
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["will_create"]["matching_target"] == "DOMAIN"
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_domain_route_confirm_posts_normalized_payload(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="YouTube via VPN",
                matching_target="DOMAIN",
                network_id="vpn-albania",
                domains=[{"domain": "youtube.com"}],
                target_devices=[{"type": "ALL_CLIENTS"}],
                kill_switch_enabled=True,
                confirm=True,
            )

        assert result["success"] is True
        assert result["data"]["id"] == "route-new"
        assert result["data"]["name"] == "YouTube via VPN"
        assert "route_id" not in result
        mgr.create_traffic_route.assert_awaited_once_with(
            {
                "description": "YouTube via VPN",
                "matching_target": "DOMAIN",
                "network_id": "vpn-albania",
                "domains": [{"domain": "youtube.com", "ports": [], "port_ranges": []}],
                "target_devices": [{"type": "ALL_CLIENTS"}],
                "kill_switch_enabled": True,
                "enabled": True,
                "ip_addresses": [],
                "ip_ranges": [],
                "regions": [],
                "next_hop": "",
            }
        )

    @pytest.mark.asyncio
    async def test_confirmed_create_warns_before_retry_after_unknown_outcome(self):
        mgr = _mock_manager()
        mgr.create_traffic_route = AsyncMock(side_effect=TimeoutError("response lost"))
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="YouTube via VPN",
                matching_target="DOMAIN",
                network_id="vpn-albania",
                domains=[{"domain": "youtube.com"}],
                confirm=True,
            )

        assert result["success"] is False
        assert "List routes before retrying" in result["error"]
        assert "response lost" not in result["error"]

    @pytest.mark.asyncio
    async def test_confirmed_create_reports_preflight_failure_without_uncertainty(self):
        mgr = _mock_manager()
        mgr.create_traffic_route = AsyncMock(side_effect=TrafficRoutePreflightError("Invalid client target."))
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Desktop via WAN2",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=[{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}],
                confirm=True,
            )

        assert result == {"success": False, "error": "Failed to create traffic route: Invalid client target."}

    @pytest.mark.parametrize("confirm", [False, True])
    @pytest.mark.asyncio
    async def test_empty_target_devices_are_rejected_instead_of_widening_scope(self, confirm):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Explicitly empty targets",
                matching_target="DOMAIN",
                network_id="vpn-albania",
                domains=[{"domain": "youtube.com"}],
                target_devices=[],
                confirm=confirm,
            )

        assert result["success"] is False
        assert "target_devices" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_domain_route_rejects_missing_domains(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Unsafe route",
                matching_target="DOMAIN",
                network_id="vpn-albania",
                confirm=True,
            )

        assert result["success"] is False
        assert "domains" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_preview_delegates_to_canonical_manager_validation(self):
        mgr = _mock_manager()
        target = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Desktop via WAN2",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=target,
                kill_switch_enabled=True,
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["will_create"]["matching_target"] == "INTERNET"
        assert result["preview"]["will_create"]["target_devices"] == target
        mgr.validate_internet_route_target.assert_awaited_once_with(target, "wan-att")
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_preview_requires_network_session(self):
        mgr = _mock_manager()
        mgr.validate_internet_route_target = AsyncMock(side_effect=UniFiAuthError("key only"))
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Desktop via WAN2",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=[{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}],
            )

        assert result["success"] is False
        assert "Network session authentication" in result["error"]
        assert "key only" not in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_preview_with_valid_target(self):
        mgr = _mock_manager()
        target = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Desktop via WAN2",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=target,
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        mgr.validate_internet_route_target.assert_awaited_once_with(target, "wan-att")
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_rejects_non_wan_target(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes can target only a verified WAN network")
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Unsafe route",
                matching_target="INTERNET",
                network_id="vpn-route",
                target_devices=[{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}],
            )

        assert result["success"] is False
        assert "WAN network" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_rejects_all_clients_target(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require exactly one explicit CLIENT target")
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Unsafe route",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=[{"type": "ALL_CLIENTS"}],
            )

        assert result["success"] is False
        assert "explicit CLIENT" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.parametrize("client_mac", ["01:00:5e:00:00:01", "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00"])
    @pytest.mark.asyncio
    async def test_internet_route_rejects_non_unicast_client_mac(self, client_mac):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require a valid unicast client MAC address")
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Unsafe route",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=[{"type": "CLIENT", "client_mac": client_mac}],
            )

        assert result["success"] is False
        assert "valid unicast client MAC" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_rejects_invalid_client_mac(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require a valid unicast client MAC address")
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import create_traffic_route

            result = await create_traffic_route(
                name="Unsafe route",
                matching_target="INTERNET",
                network_id="wan-att",
                target_devices=[{"type": "CLIENT", "client_mac": "not-a-mac"}],
            )

        assert result["success"] is False
        assert "valid client_mac" in result["error"]
        mgr.create_traffic_route.assert_not_awaited()


# ---------------------------------------------------------------------------
# Preview / apply for target_devices (the headline use case: swapping a device)
# ---------------------------------------------------------------------------


class TestUpdateTrafficRouteTargets:
    @pytest.mark.asyncio
    async def test_vanished_wan_during_confirm_reports_target_network_not_found(self):
        connection = MagicMock()
        connection.site = "default"
        connection.request = AsyncMock(return_value={})
        network_manager = MagicMock()
        network_manager.get_network_details = AsyncMock(
            side_effect=[{"purpose": "wan"}, UniFiNotFoundError("network", "wan-gone")]
        )
        manager = TrafficRouteManager(connection, network_manager)
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["network_id"] = "wan-old"
        manager.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", manager):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", network_id="wan-gone", confirm=True)

        assert result["success"] is False
        assert "Target network was not found" in result["error"]
        assert "Traffic route was not found" not in result["error"]
        connection.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_target_devices_preview_shows_current_and_proposed(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", target_devices=NEW_TARGETS, confirm=False)

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["current"]["target_devices"] == SAMPLE_ROUTE["target_devices"]
        assert result["preview"]["proposed"]["target_devices"] == NEW_TARGETS
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_target_devices_apply_forwards_to_manager(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", target_devices=NEW_TARGETS, confirm=True)

        assert result["success"] is True
        mgr.update_traffic_route.assert_awaited_once_with("route-001", target_devices=NEW_TARGETS)

    @pytest.mark.asyncio
    async def test_internet_route_target_network_update_forwards_verified_wan(self):
        mgr = _mock_manager()
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["target_devices"] = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", network_id="wan-sonic", confirm=True)

        assert result["success"] is True
        mgr.update_traffic_route.assert_awaited_once_with("route-001", network_id="wan-sonic")
        mgr.validate_internet_route_target.assert_awaited_once_with(current["target_devices"], "wan-sonic")

    @pytest.mark.asyncio
    async def test_internet_route_target_device_update_forwards_single_valid_client(self):
        mgr = _mock_manager()
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["network_id"] = "wan-sonic"
        current["target_devices"] = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        replacement = [{"type": "CLIENT", "client_mac": "12:22:33:44:55:66"}]
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", target_devices=replacement, confirm=True)

        assert result["success"] is True
        mgr.update_traffic_route.assert_awaited_once_with("route-001", target_devices=replacement)
        mgr.validate_internet_route_target.assert_awaited_once_with(replacement, "wan-sonic")

    @pytest.mark.asyncio
    async def test_internet_route_target_device_update_rejects_non_unicast_client(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require a valid unicast client MAC address")
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["network_id"] = "wan-sonic"
        current["target_devices"] = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001",
                target_devices=[{"type": "CLIENT", "client_mac": "01:00:5e:00:00:01"}],
                confirm=True,
            )

        assert result["success"] is False
        assert "valid unicast client MAC" in result["error"]
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_combined_target_update_forwards_only_valid_final_scope(self):
        mgr = _mock_manager()
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["network_id"] = "wan-att"
        current["target_devices"] = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        replacement = [{"type": "CLIENT", "client_mac": "12:22:33:44:55:66"}]
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001",
                target_devices=replacement,
                network_id="wan-sonic",
                confirm=True,
            )

        assert result["success"] is True
        mgr.update_traffic_route.assert_awaited_once_with(
            "route-001",
            target_devices=replacement,
            network_id="wan-sonic",
        )
        mgr.validate_internet_route_target.assert_awaited_once_with(replacement, "wan-sonic")

    @pytest.mark.asyncio
    async def test_internet_route_target_network_update_rejects_non_wan(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes can target only a verified WAN network")
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["target_devices"] = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", network_id="vpn-route", confirm=True)

        assert result["success"] is False
        assert "WAN network" in result["error"]
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_internet_route_target_device_update_rejects_all_clients(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require exactly one explicit CLIENT target")
        current = copy.deepcopy(SAMPLE_ROUTE)
        current["matching_target"] = "INTERNET"
        current["network_id"] = "wan-sonic"
        current["target_devices"] = [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}]
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001",
                target_devices=[{"type": "ALL_CLIENTS"}],
                confirm=True,
            )

        assert result["success"] is False
        assert "explicit CLIENT" in result["error"]
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enabling_unsafe_internet_route_is_rejected(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require exactly one explicit CLIENT target")
        current = copy.deepcopy(SAMPLE_ROUTE)
        current.update(
            {
                "enabled": False,
                "matching_target": "INTERNET",
                "network_id": "vpn-route",
                "target_devices": [{"type": "ALL_CLIENTS"}],
            }
        )
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", enabled=True, confirm=True)

        assert result["success"] is False
        assert "explicit CLIENT" in result["error"]
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_route_match_fields_forwarded(self):
        mgr = _mock_manager()
        new_domains = [{"domain": "dev.secondlife.io", "ports": [], "port_ranges": []}]
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001",
                domains=new_domains,
                regions=[],
                next_hop="10.0.0.1",
                confirm=True,
            )

        assert result["success"] is True
        mgr.update_traffic_route.assert_awaited_once_with(
            "route-001", domains=new_domains, regions=[], next_hop="10.0.0.1"
        )

    @pytest.mark.asyncio
    async def test_enabled_only_still_works(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", enabled=False, confirm=True)

        assert result["success"] is True
        mgr.update_traffic_route.assert_awaited_once_with("route-001", enabled=False)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestUpdateTrafficRouteValidation:
    @pytest.mark.asyncio
    async def test_confirmed_invalid_update_uses_real_manager_validation_error(self):
        connection = MagicMock()
        connection.site = "default"
        connection.request = AsyncMock(return_value={})
        network_manager = MagicMock()
        manager = TrafficRouteManager(connection, network_manager)
        manager.get_traffic_route_details = AsyncMock(return_value=copy.deepcopy(SAMPLE_ROUTE))
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", manager):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001", domains=[{"domain": "example.com", "ports": [True]}], confirm=True
            )

        assert result["success"] is False
        assert "integer ports" in result["error"]
        assert "connectivity" not in result["error"]
        connection.request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disabling_with_equivalent_mac_skips_preview_wan_lookup(self):
        mgr = _mock_manager()
        current = copy.deepcopy(SAMPLE_ROUTE)
        current.update(
            {
                "matching_target": "internet",
                "network_id": "legacy-vpn",
                "target_devices": [{"type": "CLIENT", "client_mac": "AA-BB-CC-DD-EE-FE"}],
            }
        )
        mgr.get_traffic_route_details = AsyncMock(return_value=current)
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001",
                enabled=False,
                target_devices=[{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:fe"}],
            )

        assert result["success"] is True
        mgr.validate_internet_route_target.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_invalid_nested_update_preview_returns_validation_error(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", domains=[{"domain": "example.com", "ports": [True]}])

        assert result["success"] is False
        assert "integer ports" in result["error"]
        assert "connectivity" not in result["error"]
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_arbitrary_controller_value_error_text_is_not_returned(self):
        mgr = _mock_manager()
        mgr.get_traffic_route_details = AsyncMock(side_effect=ValueError("controller-secret-value"))
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", enabled=False)

        assert result["success"] is False
        assert "controller-secret-value" not in result["error"]

    @pytest.mark.asyncio
    async def test_no_fields_provided_errors(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", confirm=True)

        assert result["success"] is False
        assert "At least one updatable field" in result["error"]
        # Should fail fast without touching the controller.
        mgr.get_traffic_route_details.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_target_devices_must_be_list(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route("route-001", target_devices={"type": "ALL_CLIENTS"}, confirm=True)

        assert result["success"] is False
        assert "must be a list" in result["error"]
        mgr.update_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_target_devices_entry_requires_type(self):
        mgr = _mock_manager()
        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import update_traffic_route

            result = await update_traffic_route(
                "route-001", target_devices=[{"client_mac": "aa:bb:cc:dd:ee:ff"}], confirm=True
            )

        assert result["success"] is False
        assert "must be an object with a 'type'" in result["error"]
        mgr.update_traffic_route.assert_not_awaited()


# ---------------------------------------------------------------------------
# Toggle Internet-route safety
# ---------------------------------------------------------------------------


class TestToggleInternetRouteSafety:
    @pytest.mark.asyncio
    async def test_missing_route_returns_explicit_not_found_response(self):
        mgr = _mock_manager()
        mgr.get_traffic_route_details = AsyncMock(side_effect=UniFiNotFoundError("traffic_route", "route-missing"))

        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import toggle_traffic_route

            result = await toggle_traffic_route("route-missing", confirm=True)

        assert result == {"success": False, "error": "Traffic route was not found."}
        mgr.toggle_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enabling_unsafe_internet_route_is_rejected(self):
        mgr = _mock_manager()
        _reject_internet_target(mgr, "INTERNET Traffic Routes require exactly one explicit CLIENT target")
        current = copy.deepcopy(SAMPLE_ROUTE)
        current.update(
            {
                "enabled": False,
                "matching_target": "INTERNET",
                "network_id": "vpn-route",
                "target_devices": [{"type": "ALL_CLIENTS"}],
            }
        )
        mgr.get_traffic_route_details = AsyncMock(return_value=current)

        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import toggle_traffic_route

            result = await toggle_traffic_route("route-001", confirm=True)

        assert result["success"] is False
        assert "explicit CLIENT" in result["error"]
        mgr.toggle_traffic_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_enabling_safe_internet_route_validates_wan_then_toggles(self):
        mgr = _mock_manager()
        current = copy.deepcopy(SAMPLE_ROUTE)
        current.update(
            {
                "enabled": False,
                "matching_target": "INTERNET",
                "network_id": "wan-att",
                "target_devices": [{"type": "CLIENT", "client_mac": "aa:bb:cc:dd:ee:ff"}],
            }
        )
        mgr.get_traffic_route_details = AsyncMock(return_value=current)

        with patch("unifi_network_mcp.tools.traffic_routes.traffic_route_manager", mgr):
            from unifi_network_mcp.tools.traffic_routes import toggle_traffic_route

            result = await toggle_traffic_route("route-001", confirm=True)

        assert result["success"] is True
        assert "Read route details to confirm" in result["message"]
        mgr.get_traffic_route_details.assert_awaited_once_with("route-001", force_refresh=True)
        mgr.validate_internet_route_target.assert_awaited_once_with(current["target_devices"], "wan-att")
        mgr.toggle_traffic_route.assert_awaited_once_with("route-001")
