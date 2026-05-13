"""Tests for UP6 / USP-Strip outlet control.

Covers DeviceManager.get_pdu_outlets / set_outlet_state and the
unifi_get_pdu_outlets / unifi_set_outlet_state tool functions.

The critical correctness guarantee under test is that writing one outlet
preserves every other outlet's override entry verbatim.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


SAMPLE_OUTLET_TABLE = [
    {
        "index": 1,
        "name": "Outlet 1",
        "has_relay": True,
        "has_metering": True,
        "relay_state": True,
        "cycle_enabled": False,
    },
    {
        "index": 2,
        "name": "Outlet 2",
        "has_relay": True,
        "has_metering": True,
        "relay_state": True,
        "cycle_enabled": False,
    },
    {
        "index": 3,
        "name": "Outlet 3",
        "has_relay": True,
        "has_metering": True,
        "relay_state": False,
        "cycle_enabled": False,
    },
    {
        "index": 4,
        "name": "Outlet 4",
        "has_relay": True,
        "has_metering": True,
        "relay_state": True,
        "cycle_enabled": True,
    },
    {
        "index": 5,
        "name": "Outlet 5",
        "has_relay": True,
        "has_metering": True,
        "relay_state": False,
        "cycle_enabled": False,
    },
    {
        "index": 6,
        "name": "Outlet 6",
        "has_relay": True,
        "has_metering": True,
        "relay_state": True,
        "cycle_enabled": False,
    },
    {
        "index": 7,
        "name": "USB Outlets",
        "has_relay": True,
        "has_metering": False,
        "relay_state": False,
        "cycle_enabled": False,
    },
]

SAMPLE_OUTLET_OVERRIDES = [
    {"index": 1, "name": "Outlet 1", "relay_state": True, "cycle_enabled": False},
    {"index": 2, "name": "Outlet 2", "relay_state": True, "cycle_enabled": False},
    {"index": 3, "name": "Outlet 3", "relay_state": False, "cycle_enabled": False},
    {"index": 4, "name": "Outlet 4", "relay_state": True, "cycle_enabled": True},
    {"index": 5, "name": "Outlet 5", "relay_state": False, "cycle_enabled": False},
    {"index": 6, "name": "Outlet 6", "relay_state": True, "cycle_enabled": False},
    {"index": 7, "name": "USB Outlets", "relay_state": False, "cycle_enabled": False},
]


def _make_pdu_device(mac="ac:8b:a9:11:22:33", *, overrides=None, outlet_table=None, device_type="usp"):
    """Build a mock Device for a UP6-class PDU."""
    device = MagicMock()
    device.mac = mac
    device.raw = {
        "_id": "pdu_doc_id_xyz",
        "mac": mac,
        "name": "Rack Surge Protector Right",
        "model": "UP6",
        "type": device_type,
        "is_access_point": False,
        "outlet_table": [dict(o) for o in (outlet_table if outlet_table is not None else SAMPLE_OUTLET_TABLE)],
        "outlet_overrides": [dict(o) for o in (overrides if overrides is not None else SAMPLE_OUTLET_OVERRIDES)],
    }
    return device


def _make_ap_device(mac="11:22:33:44:55:66"):
    device = MagicMock()
    device.mac = mac
    device.raw = {
        "_id": "ap_doc_id",
        "mac": mac,
        "name": "Office AP",
        "model": "U6-Pro",
        "type": "uap",
        "is_access_point": True,
    }
    return device


@pytest.fixture
def mock_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock()
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.controller = MagicMock()
    conn.controller.devices = MagicMock()
    conn.controller.devices.update = AsyncMock()
    conn.controller.devices.values = MagicMock(return_value=[])
    conn.ensure_connected = AsyncMock(return_value=True)
    return conn


@pytest.fixture
def device_manager(mock_connection):
    from unifi_core.network.managers.device_manager import DeviceManager

    return DeviceManager(mock_connection)


class TestGetPduOutlets:
    """DeviceManager.get_pdu_outlets()."""

    @pytest.mark.asyncio
    async def test_returns_outlets_for_usp_device(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]

        result = await device_manager.get_pdu_outlets(pdu.mac)

        assert result is not None
        assert result["mac"] == pdu.mac
        assert result["model"] == "UP6"
        assert len(result["outlets"]) == 7

        first = result["outlets"][0]
        assert first["index"] == 1
        assert first["relay_state"] is True
        assert first["override_relay_state"] is True
        assert first["has_override"] is True

    @pytest.mark.asyncio
    async def test_returns_outlets_for_uap_pdu(self, device_manager, mock_connection):
        """UAP-typed PDUs (older mesh-connected strips) classify as PDU when is_access_point=False."""
        pdu = _make_pdu_device(device_type="uap")
        pdu.raw["is_access_point"] = False
        mock_connection.controller.devices.values.return_value = [pdu]

        result = await device_manager.get_pdu_outlets(pdu.mac)

        assert result is not None
        assert len(result["outlets"]) == 7

    @pytest.mark.asyncio
    async def test_returns_none_for_ap(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.get_pdu_outlets(ap.mac)

        assert result is None

    @pytest.mark.asyncio
    async def test_raises_for_unknown_device(self, device_manager, mock_connection):
        from unifi_core.exceptions import UniFiNotFoundError

        mock_connection.controller.devices.values.return_value = []

        with pytest.raises(UniFiNotFoundError):
            await device_manager.get_pdu_outlets("ff:ff:ff:ff:ff:ff")


class TestSetOutletState:
    """DeviceManager.set_outlet_state()."""

    @pytest.mark.asyncio
    async def test_modifies_only_target_outlet(self, device_manager, mock_connection):
        """The crux: writing one outlet must preserve every sibling override verbatim."""
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]

        result = await device_manager.set_outlet_state(pdu.mac, outlet_index=3, relay_state=True)

        assert result is not None
        assert result["outlet_index"] == 3
        assert result["relay_state"] is True
        assert result["siblings_preserved"] == 6

        sent = mock_connection.request.call_args[0][0]
        assert sent.method == "put"
        assert "pdu_doc_id_xyz" in sent.path
        sent_overrides = sent.data["outlet_overrides"]
        assert len(sent_overrides) == 7

        sent_by_index = {o["index"]: o for o in sent_overrides}
        # Target flipped on
        assert sent_by_index[3]["relay_state"] is True
        # All other entries are byte-for-byte identical to the originals
        for original in SAMPLE_OUTLET_OVERRIDES:
            if original["index"] == 3:
                continue
            assert sent_by_index[original["index"]] == original, f"override for outlet {original['index']} was mutated"

    @pytest.mark.asyncio
    async def test_cycle_enabled_unchanged_when_omitted(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]

        await device_manager.set_outlet_state(pdu.mac, outlet_index=4, relay_state=False)

        sent_overrides = mock_connection.request.call_args[0][0].data["outlet_overrides"]
        outlet_4 = next(o for o in sent_overrides if o["index"] == 4)
        assert outlet_4["relay_state"] is False
        # Original cycle_enabled=True must be preserved untouched
        assert outlet_4["cycle_enabled"] is True

    @pytest.mark.asyncio
    async def test_cycle_enabled_updated_when_provided(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]

        await device_manager.set_outlet_state(pdu.mac, outlet_index=4, relay_state=True, cycle_enabled=False)

        sent_overrides = mock_connection.request.call_args[0][0].data["outlet_overrides"]
        outlet_4 = next(o for o in sent_overrides if o["index"] == 4)
        assert outlet_4["cycle_enabled"] is False

    @pytest.mark.asyncio
    async def test_seeds_override_when_missing(self, device_manager, mock_connection):
        """If the controller has no override yet for an outlet, one is appended."""
        pdu = _make_pdu_device(overrides=[o for o in SAMPLE_OUTLET_OVERRIDES if o["index"] != 5])
        mock_connection.controller.devices.values.return_value = [pdu]

        result = await device_manager.set_outlet_state(pdu.mac, outlet_index=5, relay_state=True)

        assert result is not None
        sent_overrides = mock_connection.request.call_args[0][0].data["outlet_overrides"]
        assert len(sent_overrides) == 7
        outlet_5 = next(o for o in sent_overrides if o["index"] == 5)
        assert outlet_5["relay_state"] is True
        assert outlet_5["name"] == "Outlet 5"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_index(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]

        result = await device_manager.set_outlet_state(pdu.mac, outlet_index=99, relay_state=True)

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none_for_non_pdu(self, device_manager, mock_connection):
        ap = _make_ap_device()
        mock_connection.controller.devices.values.return_value = [ap]

        result = await device_manager.set_outlet_state(ap.mac, outlet_index=1, relay_state=True)

        assert result is None
        mock_connection.request.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_mutate_cached_overrides(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        original_outlet_3 = dict(pdu.raw["outlet_overrides"][2])
        mock_connection.controller.devices.values.return_value = [pdu]

        await device_manager.set_outlet_state(pdu.mac, outlet_index=3, relay_state=True)

        # The cached device's outlet_overrides entry is unchanged
        assert pdu.raw["outlet_overrides"][2] == original_outlet_3

    @pytest.mark.asyncio
    async def test_invalidates_cache_on_success(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]

        await device_manager.set_outlet_state(pdu.mac, outlet_index=1, relay_state=False)

        mock_connection._invalidate_cache.assert_called()

    @pytest.mark.asyncio
    async def test_propagates_api_error(self, device_manager, mock_connection):
        pdu = _make_pdu_device()
        mock_connection.controller.devices.values.return_value = [pdu]
        mock_connection.request.side_effect = Exception("API error")

        with pytest.raises(Exception):
            await device_manager.set_outlet_state(pdu.mac, outlet_index=1, relay_state=False)


class TestSetOutletStateTool:
    """unifi_set_outlet_state tool function (validation, preview, confirm)."""

    @pytest.mark.asyncio
    async def test_rejects_zero_index(self):
        from unifi_network_mcp.tools.devices import set_outlet_state

        result = await set_outlet_state(mac_address="ac:8b:a9:11:22:33", outlet_index=0, relay_state=True)
        assert result["success"] is False
        assert result["error"]  # pydantic validation rejects outlet_index < 1

    @pytest.mark.asyncio
    async def test_rejects_non_pdu(self):
        from unifi_network_mcp.tools.devices import set_outlet_state

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(return_value=None)
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await set_outlet_state(
                mac_address="11:22:33:44:55:66", outlet_index=1, relay_state=True, confirm=True
            )

        assert result["success"] is False
        assert "not a Smart Power PDU" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_unknown_index_with_available_list(self):
        from unifi_network_mcp.tools.devices import set_outlet_state

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(
                return_value={
                    "mac": "ac:8b:a9:11:22:33",
                    "name": "Rack PDU",
                    "model": "UP6",
                    "outlets": [
                        {
                            "index": 1,
                            "name": "A",
                            "has_relay": True,
                            "relay_state": True,
                            "cycle_enabled": False,
                            "override_relay_state": True,
                            "override_cycle_enabled": False,
                            "has_override": True,
                        },
                    ],
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await set_outlet_state(mac_address="ac:8b:a9:11:22:33", outlet_index=4, relay_state=True)

        assert result["success"] is False
        assert "not found" in result["error"]
        assert "[1]" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_outlet_without_relay(self):
        from unifi_network_mcp.tools.devices import set_outlet_state

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(
                return_value={
                    "mac": "ac:8b:a9:11:22:33",
                    "name": "PDU",
                    "model": "UP1",
                    "outlets": [
                        {
                            "index": 1,
                            "name": "Sense-only",
                            "has_relay": False,
                            "relay_state": None,
                            "cycle_enabled": None,
                            "override_relay_state": None,
                            "override_cycle_enabled": None,
                            "has_override": False,
                        },
                    ],
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await set_outlet_state(
                mac_address="ac:8b:a9:11:22:33", outlet_index=1, relay_state=True, confirm=True
            )

        assert result["success"] is False
        assert "has_relay=false" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_warns_when_powering_off_live_outlet(self):
        from unifi_network_mcp.tools.devices import set_outlet_state

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(
                return_value={
                    "mac": "ac:8b:a9:11:22:33",
                    "name": "Rack PDU",
                    "model": "UP6",
                    "outlets": [
                        {
                            "index": 1,
                            "name": "Server",
                            "has_relay": True,
                            "relay_state": True,
                            "cycle_enabled": False,
                            "override_relay_state": True,
                            "override_cycle_enabled": False,
                            "has_override": True,
                        },
                    ],
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await set_outlet_state(
                mac_address="ac:8b:a9:11:22:33", outlet_index=1, relay_state=False, confirm=False
            )

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert any("powered ON" in w for w in result["warnings"])
        assert any("siblings" in w.lower() or "preserved" in w.lower() for w in result["warnings"])

    @pytest.mark.asyncio
    async def test_confirm_executes_write(self):
        from unifi_network_mcp.tools.devices import set_outlet_state

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(
                return_value={
                    "mac": "ac:8b:a9:11:22:33",
                    "name": "Rack PDU",
                    "model": "UP6",
                    "outlets": [
                        {
                            "index": 1,
                            "name": "Server",
                            "has_relay": True,
                            "relay_state": True,
                            "cycle_enabled": False,
                            "override_relay_state": True,
                            "override_cycle_enabled": False,
                            "has_override": True,
                        },
                    ],
                }
            )
            mock_dm.set_outlet_state = AsyncMock(
                return_value={
                    "outlet_index": 1,
                    "name": "Server",
                    "relay_state": False,
                    "cycle_enabled": False,
                    "siblings_preserved": 6,
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await set_outlet_state(
                mac_address="ac:8b:a9:11:22:33", outlet_index=1, relay_state=False, confirm=True
            )

        assert result["success"] is True
        mock_dm.set_outlet_state.assert_called_once_with(
            device_mac="ac:8b:a9:11:22:33",
            outlet_index=1,
            relay_state=False,
            cycle_enabled=None,
        )


class TestGetPduOutletsTool:
    """unifi_get_pdu_outlets tool function."""

    @pytest.mark.asyncio
    async def test_returns_outlet_data(self):
        from unifi_network_mcp.tools.devices import get_pdu_outlets

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(
                return_value={
                    "mac": "ac:8b:a9:11:22:33",
                    "name": "Rack PDU",
                    "model": "UP6",
                    "outlets": [],
                }
            )
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await get_pdu_outlets(mac_address="ac:8b:a9:11:22:33")

        assert result["success"] is True
        assert result["model"] == "UP6"

    @pytest.mark.asyncio
    async def test_returns_error_for_non_pdu(self):
        from unifi_network_mcp.tools.devices import get_pdu_outlets

        with patch("unifi_network_mcp.tools.devices.device_manager") as mock_dm:
            mock_dm.get_pdu_outlets = AsyncMock(return_value=None)
            mock_dm._connection = MagicMock()
            mock_dm._connection.site = "default"

            result = await get_pdu_outlets(mac_address="11:22:33:44:55:66")

        assert result["success"] is False
        assert "not a Smart Power PDU" in result["error"]
