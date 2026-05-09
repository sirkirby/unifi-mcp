"""Tests for firewall manager mutation safety.

Verifies that update methods use deepcopy to protect cached .raw
from mutation, and that update_firewall_policy uses the single-policy
endpoint with deep_merge.
"""

import copy
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SAMPLE_ROUTE_RAW = {
    "_id": "route001",
    "enabled": True,
    "description": "Test route",
    "network_id": "net001",
    "interface": "WAN",
    "kill_switch_enabled": False,
    "domains": [
        {"domain": "example.com", "ports": [443, 80]},
        {"domain": "other.com", "ports": [8443]},
    ],
}


def _make_traffic_route(raw: dict | None = None):
    """Create a mock TrafficRoute with the given raw dict."""
    route = MagicMock()
    route.raw = raw if raw is not None else copy.deepcopy(SAMPLE_ROUTE_RAW)
    route.id = route.raw["_id"]
    route.enabled = route.raw.get("enabled", True)
    return route


def _make_mock_connection(routes: list | None = None):
    """Create a mock ConnectionManager pre-wired with get_traffic_routes results."""
    conn = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(return_value={})
    conn.site = "default"
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    return conn


@pytest.fixture
def mock_connection():
    return _make_mock_connection()


@pytest.fixture
def firewall_manager(mock_connection):
    from unifi_core.network.managers.firewall_manager import FirewallManager

    return FirewallManager(mock_connection)


class TestUpdateTrafficRouteMutationSafety:
    """Ensure update_traffic_route does not mutate the cached TrafficRoute.raw."""

    @pytest.mark.asyncio
    async def test_does_not_mutate_cached_route(self, firewall_manager, mock_connection):
        """The cached TrafficRoute.raw must be unchanged after update_traffic_route."""
        route = _make_traffic_route()
        original_raw = copy.deepcopy(route.raw)

        with patch.object(firewall_manager, "get_traffic_routes", new_callable=AsyncMock, return_value=[route]):
            await firewall_manager.update_traffic_route("route001", {"description": "Changed", "enabled": False})

        assert route.raw == original_raw

    @pytest.mark.asyncio
    async def test_happy_path_sends_merged_payload(self, firewall_manager, mock_connection):
        """The API request should contain original fields merged with updates."""
        route = _make_traffic_route()
        updates = {"description": "Updated route", "kill_switch_enabled": True}

        with patch.object(firewall_manager, "get_traffic_routes", new_callable=AsyncMock, return_value=[route]):
            result = await firewall_manager.update_traffic_route("route001", updates)

        assert result is True
        mock_connection.request.assert_called_once()

        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        payload = api_request.data

        # Original fields preserved
        assert payload["_id"] == "route001"
        assert payload["network_id"] == "net001"
        assert payload["interface"] == "WAN"
        # Updates applied
        assert payload["description"] == "Updated route"
        assert payload["kill_switch_enabled"] is True

    @pytest.mark.asyncio
    async def test_does_not_mutate_cached_route_on_api_failure(self, firewall_manager, mock_connection):
        """Even when the API call fails, the cached TrafficRoute.raw must be untouched."""
        route = _make_traffic_route()
        original_raw = copy.deepcopy(route.raw)

        mock_connection.request = AsyncMock(side_effect=Exception("API error"))

        with patch.object(firewall_manager, "get_traffic_routes", new_callable=AsyncMock, return_value=[route]):
            with pytest.raises(Exception, match="API error"):
                await firewall_manager.update_traffic_route("route001", {"description": "Should not persist"})

        assert route.raw == original_raw


# ---------------------------------------------------------------------------
# update_firewall_policy — endpoint and merge tests (issue #124)
# ---------------------------------------------------------------------------

SAMPLE_POLICY_RAW = {
    "_id": "pol001",
    "name": "Test Policy",
    "action": "ALLOW",
    "enabled": True,
    "logging": False,
    "predefined": False,
    "protocol": "all",
    "ip_version": "BOTH",
    "source": {
        "zone_id": "zone-internal",
        "matching_target": "NETWORK",
        "network_ids": ["net001"],
    },
    "destination": {
        "zone_id": "zone-external",
        "matching_target": "ANY",
    },
}


