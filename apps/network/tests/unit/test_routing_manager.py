"""Tests for the RoutingManager class.

This module tests static route operations.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestRoutingManager:
    """Tests for the RoutingManager class."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock ConnectionManager."""
        conn = MagicMock()
        conn.site = "default"
        conn.request = AsyncMock()
        conn.get_cached = MagicMock(return_value=None)
        conn._update_cache = MagicMock()
        conn._invalidate_cache = MagicMock()
        return conn

    @pytest.fixture
    def routing_manager(self, mock_connection):
        """Create a RoutingManager with mocked connection."""
        from unifi_core.network.managers.routing_manager import RoutingManager

        return RoutingManager(mock_connection)

    @pytest.mark.asyncio
    async def test_get_routes_returns_list(self, routing_manager, mock_connection):
        """Test get_routes returns a list of static routes."""
        mock_routes = [
            {
                "_id": "r1",
                "name": "Route to LAN2",
                "static-route_network": "10.0.0.0/24",
                "static-route_nexthop": "192.168.1.1",
            },
            {
                "_id": "r2",
                "name": "Route to VPN",
                "static-route_network": "172.16.0.0/16",
                "static-route_nexthop": "192.168.1.254",
            },
        ]
        mock_connection.request.return_value = mock_routes

        routes = await routing_manager.get_routes()

        assert len(routes) == 2
        assert routes[0]["name"] == "Route to LAN2"
        mock_connection._update_cache.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_routes_uses_cache(self, routing_manager, mock_connection):
        """Test get_routes returns cached data when available."""
        cached_routes = [{"_id": "cached", "name": "Cached Route"}]
        mock_connection.get_cached.return_value = cached_routes

        routes = await routing_manager.get_routes()

        assert routes == cached_routes
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_routes_handles_error(self, routing_manager, mock_connection):
        """Test get_routes returns empty list on error."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await routing_manager.get_routes()

    @pytest.mark.asyncio
    async def test_get_active_routes_returns_list(self, routing_manager, mock_connection):
        """Test get_active_routes returns active routing table."""
        mock_routes = [
            {"destination": "0.0.0.0/0", "gateway": "192.168.1.1"},
            {"destination": "192.168.1.0/24", "gateway": "0.0.0.0"},
        ]
        mock_connection.request.return_value = mock_routes

        routes = await routing_manager.get_active_routes()

        assert len(routes) == 2
        # Verify correct endpoint was called
        call_args = mock_connection.request.call_args
        api_request = call_args[0][0]
        assert api_request.path == "/stat/routing"

    @pytest.mark.asyncio
    async def test_get_active_routes_handles_error(self, routing_manager, mock_connection):
        """Test get_active_routes returns empty list on error."""
        mock_connection.request.side_effect = Exception("Network error")

        with pytest.raises(Exception):
            await routing_manager.get_active_routes()

    @pytest.mark.asyncio
    async def test_get_active_routes_reads_v2_table_when_legacy_is_empty(self, routing_manager, mock_connection):
        """Newer controllers answer /stat/routing with no rows and serve the table from V2 /routes."""
        v2_table = {
            "truncated": False,
            "items": [
                {
                    "destination": "0.0.0.0/0",
                    "distance": 200,
                    "origin": "DHCP",
                    "type": "unicast",
                    "nexthops": [
                        {"gateway": "203.0.113.1", "interface": "net-wan", "in_use": True, "weight": 1},
                        {"gateway": "203.0.113.2", "interface": "net-wan2", "in_use": False, "weight": 1},
                    ],
                },
                {
                    "destination": "192.168.1.0/24",
                    "origin": "Kernel",
                    "type": "unicast",
                    "nexthops": [{"interface": "net-lan", "in_use": True, "weight": 1}],
                },
                {"destination": "0.0.0.0/0", "origin": "PBR", "type": "blackhole", "nexthops": [{"in_use": True}]},
            ],
        }
        mock_connection.request.side_effect = [[], v2_table]

        routes = await routing_manager.get_active_routes()

        assert [call.args[0].path for call in mock_connection.request.call_args_list] == ["/stat/routing", "/routes"]
        assert routes == [
            {
                "pfx": "0.0.0.0/0",
                "nh": [{"via": "203.0.113.1", "intf": "net-wan"}],
                "metric": 200,
                "origin": "DHCP",
                "route_type": "unicast",
            },
            {
                "pfx": "192.168.1.0/24",
                "nh": [{"via": None, "intf": "net-lan"}],
                "metric": None,
                "origin": "Kernel",
                "route_type": "unicast",
            },
            {
                "pfx": "0.0.0.0/0",
                "nh": [{"via": None, "intf": None}],
                "metric": None,
                "origin": "PBR",
                "route_type": "blackhole",
            },
        ]

    @pytest.mark.asyncio
    async def test_get_active_routes_stays_empty_without_a_v2_table(self, routing_manager, mock_connection):
        """An empty legacy table is still an empty result when V2 /routes is missing."""
        mock_connection.request.side_effect = [[], Exception("404 from /routes")]

        assert await routing_manager.get_active_routes() == []

    @pytest.mark.asyncio
    async def test_get_active_routes_reads_v2_table_when_legacy_is_missing(self, routing_manager, mock_connection):
        mock_connection.request.side_effect = [
            Exception("404 Not Found"),
            {"items": [{"destination": "10.0.0.0/8", "nexthops": []}]},
        ]

        routes = await routing_manager.get_active_routes()

        assert routes == [{"pfx": "10.0.0.0/8", "nh": [], "metric": None}]

    @pytest.mark.asyncio
    async def test_get_route_details_found(self, routing_manager, mock_connection):
        """Test get_route_details returns route when found."""
        mock_routes = [
            {"_id": "r1", "name": "Route 1"},
            {"_id": "r2", "name": "Route 2"},
        ]
        mock_connection.request.return_value = mock_routes

        route = await routing_manager.get_route_details("r2")

        assert route is not None
        assert route["name"] == "Route 2"

    @pytest.mark.asyncio
    async def test_get_route_details_not_found(self, routing_manager, mock_connection):
        """Test get_route_details raises UniFiNotFoundError when not found."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = [{"_id": "r1"}]

        with pytest.raises(UniFiNotFoundError):
            await routing_manager.get_route_details("nonexistent")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            pytest.param(
                {
                    "name": "New Route",
                    "static_route_network": "10.0.0.0/24",
                    "static_route_nexthop": "192.168.1.1",
                },
                {
                    "name": "New Route",
                    "static-route_network": "10.0.0.0/24",
                    "static-route_nexthop": "192.168.1.1",
                    "static-route_distance": 1,
                    "enabled": True,
                },
                id="required-only-uses-defaults",
            ),
            pytest.param(
                {
                    "name": "Custom Route",
                    "static_route_network": "172.16.0.0/16",
                    "static_route_nexthop": "10.0.0.1",
                    "static_route_distance": 10,
                    "enabled": False,
                    "route_type": "nexthop-route",
                },
                {"static-route_distance": 10, "enabled": False, "type": "nexthop-route"},
                id="all-options",
            ),
        ],
    )
    async def test_create_route_payload(self, routing_manager, mock_connection, kwargs, expected):
        mock_connection.request.return_value = [{"_id": "new1"}]

        await routing_manager.create_route(**kwargs)

        api_request = mock_connection.request.call_args[0][0]
        for key, value in expected.items():
            assert api_request.data[key] == value

    @pytest.mark.asyncio
    async def test_create_route_invalidates_cache(self, routing_manager, mock_connection):
        """Test create_route invalidates the cache."""
        mock_connection.request.return_value = [{"_id": "new1"}]

        await routing_manager.create_route(
            name="Test",
            static_route_network="10.0.0.0/24",
            static_route_nexthop="192.168.1.1",
        )

        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_create_route_handles_error(self, routing_manager, mock_connection):
        """Test create_route returns None on error."""
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await routing_manager.create_route(
                name="Test",
                static_route_network="10.0.0.0/24",
                static_route_nexthop="192.168.1.1",
            )

    @pytest.mark.asyncio
    async def test_update_route_success(self, routing_manager, mock_connection):
        """Test update_route with valid parameters."""
        mock_connection.request.side_effect = [
            [{"_id": "r1", "name": "Old Name"}],  # get_routes
            {},  # update response
        ]

        result = await routing_manager.update_route(
            route_id="r1",
            name="New Name",
            enabled=False,
        )

        assert result is True
        update_call = mock_connection.request.call_args_list[1]
        api_request = update_call[0][0]
        assert api_request.data["name"] == "New Name"
        assert api_request.data["enabled"] is False
        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_update_route_network_and_nexthop(self, routing_manager, mock_connection):
        """Test update_route with network and nexthop changes."""
        mock_connection.request.side_effect = [
            [{"_id": "r1", "name": "Test"}],
            {},
        ]

        await routing_manager.update_route(
            route_id="r1",
            static_route_network="192.168.0.0/24",
            static_route_nexthop="10.0.0.1",
            static_route_distance=5,
        )

        update_call = mock_connection.request.call_args_list[1]
        api_request = update_call[0][0]
        assert api_request.data["static-route_network"] == "192.168.0.0/24"
        assert api_request.data["static-route_nexthop"] == "10.0.0.1"
        assert api_request.data["static-route_distance"] == 5

    @pytest.mark.asyncio
    async def test_update_route_not_found(self, routing_manager, mock_connection):
        """Test update_route raises UniFiNotFoundError when route missing."""
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.request.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await routing_manager.update_route(
                route_id="nonexistent",
                name="Test",
            )

    @pytest.mark.asyncio
    async def test_update_route_no_updates(self, routing_manager, mock_connection):
        """Test update_route with no changes still succeeds (sends full object)."""
        mock_connection.request.side_effect = [
            [{"_id": "r1", "name": "Test"}],  # get_routes response
            {},  # update response
        ]

        result = await routing_manager.update_route(route_id="r1")

        # With full-object updates, calling with no changes is a valid noop
        assert result is True

    @pytest.mark.asyncio
    async def test_update_route_handles_error(self, routing_manager, mock_connection):
        """Test update_route raises on API error."""
        mock_connection.request.side_effect = [
            [{"_id": "r1", "name": "Test"}],
            Exception("API error"),
        ]

        with pytest.raises(Exception, match="API error"):
            await routing_manager.update_route(route_id="r1", name="New")
