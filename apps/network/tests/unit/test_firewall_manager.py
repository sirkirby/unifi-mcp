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
    conn.host = "127.0.0.1"
    conn.port = 443
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
# firewall policy ordering — official integration API support
# ---------------------------------------------------------------------------


class TestFirewallPolicyOrdering:
    """Ordering is managed through the official integration API, not index PUTs."""

    class _ResponseContext:
        def __init__(self, response):
            self.response = response

        async def __aenter__(self):
            return self.response

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Response:
        def __init__(self, status=200, json_body=None, json_error=None, text_body=""):
            self.status = status
            self._json_body = json_body
            self._json_error = json_error
            self._text_body = text_body

        async def json(self, content_type=None):
            if self._json_error is not None:
                raise self._json_error
            return self._json_body

        async def text(self):
            return self._text_body

    class _Session:
        def __init__(self, response):
            self.response = response
            self.closed = False

        def request(self, *args, **kwargs):
            return TestFirewallPolicyOrdering._ResponseContext(self.response)

        async def close(self):
            self.closed = True

    @staticmethod
    def _manager_with_integration_response(mock_connection, response):
        from unifi_core.network.managers.firewall_manager import FirewallManager

        session = TestFirewallPolicyOrdering._Session(response)
        auth = MagicMock()
        auth.has_api_key = True
        auth.get_api_key_session = AsyncMock(return_value=session)
        return FirewallManager(mock_connection, auth), session

    @pytest.mark.asyncio
    async def test_ordering_requires_api_key(self, firewall_manager):
        with pytest.raises(RuntimeError, match="requires a UniFi API key"):
            await firewall_manager._request_integration_api("get", "/v1/sites")

    @pytest.mark.asyncio
    async def test_integration_api_reports_non_json_error_body(self, mock_connection):
        response = self._Response(status=502, json_error=ValueError("not json"), text_body="<html>bad gateway</html>")
        manager, session = self._manager_with_integration_response(mock_connection, response)

        with pytest.raises(RuntimeError, match="Integration API returned 502.*bad gateway"):
            await manager._request_integration_api("get", "/v1/sites")

        assert session.closed is True

    @pytest.mark.asyncio
    async def test_integration_api_reports_empty_error_body(self, mock_connection):
        response = self._Response(status=500, json_error=ValueError("not json"), text_body="")
        manager, _session = self._manager_with_integration_response(mock_connection, response)

        with pytest.raises(RuntimeError, match="Integration API returned 500.*<empty body>"):
            await manager._request_integration_api("get", "/v1/sites")

    @pytest.mark.asyncio
    async def test_integration_api_reports_non_json_success_body(self, mock_connection):
        response = self._Response(status=200, json_error=ValueError("not json"), text_body="OK")
        manager, _session = self._manager_with_integration_response(mock_connection, response)

        with pytest.raises(RuntimeError, match="Integration API returned non-JSON response.*OK"):
            await manager._request_integration_api("get", "/v1/sites")

    @pytest.mark.asyncio
    async def test_get_policy_ordering_uses_integration_endpoint(self, firewall_manager):
        firewall_manager._request_integration_api = AsyncMock(
            side_effect=[
                {"data": [{"id": "site-uuid", "name": "default"}]},
                {"data": [{"id": "zone-src", "name": "Internal"}, {"id": "zone-dst", "name": "External"}]},
                {"orderedFirewallPolicyIds": {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}},
            ]
        )

        result = await firewall_manager.get_firewall_policy_ordering("zone-src", "zone-dst")

        assert result["orderedFirewallPolicyIds"]["beforeSystemDefined"] == ["allow"]
        call = firewall_manager._request_integration_api.call_args_list[1]
        assert call.args[1] == "/v1/sites/site-uuid/firewall/zones"
        call = firewall_manager._request_integration_api.call_args_list[2]
        assert call.args[0] == "get"
        assert call.args[1] == "/v1/sites/site-uuid/firewall/policies/ordering"
        assert call.kwargs["params"] == {
            "sourceFirewallZoneId": "zone-src",
            "destinationFirewallZoneId": "zone-dst",
        }

    @pytest.mark.asyncio
    async def test_reorder_policy_ordering_sends_complete_payload(self, firewall_manager):
        firewall_manager._request_integration_api = AsyncMock(
            side_effect=[
                {"data": [{"id": "site-uuid", "name": "default"}]},
                {"data": [{"id": "zone-src", "name": "Internal"}, {"id": "zone-dst", "name": "External"}]},
                {"orderedFirewallPolicyIds": {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}},
                {"orderedFirewallPolicyIds": {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}},
            ]
        )
        ordering = {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}

        result = await firewall_manager.reorder_firewall_policies("zone-src", "zone-dst", ordering)

        assert result["orderedFirewallPolicyIds"] == ordering
        call = firewall_manager._request_integration_api.call_args_list[1]
        assert call.args[1] == "/v1/sites/site-uuid/firewall/zones"
        call = firewall_manager._request_integration_api.call_args_list[2]
        assert call.args[0] == "get"
        assert call.args[1] == "/v1/sites/site-uuid/firewall/policies/ordering"
        call = firewall_manager._request_integration_api.call_args_list[3]
        assert call.args[0] == "put"
        assert call.args[1] == "/v1/sites/site-uuid/firewall/policies/ordering"
        assert call.kwargs["data"] == {"orderedFirewallPolicyIds": ordering}
        firewall_manager._connection._invalidate_cache.assert_any_call(
            "firewall_policy_ordering_zone-src_zone-dst_default"
        )

    @pytest.mark.asyncio
    async def test_reorder_policy_ordering_ignores_cached_ordering_for_validation(self, firewall_manager):
        stale_ordering = {
            "orderedFirewallPolicyIds": {
                "beforeSystemDefined": ["stale-allow"],
                "afterSystemDefined": ["stale-block"],
            }
        }

        def fake_get_cached(key):
            if key == "firewall_policy_ordering_zone-src_zone-dst_default":
                return stale_ordering
            return None

        firewall_manager._connection.get_cached.side_effect = fake_get_cached
        firewall_manager._request_integration_api = AsyncMock(
            side_effect=[
                {"data": [{"id": "site-uuid", "name": "default"}]},
                {"data": [{"id": "zone-src", "name": "Internal"}, {"id": "zone-dst", "name": "External"}]},
                {"orderedFirewallPolicyIds": {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}},
                {"orderedFirewallPolicyIds": {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}},
            ]
        )
        ordering = {"beforeSystemDefined": ["allow"], "afterSystemDefined": ["block"]}

        result = await firewall_manager.reorder_firewall_policies("zone-src", "zone-dst", ordering)

        assert result["orderedFirewallPolicyIds"] == ordering
        calls = firewall_manager._request_integration_api.call_args_list
        assert calls[2].args[0] == "get"
        assert calls[2].args[1] == "/v1/sites/site-uuid/firewall/policies/ordering"
        assert calls[3].args[0] == "put"

    @pytest.mark.asyncio
    async def test_reorder_rejects_duplicate_policy_ids_before_api_call(self, firewall_manager):
        firewall_manager._request_integration_api = AsyncMock()
        ordering = {"beforeSystemDefined": ["allow", "allow"], "afterSystemDefined": ["block"]}

        with pytest.raises(ValueError, match="duplicate policy IDs: allow"):
            await firewall_manager.reorder_firewall_policies("zone-src", "zone-dst", ordering)

        firewall_manager._request_integration_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_reorder_rejects_non_string_policy_ids_before_api_call(self, firewall_manager):
        firewall_manager._request_integration_api = AsyncMock()
        ordering = {"beforeSystemDefined": ["allow", None], "afterSystemDefined": ["block"]}

        with pytest.raises(ValueError, match="non-empty policy ID strings"):
            await firewall_manager.reorder_firewall_policies("zone-src", "zone-dst", ordering)

        firewall_manager._request_integration_api.assert_not_called()

    @pytest.mark.asyncio
    async def test_reorder_rejects_payload_that_drops_current_policy(self, firewall_manager):
        firewall_manager._request_integration_api = AsyncMock(
            side_effect=[
                {"data": [{"id": "site-uuid", "name": "default"}]},
                {"data": [{"id": "zone-src", "name": "Internal"}, {"id": "zone-dst", "name": "External"}]},
                {
                    "orderedFirewallPolicyIds": {
                        "beforeSystemDefined": ["allow-1", "allow-2"],
                        "afterSystemDefined": ["block-1"],
                    }
                },
            ]
        )
        ordering = {"beforeSystemDefined": ["allow-1"], "afterSystemDefined": ["block-1"]}

        with pytest.raises(ValueError, match="Missing: allow-2; unexpected: none"):
            await firewall_manager.reorder_firewall_policies("zone-src", "zone-dst", ordering)

        assert firewall_manager._request_integration_api.call_count == 3
        assert firewall_manager._request_integration_api.call_args_list[-1].args[0] == "get"

    @pytest.mark.asyncio
    async def test_policy_ordering_translates_v2_zone_ids_to_integration_ids(self, firewall_manager):
        firewall_manager._request_integration_api = AsyncMock(
            side_effect=[
                {"data": [{"id": "site-uuid", "name": "default"}]},
                {
                    "data": [
                        {"id": "integration-internal", "name": "Internal"},
                        {"id": "integration-external", "name": "External"},
                    ]
                },
                {"orderedFirewallPolicyIds": {"beforeSystemDefined": [], "afterSystemDefined": []}},
            ]
        )

        with patch.object(
            firewall_manager,
            "get_firewall_zones",
            new_callable=AsyncMock,
            return_value=[
                {"_id": "v2-internal", "name": "Internal", "zone_key": "internal"},
                {"_id": "v2-external", "name": "External", "zone_key": "external"},
            ],
        ):
            await firewall_manager.get_firewall_policy_ordering("v2-internal", "v2-external")

        call = firewall_manager._request_integration_api.call_args_list[2]
        assert call.args[1] == "/v1/sites/site-uuid/firewall/policies/ordering"
        assert call.kwargs["params"] == {
            "sourceFirewallZoneId": "integration-internal",
            "destinationFirewallZoneId": "integration-external",
        }


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
    async def test_create_port_forward_handles_wrapped_response_shape(self, firewall_manager, mock_connection):
        """Older firmware returns {"data": [{...}]} — manager must extract the rule."""
        mock_connection.request = AsyncMock(return_value={"data": [copy.deepcopy(SAMPLE_CREATED_PORT_FORWARD)]})

        result = await firewall_manager.create_port_forward(
            {"name": "test", "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1"}
        )

        assert result is not None
        assert result["_id"] == "abc123"
        assert result["name"] == "test"

    @pytest.mark.asyncio
    async def test_create_port_forward_handles_bare_list_response_shape(self, firewall_manager, mock_connection):
        """UDM-SE 8.4.x returns [{...}] — manager must extract the rule (regression test for #207)."""
        mock_connection.request = AsyncMock(return_value=[copy.deepcopy(SAMPLE_CREATED_PORT_FORWARD)])

        result = await firewall_manager.create_port_forward(
            {"name": "test", "dst_port": "80", "fwd_port": "80", "fwd_ip": "10.0.0.1"}
        )

        assert result is not None
        assert result["_id"] == "abc123"
        assert result["name"] == "test"


# ---------------------------------------------------------------------------
# delete_port_forward — V1 DELETE endpoint + guards
# ---------------------------------------------------------------------------


class TestDeletePortForward:
    """Direct manager coverage for delete_port_forward (issued the V1 DELETE and invalidates cache)."""

    @pytest.mark.asyncio
    async def test_delete_port_forward_success(self, firewall_manager, mock_connection):
        """Happy path: issues DELETE /rest/portforward/<id>, invalidates cache, returns True."""
        mock_connection.request = AsyncMock(return_value={})

        result = await firewall_manager.delete_port_forward("pf_001")

        assert result is True
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.method == "delete"
        assert api_request.path == "/rest/portforward/pf_001"
        mock_connection._invalidate_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_port_forward_not_connected_raises(self, firewall_manager, mock_connection):
        """When the connection can't be established, raise ConnectionError before any request."""
        mock_connection.ensure_connected = AsyncMock(return_value=False)

        with pytest.raises(ConnectionError):
            await firewall_manager.delete_port_forward("pf_001")

        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_port_forward_reraises_request_error(self, firewall_manager, mock_connection):
        """A controller/request error propagates (the manager re-raises)."""
        mock_connection.request = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            await firewall_manager.delete_port_forward("pf_001")