def _make_firewall_policy(raw: dict | None = None):
    """Create a mock FirewallPolicy with the given raw dict."""
    policy = MagicMock()
    policy.raw = raw if raw is not None else copy.deepcopy(SAMPLE_POLICY_RAW)
    policy.id = policy.raw["_id"]
    policy.predefined = policy.raw.get("predefined", False)
    return policy


class TestUpdateFirewallPolicyEndpoint:
    """Ensure update_firewall_policy uses single-policy endpoint, not batch."""

    @pytest.mark.asyncio
    async def test_uses_single_policy_endpoint(self, firewall_manager, mock_connection):
        """PUT should target /firewall-policies/{id}, not /firewall-policies/batch."""
        policy = _make_firewall_policy()

        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[policy]):
            result = await firewall_manager.update_firewall_policy("pol001", {"logging": True})

        assert result is True
        mock_connection.request.assert_called_once()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/firewall-policies/pol001"
        assert api_request.method == "put"

    @pytest.mark.asyncio
    async def test_sends_merged_payload_not_wrapped_in_list(self, firewall_manager, mock_connection):
        """Payload should be a single dict, not a list."""
        policy = _make_firewall_policy()

        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[policy]):
            await firewall_manager.update_firewall_policy("pol001", {"logging": True})

        api_request = mock_connection.request.call_args[0][0]
        payload = api_request.data
        assert isinstance(payload, dict)
        assert payload["logging"] is True
        assert payload["_id"] == "pol001"

    @pytest.mark.asyncio
    async def test_deep_merges_nested_objects(self, firewall_manager, mock_connection):
        """Nested source/destination dicts should be deep-merged, not replaced."""
        policy = _make_firewall_policy()

        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[policy]):
            await firewall_manager.update_firewall_policy("pol001", {"source": {"zone_id": "zone-wan"}})

        api_request = mock_connection.request.call_args[0][0]
        payload = api_request.data
        # Updated key
        assert payload["source"]["zone_id"] == "zone-wan"
        # Sibling keys preserved by deep_merge
        assert payload["source"]["matching_target"] == "NETWORK"
        assert payload["source"]["network_ids"] == ["net001"]

    @pytest.mark.asyncio
    async def test_does_not_mutate_cached_policy(self, firewall_manager, mock_connection):
        """The cached FirewallPolicy.raw must be unchanged after update."""
        policy = _make_firewall_policy()
        original_raw = copy.deepcopy(policy.raw)

        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[policy]):
            await firewall_manager.update_firewall_policy("pol001", {"logging": True})

        assert policy.raw == original_raw


class TestToggleFirewallPolicyPayload:
    """Toggle must PUT a fully-merged object, not a partial {enabled} payload.

    The controller rejects PUTs missing any required field (action,
    ipVersion, name, source, destination, schedule). This is enforced by
    delegating toggle through update_firewall_policy.
    """

    @pytest.mark.asyncio
    async def test_put_payload_includes_all_required_fields(self, firewall_manager, mock_connection):
        policy = _make_firewall_policy()  # raw enabled=True
        policy.enabled = True  # explicit: helper uses MagicMock attrs which are truthy by default

        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[policy]):
            await firewall_manager.toggle_firewall_policy("pol001")

        api_request = mock_connection.request.call_args[0][0]
        payload = api_request.data
        # All controller-required fields present
        for required in ("action", "ip_version", "name", "source", "destination"):
            assert required in payload, f"toggle PUT missing required field '{required}'"
        # The toggled flag is what changed
        assert payload["enabled"] is False
        # Sibling fields preserved
        assert payload["name"] == "Test Policy"
        assert payload["action"] == "ALLOW"
        assert payload["source"]["zone_id"] == "zone-internal"

    @pytest.mark.asyncio
    async def test_uses_single_policy_endpoint(self, firewall_manager, mock_connection):
        policy = _make_firewall_policy()
        policy.enabled = True
        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[policy]):
            await firewall_manager.toggle_firewall_policy("pol001")

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/firewall-policies/pol001"
        assert api_request.method == "put"

    @pytest.mark.asyncio
    async def test_flips_enabled_state(self, firewall_manager, mock_connection):
        disabled = _make_firewall_policy({**SAMPLE_POLICY_RAW, "enabled": False})
        disabled.enabled = False
        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[disabled]):
            await firewall_manager.toggle_firewall_policy("pol001")

        payload = mock_connection.request.call_args[0][0].data
        assert payload["enabled"] is True

    @pytest.mark.asyncio
    async def test_raises_when_policy_missing(self, firewall_manager):
        from unifi_core.exceptions import UniFiNotFoundError

        with patch.object(firewall_manager, "get_firewall_policies", new_callable=AsyncMock, return_value=[]):
            with pytest.raises(UniFiNotFoundError):
                await firewall_manager.toggle_firewall_policy("does-not-exist")


