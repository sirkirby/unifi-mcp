"""Tests for the OonManager class.

This module tests OON (Object-Oriented Network) policy operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

CALLS = [
    lambda m: m.get_oon_policies(),
    lambda m: m.get_oon_policy_by_id("p1"),
    lambda m: m.create_oon_policy({"name": "Test"}),
    lambda m: m.update_oon_policy("p1", {"name": "Test"}),
    lambda m: m.toggle_oon_policy("p1"),
    lambda m: m.delete_oon_policy("p1"),
]


class TestOonManager:
    """Tests for the OonManager class."""

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
    def oon_manager(self, mock_connection):
        """Create an OonManager with mocked connection."""
        from unifi_core.network.managers.oon_manager import OonManager

        return OonManager(mock_connection)

    # ---- get_oon_policies ----

    @pytest.mark.asyncio
    async def test_get_oon_policies_returns_list(self, oon_manager, mock_connection):
        """Test get_oon_policies returns a list of policies."""
        mock_policies = [
            {"id": "p1", "name": "Bedtime", "enabled": True},
            {"id": "p2", "name": "App Block", "enabled": True},
        ]
        mock_connection.request.return_value = mock_policies

        policies = await oon_manager.get_oon_policies()

        assert len(policies) == 2
        assert policies[0]["name"] == "Bedtime"
        mock_connection._update_cache.assert_called_once()
        assert mock_connection.request.call_args[0][0].path == "/object-oriented-network-configs"

    @pytest.mark.asyncio
    async def test_get_oon_policies_uses_cache(self, oon_manager, mock_connection):
        """Test get_oon_policies returns cached data when available."""
        cached = [{"id": "cached", "name": "Cached Policy"}]
        mock_connection.get_cached.return_value = cached

        policies = await oon_manager.get_oon_policies()

        assert policies == cached
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_oon_policies_handles_404(self, oon_manager, mock_connection):
        """Test get_oon_policies returns empty list on 404 (unsupported controller)."""
        mock_connection.request.side_effect = Exception("404 Not Found")

        # 404 is a legitimate fallback path: returns empty list when the
        # controller does not support OON policies. Other errors raise.
        result = await oon_manager.get_oon_policies()
        assert result == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", CALLS)
    async def test_not_connected_raises(self, oon_manager, mock_connection, call):
        """Every manager operation raises when not connected, without sending a request."""
        mock_connection.ensure_connected.return_value = False

        with pytest.raises(ConnectionError, match="Not connected to controller"):
            await call(oon_manager)

        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("call", CALLS)
    async def test_api_error_propagates(self, oon_manager, mock_connection, call):
        """API errors propagate from every manager operation."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            await call(oon_manager)

    # ---- get_oon_policy_by_id ----

    @pytest.mark.asyncio
    async def test_get_oon_policy_by_id_found(self, oon_manager, mock_connection):
        """Test get_oon_policy_by_id returns policy when found."""
        mock_connection.request.return_value = {"id": "p1", "name": "Test Policy"}

        policy = await oon_manager.get_oon_policy_by_id("p1")

        assert policy is not None
        assert policy["name"] == "Test Policy"
        assert mock_connection.request.call_args[0][0].path == "/object-oriented-network-config/p1"

    # ---- create_oon_policy ----

    @pytest.mark.asyncio
    async def test_create_oon_policy_success(self, oon_manager, mock_connection):
        """Test create_oon_policy with valid data."""
        policy_data = {
            "_id": "old1",
            "id": "old1",
            "name": "New Policy",
            "enabled": True,
            "target_type": "CLIENTS",
            "targets": ["aa:bb:cc:dd:ee:ff"],
        }
        mock_connection.request.return_value = {**policy_data, "id": "new1"}

        result = await oon_manager.create_oon_policy(policy_data)

        assert result is not None
        assert result["id"] == "new1"
        mock_connection._invalidate_cache.assert_called()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/object-oriented-network-config"
        assert api_request.method == "post"
        # _id and id are stripped from the POST body
        assert "_id" not in api_request.data
        assert "id" not in api_request.data

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("target_type", "targets", "expected"),
        [
            (
                "CLIENTS",
                ["aa:bb:cc:dd:ee:ff", {"type": "MAC", "id": "11:22:33:44:55:66"}],
                [
                    {"type": "MAC", "value": "aa:bb:cc:dd:ee:ff"},
                    {"type": "MAC", "value": "11:22:33:44:55:66"},
                ],
            ),
            ("GROUPS", ["group-1"], [{"type": "NETWORK_GROUP_ID", "value": "group-1"}]),
        ],
    )
    async def test_create_oon_policy_normalizes_targets(
        self, oon_manager, mock_connection, target_type, targets, expected
    ):
        """create_oon_policy sends controller target objects (MAC values, network group ids)."""
        policy_data = {
            "name": "Test",
            "enabled": False,
            "target_type": target_type,
            "targets": targets,
            "secure": {"enabled": False, "internet": {"mode": "TURN_OFF_INTERNET"}},
        }
        mock_connection.request.return_value = {"id": "new1", "name": "Test"}

        await oon_manager.create_oon_policy(policy_data)

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.data["targets"] == expected

    @pytest.mark.asyncio
    @pytest.mark.parametrize("internet_access_enabled", [False, True])
    async def test_create_oon_policy_normalizes_secure_shorthand(
        self, oon_manager, mock_connection, internet_access_enabled
    ):
        """Secure shorthand becomes required nested fields; empty shorthand becomes a disabled draft."""
        policy_data = {
            "name": "Test",
            "enabled": False,
            "target_type": "CLIENTS",
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "secure": {"internet_access_enabled": internet_access_enabled, "apps": []},
        }
        mock_connection.request.return_value = {"id": "new1", "name": "Test"}

        await oon_manager.create_oon_policy(policy_data)

        api_request = mock_connection.request.call_args[0][0]
        assert api_request.data["secure"] == {
            "enabled": not internet_access_enabled,
            "internet": {"mode": "TURN_OFF_INTERNET"},
        }

    @pytest.mark.asyncio
    async def test_create_oon_policy_missing_name(self, oon_manager, mock_connection):
        """Test create_oon_policy returns None when name is missing."""
        result = await oon_manager.create_oon_policy({"enabled": True})

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_oon_policy_handles_data_wrapper(self, oon_manager, mock_connection):
        """Test create_oon_policy handles response with data key."""
        mock_connection.request.return_value = {"data": {"id": "new1", "name": "Test"}}

        result = await oon_manager.create_oon_policy({"name": "Test"})

        assert result == {"id": "new1", "name": "Test"}

    # ---- update_oon_policy ----

    @pytest.mark.asyncio
    async def test_update_oon_policy_fetches_and_merges(self, oon_manager, mock_connection):
        """Test update_oon_policy fetches current policy, merges, PUTs full object."""
        existing_policy = {
            "id": "p1",
            "name": "Kids Bedtime",
            "enabled": True,
            "target_type": "CLIENTS",
            "targets": ["aa:bb:cc:dd:ee:ff"],
            "secure": {"internet_access_enabled": True},
            "qos": {"mode": "OFF"},
            "route": {"mode": "OFF"},
        }
        mock_connection.request.side_effect = [
            existing_policy,  # GET
            {},  # PUT
        ]

        result = await oon_manager.update_oon_policy("p1", {"name": "Kids Bedtime v2", "enabled": False})

        assert result["name"] == "Kids Bedtime v2"
        assert result["enabled"] is False
        put_call = mock_connection.request.call_args_list[1]
        put_request = put_call[0][0]
        assert put_request.method == "put"
        assert put_request.path == "/object-oriented-network-config/p1"
        mock_connection._invalidate_cache.assert_called()
        assert put_request.data["name"] == "Kids Bedtime v2"
        assert put_request.data["enabled"] is False
        assert put_request.data["targets"] == ["aa:bb:cc:dd:ee:ff"]
        assert put_request.data["secure"] == {"internet_access_enabled": True}

    @pytest.mark.asyncio
    async def test_update_oon_policy_empty_update(self, oon_manager, mock_connection):
        """Test update_oon_policy with empty data returns existing without PUT."""
        existing = {"id": "p1", "name": "Existing"}
        mock_connection.request.return_value = existing

        result = await oon_manager.update_oon_policy("p1", {})

        assert result == existing
        # Only the GET (existence check) ran; no PUT.
        assert mock_connection.request.call_count == 1

    # ---- toggle_oon_policy ----

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("currently_enabled", "expected"), [(False, True), (True, False)])
    async def test_toggle_oon_policy_flips_state(self, oon_manager, mock_connection, currently_enabled, expected):
        """toggle_oon_policy enables a disabled policy and disables an enabled one."""
        mock_connection.request.side_effect = [
            {"id": "p1", "name": "Test", "enabled": currently_enabled},  # get
            {},  # put
        ]

        result = await oon_manager.toggle_oon_policy("p1")

        assert result is expected

    @pytest.mark.asyncio
    async def test_toggle_oon_policy_not_found(self, oon_manager, mock_connection):
        """Test toggle_oon_policy raises UniFiNotFoundError when policy missing."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = None

        with pytest.raises(UniFiNotFoundError):
            await oon_manager.toggle_oon_policy("nonexistent")

    @pytest.mark.asyncio
    async def test_toggle_oon_policy_invalidates_cache(self, oon_manager, mock_connection):
        """Test toggle_oon_policy invalidates cache."""
        mock_connection.request.side_effect = [
            {"id": "p1", "enabled": True},
            {},
        ]

        await oon_manager.toggle_oon_policy("p1")

        mock_connection._invalidate_cache.assert_called()

    # ---- delete_oon_policy ----

    @pytest.mark.asyncio
    async def test_delete_oon_policy_success(self, oon_manager, mock_connection):
        """Test delete_oon_policy with valid ID."""
        mock_connection.request.return_value = {}

        result = await oon_manager.delete_oon_policy("p1")

        assert result is True
        mock_connection._invalidate_cache.assert_called()
        api_request = mock_connection.request.call_args[0][0]
        assert api_request.path == "/object-oriented-network-config/p1"
        assert api_request.method == "delete"

    # ---- API path verification ----
