"""Tests for DoorManager and door tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.door_manager import _LOCATIONS_EXPAND, DoorManager
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cm_api():
    """ConnectionManager with API client available."""
    cm = AccessConnectionManager(host="192.168.1.1", username="", password="", api_key="test-key")
    cm._api_client_available = True
    cm._api_client = AsyncMock()
    return cm


@pytest.fixture
def cm_proxy():
    """ConnectionManager with proxy available."""
    cm = AccessConnectionManager(host="192.168.1.1", username="admin", password="secret")
    cm._proxy_available = True
    cm._proxy_session = MagicMock()
    return cm


@pytest.fixture
def cm_both(cm_api):
    """ConnectionManager with both paths available."""
    cm_api._proxy_available = True
    cm_api._proxy_session = MagicMock()
    cm_api.username = "admin"
    cm_api.password = "secret"
    return cm_api


@pytest.fixture
def cm_none():
    """ConnectionManager with no auth paths."""
    cm = AccessConnectionManager(host="192.168.1.1", username="", password="")
    return cm


@pytest.fixture
def door_mgr_api(cm_api):
    return DoorManager(cm_api)


@pytest.fixture
def door_mgr_proxy(cm_proxy):
    return DoorManager(cm_proxy)


@pytest.fixture
def door_mgr_both(cm_both):
    return DoorManager(cm_both)


@pytest.fixture
def door_mgr_none(cm_none):
    return DoorManager(cm_none)


# ---------------------------------------------------------------------------
# list_doors
# ---------------------------------------------------------------------------


class TestListDoors:
    @pytest.mark.asyncio
    async def test_list_doors_api_client(self, door_mgr_api, cm_api):
        """list_doors uses API client when available."""
        mock_door = MagicMock()
        mock_door.id = "door-1"
        mock_door.name = "Front Door"
        mock_door.door_position_status = "closed"
        mock_door.lock_relay_status = "locked"

        cm_api._api_client.get_doors = AsyncMock(return_value=[mock_door])

        doors = await door_mgr_api.list_doors()

        assert len(doors) == 1
        assert doors[0]["id"] == "door-1"
        assert doors[0]["name"] == "Front Door"
        assert doors[0]["door_position_status"] == "closed"
        assert doors[0]["lock_relay_status"] == "locked"

    @pytest.mark.asyncio
    async def test_list_doors_proxy(self, door_mgr_proxy, cm_proxy):
        """list_doors falls back to proxy using dashboard/locations endpoint."""
        expected = [{"id": "door-2", "name": "Back Door"}]

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            doors = await door_mgr_proxy.list_doors()

        assert doors == expected
        mock_req.assert_awaited_once_with("GET", f"dashboard/locations?{_LOCATIONS_EXPAND}")

    @pytest.mark.asyncio
    async def test_list_doors_no_auth(self, door_mgr_none):
        """list_doors raises when no auth path available."""
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await door_mgr_none.list_doors()

    @pytest.mark.asyncio
    async def test_list_doors_proxy_compact(self, door_mgr_proxy, cm_proxy):
        """compact=True simplifies nested devices and strips thumbnail."""
        locations = [
            {
                "id": "door-1",
                "name": "Main Door",
                "location_type": "door",
                "access_method": ["nfc", "bt_button"],
                "up_id": "floor-1",
                "extras": None,
                "device_ids": ["dev-1", "dev-2"],
                "thumbnail": {"type": "thumbnail", "url": "/icons/cover.png"},
                "devices": [
                    {
                        "name": "Reader",
                        "id": "dev-1",
                        "device_type": "UA-G3",
                        "online": True,
                        "direction": "entry",
                        # Fields that should be stripped from nested devices:
                        "alias": "Main Door - Entry",
                        "ip": "10.0.0.1",
                        "mac": "AA:BB",
                        "firmware": "v3.17.11.0",
                        "guid": "some-guid",
                        "start_time": 12345,
                        "hw_type": "GA",
                        "revision": "123",
                        "access_method": {"nfc": "yes"},
                        "cap": [],
                        "category": ["ua-lite"],
                        "location_id": "door-1",
                        "connected_hub_id": "dev-2",
                        "version": "v3.17.11.0",
                        "adopting": False,
                        "location_states": [],
                    },
                ],
            }
        ]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": locations}
            doors = await door_mgr_proxy.list_doors(compact=True)

        assert len(doors) == 1
        door = doors[0]
        # Essential door fields kept
        assert door["id"] == "door-1"
        assert door["name"] == "Main Door"
        assert door["location_type"] == "door"
        assert door["access_method"] == ["nfc", "bt_button"]
        # Thumbnail stripped
        assert "thumbnail" not in door
        # up_id, extras, device_ids stripped
        assert "up_id" not in door
        assert "extras" not in door
        assert "device_ids" not in door
        # Devices simplified
        assert len(door["devices"]) == 1
        dev = door["devices"][0]
        assert dev["name"] == "Reader"
        assert dev["id"] == "dev-1"
        assert dev["device_type"] == "UA-G3"
        assert dev["online"] is True
        assert dev["direction"] == "entry"
        # Nested device bloat stripped
        assert "guid" not in dev
        assert "start_time" not in dev
        assert "revision" not in dev
        assert "access_method" not in dev
        assert "cap" not in dev
        assert "category" not in dev

    @pytest.mark.asyncio
    async def test_list_doors_prefers_api_client(self, door_mgr_both, cm_both):
        """list_doors prefers API client over proxy when both available."""
        mock_door = MagicMock()
        mock_door.id = "door-1"
        mock_door.name = "Main Door"
        mock_door.door_position_status = "open"
        mock_door.lock_relay_status = "unlocked"

        cm_both._api_client.get_doors = AsyncMock(return_value=[mock_door])

        doors = await door_mgr_both.list_doors()

        assert len(doors) == 1
        assert doors[0]["name"] == "Main Door"
        cm_both._api_client.get_doors.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_door
# ---------------------------------------------------------------------------


class TestGetDoor:
    @pytest.mark.asyncio
    async def test_get_door_api_client(self, door_mgr_api, cm_api):
        """get_door returns detailed door info via API client."""
        mock_door = MagicMock()
        mock_door.id = "door-1"
        mock_door.name = "Front Door"
        mock_door.door_position_status = "closed"
        mock_door.lock_relay_status = "locked"
        mock_door.camera_resource_id = "cam-1"
        mock_door.door_guard = None

        cm_api._api_client.get_door = AsyncMock(return_value=mock_door)

        detail = await door_mgr_api.get_door("door-1")

        assert detail["id"] == "door-1"
        assert detail["camera_resource_id"] == "cam-1"

    @pytest.mark.asyncio
    async def test_get_door_proxy(self, door_mgr_proxy, cm_proxy):
        """get_door filters from dashboard/locations response by ID."""
        locations = [
            {"id": "door-1", "name": "Front Door"},
            {"id": "door-2", "name": "Back Door", "lock_relay_status": "locked"},
        ]

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": locations}
            detail = await door_mgr_proxy.get_door("door-2")

        assert detail == {"id": "door-2", "name": "Back Door", "lock_relay_status": "locked"}
        mock_req.assert_awaited_once_with("GET", f"dashboard/locations?{_LOCATIONS_EXPAND}")

    @pytest.mark.asyncio
    async def test_get_door_proxy_not_found(self, door_mgr_proxy, cm_proxy):
        """get_door raises ValueError when door ID not found in locations."""
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": [{"id": "other-door"}]}
            with pytest.raises(UniFiNotFoundError):
                await door_mgr_proxy.get_door("missing-door")

    @pytest.mark.asyncio
    async def test_get_door_empty_id(self, door_mgr_api):
        """get_door raises ValueError for empty door_id."""
        with pytest.raises(ValueError, match="door_id is required"):
            await door_mgr_api.get_door("")

    @pytest.mark.asyncio
    async def test_get_door_no_auth(self, door_mgr_none):
        """get_door raises when no auth path available."""
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await door_mgr_none.get_door("door-1")


# ---------------------------------------------------------------------------
# get_door_status
# ---------------------------------------------------------------------------


class TestGetDoorStatus:
    @pytest.mark.asyncio
    async def test_get_door_status_api(self, door_mgr_api, cm_api):
        """get_door_status extracts status fields via API client."""
        mock_door = MagicMock()
        mock_door.id = "door-1"
        mock_door.name = "Front Door"
        mock_door.door_position_status = "closed"
        mock_door.lock_relay_status = "locked"

        cm_api._api_client.get_door = AsyncMock(return_value=mock_door)

        status = await door_mgr_api.get_door_status("door-1")

        assert status["lock_relay_status"] == "locked"
        assert status["door_position_status"] == "closed"

    @pytest.mark.asyncio
    async def test_get_door_status_proxy(self, door_mgr_proxy, cm_proxy):
        """get_door_status extracts status fields from locations via proxy."""
        locations = [
            {
                "id": "door-2",
                "name": "Back Door",
                "door_position_status": "open",
                "lock_relay_status": "unlocked",
                "extra_field": "ignored",
            }
        ]

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": locations}
            status = await door_mgr_proxy.get_door_status("door-2")

        assert status["lock_relay_status"] == "unlocked"
        assert "extra_field" not in status

    @pytest.mark.asyncio
    async def test_get_door_status_empty_id(self, door_mgr_api):
        """get_door_status raises ValueError for empty door_id."""
        with pytest.raises(ValueError, match="door_id is required"):
            await door_mgr_api.get_door_status("")


# ---------------------------------------------------------------------------
# list_door_groups
# ---------------------------------------------------------------------------


class TestListDoorGroups:
    @pytest.mark.asyncio
    async def test_list_door_groups_proxy(self, door_mgr_proxy, cm_proxy):
        """list_door_groups returns groups via proxy using access_groups endpoint."""
        expected = [{"id": "grp-1", "name": "Building A"}]

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": expected}
            groups = await door_mgr_proxy.list_door_groups()

        assert groups == expected
        mock_req.assert_awaited_once_with("GET", "access_groups")

    @pytest.mark.asyncio
    async def test_list_door_groups_no_proxy(self, door_mgr_api):
        """list_door_groups raises when proxy not available (API-only doesn't support this)."""
        # API client path doesn't have proxy
        door_mgr_api._cm._proxy_available = False
        door_mgr_api._cm._proxy_session = None
        with pytest.raises(UniFiConnectionError, match="proxy session required"):
            await door_mgr_api.list_door_groups()


# ---------------------------------------------------------------------------
# unlock_door (preview)
# ---------------------------------------------------------------------------


class TestUnlockDoor:
    @pytest.mark.asyncio
    async def test_unlock_door_preview(self, door_mgr_api, cm_api):
        """unlock_door returns preview data."""
        mock_door = MagicMock()
        mock_door.id = "door-1"
        mock_door.name = "Front Door"
        mock_door.door_position_status = "closed"
        mock_door.lock_relay_status = "locked"

        cm_api._api_client.get_door = AsyncMock(return_value=mock_door)

        preview = await door_mgr_api.unlock_door("door-1", duration=5)

        assert preview["door_id"] == "door-1"
        assert preview["door_name"] == "Front Door"
        assert preview["proposed_changes"]["action"] == "unlock"
        assert preview["proposed_changes"]["duration_seconds"] == 5

    @pytest.mark.asyncio
    async def test_unlock_door_empty_id(self, door_mgr_api):
        """unlock_door raises ValueError for empty door_id."""
        with pytest.raises(ValueError, match="door_id is required"):
            await door_mgr_api.unlock_door("")

    @pytest.mark.asyncio
    async def test_unlock_door_invalid_duration(self, door_mgr_api):
        """unlock_door raises ValueError for invalid duration."""
        with pytest.raises(ValueError, match="duration must be at least 1"):
            await door_mgr_api.unlock_door("door-1", duration=0)


# ---------------------------------------------------------------------------
# apply_unlock_door
# ---------------------------------------------------------------------------


class TestApplyUnlockDoor:
    @pytest.mark.asyncio
    async def test_apply_unlock_api(self, door_mgr_api, cm_api):
        """apply_unlock_door uses API client."""
        cm_api._api_client.unlock_door = AsyncMock()

        result = await door_mgr_api.apply_unlock_door("door-1", duration=5)

        assert result["result"] == "success"
        assert result["action"] == "unlock"
        cm_api._api_client.unlock_door.assert_awaited_once_with("door-1")

    @pytest.mark.asyncio
    async def test_apply_unlock_proxy(self, door_mgr_proxy, cm_proxy):
        """apply_unlock_door uses proxy with dashboard/locations unlock endpoint."""
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await door_mgr_proxy.apply_unlock_door("door-2", duration=3)

        assert result["result"] == "success"
        mock_req.assert_awaited_once_with("PUT", "dashboard/locations/door-2/unlock", json={"duration": 3})

    @pytest.mark.asyncio
    async def test_apply_unlock_no_auth(self, door_mgr_none):
        """apply_unlock_door raises when no auth path."""
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await door_mgr_none.apply_unlock_door("door-1")


# ---------------------------------------------------------------------------
# lock_door (preview)
# ---------------------------------------------------------------------------


class TestLockDoor:
    @pytest.mark.asyncio
    async def test_lock_door_preview(self, door_mgr_proxy, cm_proxy):
        """lock_door returns preview data."""
        locations = [
            {
                "id": "door-1",
                "name": "Front Door",
                "door_position_status": "closed",
                "lock_relay_status": "unlocked",
            }
        ]

        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": locations}
            preview = await door_mgr_proxy.lock_door("door-1")

        assert preview["door_id"] == "door-1"
        assert preview["proposed_changes"]["action"] == "lock"

    @pytest.mark.asyncio
    async def test_lock_door_empty_id(self, door_mgr_proxy):
        """lock_door raises ValueError for empty door_id."""
        with pytest.raises(ValueError, match="door_id is required"):
            await door_mgr_proxy.lock_door("")


# ---------------------------------------------------------------------------
# apply_lock_door
# ---------------------------------------------------------------------------


class TestApplyLockDoor:
    @pytest.mark.asyncio
    async def test_apply_lock_api(self, door_mgr_api, cm_api):
        """apply_lock_door uses API client lock rule endpoint."""
        cm_api._api_client.set_door_lock_rule = AsyncMock()

        result = await door_mgr_api.apply_lock_door("door-1")

        assert result["result"] == "success"
        assert result["action"] == "lock"
        cm_api._api_client.set_door_lock_rule.assert_awaited_once()
        door_id, rule = cm_api._api_client.set_door_lock_rule.await_args.args
        assert door_id == "door-1"
        assert rule.type.value == "lock_now"
        assert rule.interval == 0

    @pytest.mark.asyncio
    async def test_apply_lock_proxy(self, door_mgr_proxy, cm_proxy):
        """apply_lock_door uses proxy with dashboard/locations lock endpoint."""
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await door_mgr_proxy.apply_lock_door("door-1")

        assert result["result"] == "success"
        assert result["action"] == "lock"
        mock_req.assert_awaited_once_with("PUT", "dashboard/locations/door-1/lock")

    @pytest.mark.asyncio
    async def test_apply_lock_no_auth(self, door_mgr_none):
        """apply_lock_door raises when no auth path is available."""
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await door_mgr_none.apply_lock_door("door-1")

    @pytest.mark.asyncio
    async def test_apply_lock_api_unavailable_uses_proxy(self, door_mgr_api):
        """apply_lock_door can no longer run after both auth paths are unavailable."""
        door_mgr_api._cm._api_client_available = False
        door_mgr_api._cm._api_client = None
        door_mgr_api._cm._proxy_available = False
        door_mgr_api._cm._proxy_session = None
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await door_mgr_api.apply_lock_door("door-1")
