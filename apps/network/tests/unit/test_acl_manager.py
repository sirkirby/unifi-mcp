"""Tests for the AclManager class.

This module tests MAC ACL rule operations (Policy Engine).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

CALLS = [
    lambda m: m.get_acl_rules(),
    lambda m: m.get_acl_rule_by_id("r1"),
    lambda m: m.update_acl_rule("r1", {"name": "Test"}),
    lambda m: m.delete_acl_rule("r1"),
]


class TestAclManager:
    """Tests for the AclManager class."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        conn.ensure_connected = AsyncMock(return_value=True)
        return conn

    @pytest.fixture
    def acl_manager(self, mock_connection):
        """Create an AclManager with mocked connection."""
        from unifi_core.network.managers.acl_manager import AclManager

        return AclManager(mock_connection)

    # ---- get_acl_rules ----

    @pytest.mark.asyncio
    async def test_get_acl_rules_returns_list(self, acl_manager, mock_connection):
        """Test get_acl_rules returns a list of rules."""
        mock_rules = [
            {"_id": "r1", "name": "Allow A", "action": "ALLOW", "mac_acl_network_id": "net1"},
            {"_id": "r2", "name": "Block All", "action": "BLOCK", "mac_acl_network_id": "net1"},
        ]
        mock_connection.request.return_value = mock_rules

        rules = await acl_manager.get_acl_rules()

        assert len(rules) == 2
        assert rules[0]["name"] == "Allow A"
        mock_connection._update_cache.assert_called_once()
        assert mock_connection.request.call_args[0][0].path == "/acl-rules"

    @pytest.mark.asyncio
    async def test_get_acl_rules_filters_by_network(self, acl_manager, mock_connection):
        """Test get_acl_rules filters by network_id."""
        mock_rules = [
            {"_id": "r1", "name": "Rule Net1", "mac_acl_network_id": "net1"},
            {"_id": "r2", "name": "Rule Net2", "mac_acl_network_id": "net2"},
            {"_id": "r3", "name": "Rule Net1 Again", "mac_acl_network_id": "net1"},
        ]
        mock_connection.request.return_value = mock_rules

        rules = await acl_manager.get_acl_rules(network_id="net1")

        assert len(rules) == 2
        assert all(r["mac_acl_network_id"] == "net1" for r in rules)

    @pytest.mark.asyncio
    async def test_get_acl_rules_uses_cache(self, acl_manager, mock_connection):
        """Test get_acl_rules returns cached data when available."""
        cached = [{"_id": "cached", "name": "Cached Rule"}]
        mock_connection.get_cached.return_value = cached

        rules = await acl_manager.get_acl_rules()

        assert rules == cached
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", CALLS)
    async def test_api_error_propagates(self, acl_manager, mock_connection, call):
        """API errors propagate from every manager operation."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            await call(acl_manager)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", CALLS)
    async def test_not_connected_raises(self, acl_manager, mock_connection, call):
        """Every manager operation raises when not connected, without sending a request."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await call(acl_manager)

        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_acl_rules_handles_dict_response(self, acl_manager, mock_connection):
        """Test get_acl_rules handles dict response with data key."""
        mock_connection.request.return_value = {"data": [{"_id": "r1", "name": "Rule"}]}

        rules = await acl_manager.get_acl_rules()

        assert len(rules) == 1

    # ---- get_acl_rule_by_id ----

    @pytest.mark.asyncio
    async def test_get_acl_rule_by_id_found(self, acl_manager, mock_connection):
        """Test get_acl_rule_by_id returns rule when found via list-then-filter."""
        mock_connection.request.return_value = [
            {"_id": "r1", "name": "Test Rule"},
            {"_id": "r2", "name": "Other Rule"},
        ]

        rule = await acl_manager.get_acl_rule_by_id("r1")

        assert rule is not None
        assert rule["name"] == "Test Rule"
        # list-then-filter: GET /acl-rules/{id} returns 405
        assert mock_connection.request.call_args[0][0].path == "/acl-rules"

    @pytest.mark.asyncio
    async def test_get_acl_rule_by_id_not_found(self, acl_manager, mock_connection):
        """Test get_acl_rule_by_id raises UniFiNotFoundError when ID not in list."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = [{"_id": "r1", "name": "Test Rule"}]

        with pytest.raises(UniFiNotFoundError):
            await acl_manager.get_acl_rule_by_id("nonexistent")

    # ---- create_acl_rule ----

    @pytest.mark.asyncio
    async def test_create_acl_rule_success(self, acl_manager, mock_connection):
        """Test create_acl_rule with valid data."""
        rule_data = {
            "name": "New Rule",
            "acl_index": 5,
            "action": "ALLOW",
            "mac_acl_network_id": "net1",
            "type": "MAC",
            "traffic_source": {"type": "CLIENT_MAC", "specific_mac_addresses": ["aa:bb:cc:dd:ee:ff"]},
            "traffic_destination": {"type": "CLIENT_MAC", "specific_mac_addresses": []},
        }
        mock_connection.request.return_value = {"_id": "new1", **rule_data}

        result = await acl_manager.create_acl_rule(rule_data)

        assert result is not None
        assert result["_id"] == "new1"
        mock_connection._invalidate_cache.assert_called()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/acl-rules"
        assert api_request.method == "post"

    @pytest.mark.asyncio
    async def test_create_acl_rule_missing_required_keys(self, acl_manager, mock_connection):
        """Test create_acl_rule returns None when required keys are missing."""
        result = await acl_manager.create_acl_rule({"name": "Incomplete"})

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_acl_rule_not_connected(self, acl_manager, mock_connection):
        """Test create_acl_rule returns None when not connected."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(Exception):
            await acl_manager.create_acl_rule(
                {
                    "name": "Test",
                    "acl_index": 0,
                    "action": "ALLOW",
                    "mac_acl_network_id": "net1",
                    "type": "MAC",
                }
            )

    @pytest.mark.asyncio
    async def test_create_acl_rule_handles_error(self, acl_manager, mock_connection):
        """Test create_acl_rule returns None on API error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await acl_manager.create_acl_rule(
                {
                    "name": "Test",
                    "acl_index": 0,
                    "action": "ALLOW",
                    "mac_acl_network_id": "net1",
                    "type": "MAC",
                }
            )

    @pytest.mark.asyncio
    async def test_create_acl_rule_handles_data_wrapper(self, acl_manager, mock_connection):
        """Test create_acl_rule handles response with data key."""
        mock_connection.request.return_value = {"data": {"_id": "new1", "name": "Test"}}

        result = await acl_manager.create_acl_rule(
            {
                "name": "Test",
                "acl_index": 0,
                "action": "ALLOW",
                "mac_acl_network_id": "net1",
                "type": "MAC",
            }
        )

        assert result == {"_id": "new1", "name": "Test"}

    # ---- update_acl_rule ----

    @pytest.mark.asyncio
    async def test_update_acl_rule_fetches_and_merges(self, acl_manager, mock_connection):
        """Test update_acl_rule fetches current rule, merges updates, PUTs full object."""
        existing_rule = {
            "_id": "r1",
            "name": "Original",
            "acl_index": 5,
            "action": "ALLOW",
            "enabled": True,
            "mac_acl_network_id": "net1",
            "type": "MAC",
            "traffic_source": {"type": "CLIENT_MAC", "specific_mac_addresses": []},
            "traffic_destination": {"type": "CLIENT_MAC", "specific_mac_addresses": []},
        }
        mock_connection.request.side_effect = [
            [existing_rule],  # LIST (for get_acl_rule_by_id)
            {},  # PUT (update)
        ]

        result = await acl_manager.update_acl_rule("r1", {"name": "Renamed", "enabled": False})

        assert result["name"] == "Renamed"
        assert result["enabled"] is False
        # Verify PUT was called with merged data
        put_call = mock_connection.request.call_args_list[1]
        put_request = put_call[0][0]
        assert put_request.method == "put"
        assert put_request.path == "/acl-rules/r1"
        mock_connection._invalidate_cache.assert_called()
        assert put_request.data["name"] == "Renamed"
        assert put_request.data["enabled"] is False
        # Original fields preserved
        assert put_request.data["acl_index"] == 5
        assert put_request.data["action"] == "ALLOW"
        assert put_request.data["mac_acl_network_id"] == "net1"

    @pytest.mark.asyncio
    async def test_update_acl_rule_not_found(self, acl_manager, mock_connection):
        """Test update_acl_rule raises UniFiNotFoundError when rule missing."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await acl_manager.update_acl_rule("nonexistent", {"name": "Test"})

    @pytest.mark.asyncio
    async def test_update_acl_rule_empty_update(self, acl_manager, mock_connection):
        """Test update_acl_rule with empty update data returns existing without PUT."""
        existing = {"_id": "r1", "name": "Original"}
        mock_connection.request.return_value = [existing]

        result = await acl_manager.update_acl_rule("r1", {})

        assert result == existing
        # Only the GET (existence check) ran; no PUT.
        assert mock_connection.request.call_count == 1

    # ---- delete_acl_rule ----

    @pytest.mark.asyncio
    async def test_delete_acl_rule_success(self, acl_manager, mock_connection):
        """Test delete_acl_rule with valid ID."""
        mock_connection.request.return_value = {}

        result = await acl_manager.delete_acl_rule("r1")

        assert result is True
        mock_connection._invalidate_cache.assert_called()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/acl-rules/r1"
        assert api_request.method == "delete"

    # ---- API path verification ----

    # ---- update_acl_rule: mask-clear sentinel handling (real pop path) ----

    @pytest.mark.asyncio
    async def test_update_clear_idempotent_no_existing_mask(self, acl_manager, mock_connection):
        """Clearing a side that has no mask is a harmless no-op (no error, MACs intact)."""
        existing = {
            "_id": "r1",
            "name": "R",
            "traffic_source": {"specific_mac_addresses": ["aa:bb:cc:dd:ee:ff"], "type": "CLIENT_MAC"},
            "traffic_destination": {"specific_mac_addresses": [], "type": "CLIENT_MAC"},
        }
        mock_connection.request.side_effect = [[existing], {}]
        result = await acl_manager.update_acl_rule("r1", {"traffic_source": {"mac_mask": None, "type": "CLIENT_MAC"}})
        assert "mac_mask" not in result["traffic_source"]
        assert result["traffic_source"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]

    @pytest.mark.asyncio
    async def test_update_clear_both_sides(self, acl_manager, mock_connection):
        """Clearing both sides in one update pops both masks."""
        existing = {
            "_id": "r1",
            "name": "R",
            "traffic_source": {
                "mac_mask": "ff:ff:00:00:00:00",
                "specific_mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "type": "CLIENT_MAC",
            },
            "traffic_destination": {
                "mac_mask": "ff:ff:ff:00:00:00",
                "specific_mac_addresses": ["01:00:5e:00:00:00"],
                "type": "CLIENT_MAC",
            },
        }
        mock_connection.request.side_effect = [[existing], {}]
        result = await acl_manager.update_acl_rule(
            "r1",
            {
                "traffic_source": {"mac_mask": None, "type": "CLIENT_MAC"},
                "traffic_destination": {"mac_mask": None, "type": "CLIENT_MAC"},
            },
        )
        assert "mac_mask" not in result["traffic_source"]
        assert "mac_mask" not in result["traffic_destination"]
        assert result["traffic_destination"]["specific_mac_addresses"] == ["01:00:5e:00:00:00"]

    @pytest.mark.asyncio
    async def test_update_clear_does_not_mutate_aliased_untouched_side(self, acl_manager, mock_connection):
        """Regression: a destination-only update must not pop the source side, even if the (aliased,
        cached) source dict happens to hold mac_mask=None — popping there would corrupt the cache."""
        existing = {
            "_id": "r1",
            "name": "R",
            "traffic_source": {"mac_mask": None, "specific_mac_addresses": [], "type": "CLIENT_MAC"},
            "traffic_destination": {
                "mac_mask": "ff:ff:ff:00:00:00",
                "specific_mac_addresses": ["01:00:5e:00:00:00"],
                "type": "CLIENT_MAC",
            },
        }
        mock_connection.request.side_effect = [[existing], {}]
        await acl_manager.update_acl_rule("r1", {"traffic_destination": {"mac_mask": None, "type": "CLIENT_MAC"}})
        # source was absent from the update → its aliased cached dict is left intact (key not popped)
        assert "mac_mask" in existing["traffic_source"]