# ---------------------------------------------------------------------------
# ID-lookup iteration robustness — issue #151
#
# `next((x for x in items if x.id == target), None)` over aiounifi item
# objects raises KeyError when any item in the list has a `raw` dict missing
# `_id` (the property does `self.raw["_id"]` directly). Lazy iteration meant
# one malformed item poisoned lookups for every item positioned at-or-after
# it — earlier matches still resolved, later matches returned "not found".
# Lookup paths now use `r.raw.get("_id")` so iteration tolerates malformed
# entries.
# ---------------------------------------------------------------------------

from aiounifi.models.port_forward import PortForward  # noqa: E402
from aiounifi.models.traffic_route import TrafficRoute  # noqa: E402


class TestPortForwardLookupRobustness:
    """get_port_forward_by_id must not be poisoned by a malformed sibling rule."""

    @pytest.mark.asyncio
    async def test_finds_rule_after_malformed_entry(self, firewall_manager):
        """A rule positioned after a malformed (no `_id`) entry must still resolve."""
        good_pre = PortForward({"_id": "pf-pre", "name": "pre"})
        malformed = PortForward({"name": "broken-no-id", "fwd_port": "1", "dst_port": "1"})
        good_post = PortForward({"_id": "pf-post", "name": "post"})

        from unifi_core.exceptions import UniFiNotFoundError

        with patch.object(
            firewall_manager,
            "get_port_forwards",
            new_callable=AsyncMock,
            return_value=[good_pre, malformed, good_post],
        ):
            pre = await firewall_manager.get_port_forward_by_id("pf-pre")
            post = await firewall_manager.get_port_forward_by_id("pf-post")
            with pytest.raises(UniFiNotFoundError):
                await firewall_manager.get_port_forward_by_id("pf-does-not-exist")

        assert pre is good_pre
        assert post is good_post  # would be None before the fix


class TestTrafficRouteLookupRobustness:
    """update_/toggle_ traffic_route must not be poisoned by a malformed sibling route."""

    @pytest.mark.asyncio
    async def test_update_finds_route_after_malformed_entry(self, firewall_manager, mock_connection):
        good_target = TrafficRoute(copy.deepcopy(SAMPLE_ROUTE_RAW))
        malformed = TrafficRoute({"description": "broken-no-id", "enabled": True})

        with patch.object(
            firewall_manager,
            "get_traffic_routes",
            new_callable=AsyncMock,
            return_value=[malformed, good_target],
        ):
            result = await firewall_manager.update_traffic_route("route001", {"description": "Updated"})

        assert result is True
        mock_connection.request.assert_called_once()


# ---------------------------------------------------------------------------
# get_firewall_zones — Network 10.2+ /firewall/zone-matrix support (issue #154)
#
# - Primary path /firewall/zone-matrix succeeds → returns zone metadata with
#   the inter-zone policy-count `data` matrix stripped.
# - Primary path raises → fallback to legacy /firewall/zones; returns its data
#   unmodified.
# - Both paths fail → exception propagates (no silent empty list).
# ---------------------------------------------------------------------------


SAMPLE_ZONE_MATRIX_RESPONSE = [
    {
        "_id": "zone-internal",
        "name": "Internal",
        "zone_key": "internal",
        # Inter-zone policy-count matrix the V2 endpoint embeds per zone.
        "data": [
            {"target_zone_id": "zone-external", "count": 3},
            {"target_zone_id": "zone-vpn", "count": 1},
        ],
    },
    {
        "_id": "zone-external",
        "name": "External",
        "zone_key": "external",
        "data": [
            {"target_zone_id": "zone-internal", "count": 0},
        ],
    },
]


SAMPLE_LEGACY_ZONES_RESPONSE = [
    {"_id": "zone-internal", "name": "Internal", "zone_key": "internal"},
    {"_id": "zone-external", "name": "External", "zone_key": "external"},
]


class TestGetFirewallZones:
    """Cover primary, fallback, and both-fail branches of get_firewall_zones."""

    @pytest.mark.asyncio
    async def test_zone_matrix_primary_strips_data_matrix(self, firewall_manager, mock_connection):
        """Primary /firewall/zone-matrix succeeds; the per-zone `data` matrix is stripped."""
        mock_connection.request = AsyncMock(return_value=copy.deepcopy(SAMPLE_ZONE_MATRIX_RESPONSE))

        zones = await firewall_manager.get_firewall_zones()

        # Only the primary endpoint should have been called.
        assert mock_connection.request.call_count == 1
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/firewall/zone-matrix"

        # Metadata preserved; matrix stripped.
        assert len(zones) == 2
        assert zones[0]["_id"] == "zone-internal"
        assert zones[0]["name"] == "Internal"
        assert zones[0]["zone_key"] == "internal"
        assert "data" not in zones[0]
        assert "data" not in zones[1]

    @pytest.mark.asyncio
    async def test_falls_back_to_legacy_zones_on_primary_failure(self, firewall_manager, mock_connection):
        """When /firewall/zone-matrix raises (e.g. 404 on older firmware), fall back to /firewall/zones."""
        mock_connection.request = AsyncMock(
            side_effect=[
                Exception("404 from /firewall/zone-matrix"),
                copy.deepcopy(SAMPLE_LEGACY_ZONES_RESPONSE),
            ]
        )

        zones = await firewall_manager.get_firewall_zones()

        # Both endpoints attempted, in order.
        assert mock_connection.request.call_count == 2
        first_path = mock_connection.request.call_args_list[0][0][0].path
        second_path = mock_connection.request.call_args_list[1][0][0].path
        assert first_path == "/firewall/zone-matrix"
        assert second_path == "/firewall/zones"

        # Legacy response is returned as-is (no `data` field to strip).
        assert len(zones) == 2
        assert zones[0]["_id"] == "zone-internal"
        assert zones[1]["_id"] == "zone-external"

    @pytest.mark.asyncio
    async def test_raises_when_both_endpoints_fail(self, firewall_manager, mock_connection):
        """When both endpoints fail, the exception propagates — no silent empty list."""
        mock_connection.request = AsyncMock(
            side_effect=[
                Exception("404 from /firewall/zone-matrix"),
                Exception("500 from /firewall/zones"),
            ]
        )

        with pytest.raises(Exception, match="500 from /firewall/zones"):
            await firewall_manager.get_firewall_zones()

        assert mock_connection.request.call_count == 2


# ---------------------------------------------------------------------------
# create_port_forward — V1 POST response shape handling (issue #207)
#
# UDM-SE 8.4.x returns a bare list `[{...}]` from POST /rest/portforward
# while older firmware returns the wrapped shape `{"data": [{...}]}`. The
# manager must extract the created rule from both shapes — see #207.
# ---------------------------------------------------------------------------


SAMPLE_CREATED_PORT_FORWARD = {
    "_id": "abc123",
    "name": "test",
    "dst_port": "80",
    "fwd_port": "80",
    "fwd_ip": "10.0.0.1",
}


class TestCreatePortForwardResponseShapes:
    """Issue #207 — create_port_forward must accept both wrapped and bare-list responses."""

    @pytest.mark.asyncio
    async def test_create_port_forward_handles_wrapped_response_shape(
        self, firewall_manager, mock_connection
    ):
        """Older firmware returns {"data": [{...}]} — manager must extract the rule."""
        mock_connection.request = AsyncMock(
            return_value={"data": [copy.deepcopy(SAMPLE_CREATED_PORT_FORWARD)]}
        )

        result = await firewall_manager.create_port_forward(
            {"name": "test", "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1"}
        )

        assert result is not None
        assert result["_id"] == "abc123"
        assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_create_port_forward_handles_bare_list_response_shape(
        self, firewall_manager, mock_connection
    ):
        """UDM-SE 8.4.x returns [{...}] — manager must extract the rule (regression test for #207)."""
        mock_connection.request = AsyncMock(
            return_value=[copy.deepcopy(SAMPLE_CREATED_PORT_FORWARD)]
        )

        result = await firewall_manager.create_port_forward(
            {"name": "test", "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1"}
        )

        assert result is not None
        assert result["_id"] == "abc123"
        assert result["name"] == "test"
