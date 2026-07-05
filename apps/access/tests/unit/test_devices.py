"""Tests for DeviceManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.access.managers.device_manager import DeviceManager
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError
from unifi_core.redaction import REDACTED

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cm_api():
    cm = AccessConnectionManager(host="192.168.1.1", username="", password="", api_key="test-key")
    cm._api_client_available = True
    cm._api_client = AsyncMock()
    return cm


@pytest.fixture
def cm_proxy():
    cm = AccessConnectionManager(host="192.168.1.1", username="admin", password="secret")
    cm._proxy_available = True
    cm._proxy_session = MagicMock()
    return cm


@pytest.fixture
def cm_none():
    return AccessConnectionManager(host="192.168.1.1", username="", password="")


@pytest.fixture
def device_mgr_api(cm_api):
    return DeviceManager(cm_api)


@pytest.fixture
def device_mgr_proxy(cm_proxy):
    return DeviceManager(cm_proxy)


@pytest.fixture
def device_mgr_none(cm_none):
    return DeviceManager(cm_none)


# ---------------------------------------------------------------------------
# list_devices
# ---------------------------------------------------------------------------


class TestListDevices:
    @pytest.mark.asyncio
    async def test_list_devices_api(self, device_mgr_api, cm_api):
        mock_device = MagicMock()
        mock_device.id = "dev-1"
        mock_device.name = "Hub Pro"
        mock_device.type = "hub"
        mock_device.connected = True
        mock_device.firmware_version = "2.1.0"

        cm_api._api_client.get_devices = AsyncMock(return_value=[mock_device])

        devices = await device_mgr_api.list_devices()

        assert len(devices) == 1
        assert devices[0]["id"] == "dev-1"
        assert devices[0]["name"] == "Hub Pro"
        assert devices[0]["connected"] is True

    @pytest.mark.asyncio
    async def test_list_devices_proxy(self, device_mgr_proxy, cm_proxy):
        """list_devices flattens nested topology4 structure."""
        topology = [
            {
                "name": "Site",
                "unique_id": "site-1",
                "floors": [
                    {
                        "name": "1F",
                        "unique_id": "floor-1",
                        "doors": [
                            {
                                "name": "Front Door",
                                "unique_id": "door-1",
                                "device_groups": [
                                    [
                                        {
                                            "unique_id": "dev-2",
                                            "name": "Reader G2",
                                            "device_type": "reader",
                                            "mac": "AA:BB",
                                        },
                                    ]
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            devices = await device_mgr_proxy.list_devices()
        assert len(devices) == 1
        assert devices[0]["unique_id"] == "dev-2"
        assert devices[0]["name"] == "Reader G2"
        assert devices[0]["_door_name"] == "Front Door"
        mock_req.assert_awaited_once_with("GET", "devices/topology4")

    @pytest.mark.asyncio
    async def test_list_devices_proxy_compact(self, device_mgr_proxy, cm_proxy):
        """compact=True strips configs, images, location, door, floor, extensions, update_manual, capabilities."""
        topology = [
            {
                "name": "Site",
                "unique_id": "site-1",
                "floors": [
                    {
                        "name": "1F",
                        "unique_id": "floor-1",
                        "doors": [
                            {
                                "name": "Front Door",
                                "unique_id": "door-1",
                                "device_groups": [
                                    [
                                        {
                                            "unique_id": "dev-2",
                                            "name": "Reader G2",
                                            "alias": "Front Reader",
                                            "device_type": "UA-G3",
                                            "firmware": "v3.17.11.0",
                                            "ip": "10.0.0.1",
                                            "mac": "AA:BB:CC:DD:EE:FF",
                                            "hw_type": "GA",
                                            "is_online": True,
                                            "is_adopted": True,
                                            "is_connected": True,
                                            "is_rebooting": False,
                                            "is_unavailable": False,
                                            "adopting": False,
                                            "connected_uah_id": "hub-1",
                                            "location_id": "door-1",
                                            "model": "G3 Pro",
                                            "display_model": "Access Reader G3 Pro",
                                            # Fields that should be stripped:
                                            "configs": [{"key": "k1", "value": "v1"}],
                                            "images": {"xs": "https://example.com/img.png"},
                                            "location": {"name": "Front Door", "unique_id": "door-1"},
                                            "door": {"name": "Front Door", "unique_id": "door-1"},
                                            "floor": {"name": "1F", "unique_id": "floor-1"},
                                            "extensions": [{"extension_name": "port_setting"}],
                                            "update_manual": {"completed": False},
                                            "capabilities": ["cap1", "cap2"],
                                            "guid": "some-guid",
                                            "source": None,
                                            "bom_rev": "",
                                            "revision": "123456",
                                        },
                                    ]
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            devices = await device_mgr_proxy.list_devices(compact=True)

        assert len(devices) == 1
        dev = devices[0]
        # Essential fields kept
        assert dev["unique_id"] == "dev-2"
        assert dev["name"] == "Reader G2"
        assert dev["device_type"] == "UA-G3"
        assert dev["firmware"] == "v3.17.11.0"
        assert dev["ip"] == "10.0.0.1"
        assert dev["is_online"] is True
        assert dev["_door_name"] == "Front Door"
        # Bloat fields stripped
        assert "configs" not in dev
        assert "images" not in dev
        assert "location" not in dev
        assert "door" not in dev
        assert "floor" not in dev
        assert "extensions" not in dev
        assert "update_manual" not in dev
        assert "capabilities" not in dev
        assert "guid" not in dev
        assert "source" not in dev
        assert "bom_rev" not in dev
        assert "revision" not in dev

    @pytest.mark.asyncio
    async def test_list_devices_no_auth(self, device_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await device_mgr_none.list_devices()


# ---------------------------------------------------------------------------
# get_device
# ---------------------------------------------------------------------------


class TestGetDevice:
    @pytest.mark.asyncio
    async def test_get_device_api(self, device_mgr_api, cm_api):
        mock_device = MagicMock()
        mock_device.id = "dev-1"
        mock_device.name = "Hub Pro"
        mock_device.type = "hub"
        mock_device.connected = True
        mock_device.firmware_version = "2.1.0"
        mock_device.mac = "AA:BB:CC:DD:EE:FF"
        mock_device.ip = "192.168.1.100"

        cm_api._api_client.get_device = AsyncMock(return_value=mock_device)

        detail = await device_mgr_api.get_device("dev-1")

        assert detail["id"] == "dev-1"
        assert detail["mac"] == "AA:BB:CC:DD:EE:FF"

    @pytest.mark.asyncio
    async def test_get_device_proxy(self, device_mgr_proxy, cm_proxy):
        """get_device finds device by unique_id from nested topology."""
        topology = [
            {
                "name": "Site",
                "unique_id": "site-1",
                "floors": [
                    {
                        "name": "1F",
                        "unique_id": "floor-1",
                        "doors": [
                            {
                                "name": "Front Door",
                                "unique_id": "door-1",
                                "device_groups": [
                                    [
                                        {"unique_id": "dev-1", "name": "Hub Pro"},
                                        {"unique_id": "dev-2", "name": "Reader G2", "device_type": "reader"},
                                    ]
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            detail = await device_mgr_proxy.get_device("dev-2")
        assert detail["unique_id"] == "dev-2"
        assert detail["name"] == "Reader G2"
        mock_req.assert_awaited_once_with("GET", "devices/topology4")

    @pytest.mark.asyncio
    async def test_get_device_proxy_not_found(self, device_mgr_proxy, cm_proxy):
        """get_device raises ValueError when device ID not found in topology."""
        topology = [{"name": "Site", "unique_id": "s", "floors": [{"name": "1F", "unique_id": "f", "doors": []}]}]
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            with pytest.raises(UniFiNotFoundError):
                await device_mgr_proxy.get_device("missing-dev")

    @pytest.mark.asyncio
    async def test_get_device_empty_id(self, device_mgr_api):
        with pytest.raises(ValueError, match="device_id is required"):
            await device_mgr_api.get_device("")

    @pytest.mark.asyncio
    async def test_get_device_no_auth(self, device_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No auth path"):
            await device_mgr_none.get_device("dev-1")


# ---------------------------------------------------------------------------
# reboot_device (preview)
# ---------------------------------------------------------------------------


class TestRebootDevice:
    @pytest.mark.asyncio
    async def test_reboot_device_preview_api(self, device_mgr_api, cm_api):
        mock_device = MagicMock()
        mock_device.id = "dev-1"
        mock_device.name = "Hub Pro"
        mock_device.type = "hub"
        mock_device.connected = True
        mock_device.firmware_version = "2.1.0"
        mock_device.mac = "AA:BB:CC:DD:EE:FF"
        mock_device.ip = "192.168.1.100"

        cm_api._api_client.get_device = AsyncMock(return_value=mock_device)

        preview = await device_mgr_api.reboot_device("dev-1")

        assert preview["device_id"] == "dev-1"
        assert preview["device_name"] == "Hub Pro"
        assert preview["proposed_changes"]["action"] == "reboot"

    @pytest.mark.asyncio
    async def test_reboot_device_empty_id(self, device_mgr_api):
        with pytest.raises(ValueError, match="device_id is required"):
            await device_mgr_api.reboot_device("")


# ---------------------------------------------------------------------------
# apply_reboot_device
# ---------------------------------------------------------------------------


class TestApplyRebootDevice:
    @pytest.mark.asyncio
    async def test_apply_reboot_success(self, device_mgr_proxy, cm_proxy):
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {}
            result = await device_mgr_proxy.apply_reboot_device("dev-1")
        assert result["result"] == "success"
        assert result["action"] == "reboot"
        mock_req.assert_awaited_once_with("POST", "devices/dev-1/reboot")

    @pytest.mark.asyncio
    async def test_apply_reboot_no_proxy(self, device_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await device_mgr_none.apply_reboot_device("dev-1")


# ---------------------------------------------------------------------------
# Device-config helpers
# ---------------------------------------------------------------------------


def _topology_with(device: dict) -> list:
    """Wrap a single device dict in the nested topology4 tree shape."""
    return [
        {
            "name": "Site",
            "unique_id": "site-1",
            "floors": [
                {
                    "name": "1F",
                    "unique_id": "floor-1",
                    "doors": [
                        {
                            "name": "Front Door",
                            "unique_id": "door-1",
                            "device_groups": [[device]],
                        }
                    ],
                }
            ],
        }
    ]


# A camera-class reader carries a 24-hex Protect-style id → is_camera=true.
_READER_ID = "a1b2c3d4e5f607182930abcd"
# A hub carries a MAC-style (12-hex) id → is_camera=false.
_HUB_ID = "aabbccddeeff"


def _reader_with_configs(configs: list) -> dict:
    return {"unique_id": _READER_ID, "name": "Entry Reader", "device_type": "UA-G6", "configs": configs}


_GREETING_CONFIGS = [
    {"device_id": _READER_ID, "key": "show_entry_greet", "value": "yes", "tag": "device_setting"},
    {"device_id": _READER_ID, "key": "greeting_text", "value": "welcome", "tag": "device_setting"},
    {"device_id": _READER_ID, "key": "greeting_broadcast_name", "value": "first_name_only", "tag": "device_setting"},
    {"device_id": _READER_ID, "key": "ssh_password", "value": "s3cr3t", "tag": "credential"},
]


class TestGetDeviceConfigs:
    @pytest.mark.asyncio
    async def test_returns_configs_and_identity(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            info = await device_mgr_proxy.get_device_configs(_READER_ID)
        assert info["device_id"] == _READER_ID
        assert info["device_name"] == "Entry Reader"
        assert info["is_camera"] is True
        assert info["configs"] == _GREETING_CONFIGS
        mock_req.assert_awaited_once_with("GET", "devices/topology4")

    @pytest.mark.asyncio
    async def test_hub_is_not_camera(self, device_mgr_proxy, cm_proxy):
        hub = {"unique_id": _HUB_ID, "name": "Door Hub", "configs": []}
        topology = _topology_with(hub)
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            info = await device_mgr_proxy.get_device_configs(_HUB_ID)
        assert info["is_camera"] is False
        assert info["configs"] == []

    @pytest.mark.asyncio
    async def test_device_without_configs_key_returns_empty_list(self, device_mgr_proxy, cm_proxy):
        reader = {"unique_id": _READER_ID, "name": "Reader"}
        topology = _topology_with(reader)
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            info = await device_mgr_proxy.get_device_configs(_READER_ID)
        assert info["configs"] == []

    @pytest.mark.asyncio
    async def test_not_found_raises(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs([]))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            with pytest.raises(UniFiNotFoundError):
                await device_mgr_proxy.get_device_configs("no-such-device")

    @pytest.mark.asyncio
    async def test_empty_id_raises(self, device_mgr_proxy):
        with pytest.raises(ValueError, match="device_id is required"):
            await device_mgr_proxy.get_device_configs("")

    @pytest.mark.asyncio
    async def test_no_proxy_raises(self, device_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await device_mgr_none.get_device_configs(_READER_ID)


class TestUpdateDeviceConfigPreview:
    @pytest.mark.asyncio
    async def test_preview_shows_current_and_proposed(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            preview = await device_mgr_proxy.update_device_config(_READER_ID, {"show_entry_greet": "no"})
        assert preview["device_id"] == _READER_ID
        assert preview["current_state"] == {"show_entry_greet": "yes"}
        assert preview["proposed_changes"] == {"show_entry_greet": "no"}

    @pytest.mark.asyncio
    async def test_preview_rejects_unknown_key(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            with pytest.raises(ValueError, match="Unknown config key"):
                await device_mgr_proxy.update_device_config(_READER_ID, {"bogus_key": "x"})

    @pytest.mark.asyncio
    async def test_preview_rejects_credential_key(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            with pytest.raises(ValueError, match="credential/secret"):
                await device_mgr_proxy.update_device_config(_READER_ID, {"ssh_password": "new"})

    @pytest.mark.asyncio
    async def test_preview_rejects_empty_updates(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            with pytest.raises(ValueError, match="No config updates"):
                await device_mgr_proxy.update_device_config(_READER_ID, {})


class TestApplyUpdateDeviceConfig:
    @pytest.mark.asyncio
    async def test_apply_puts_key_tag_value_array_with_is_camera(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [{"data": topology}, {"code": 1, "codeS": "SUCCESS"}]
            result = await device_mgr_proxy.apply_update_device_config(
                _READER_ID, {"show_entry_greet": "no", "greeting_text": "hello"}
            )
        assert result["result"] == "success"
        assert result["updated_keys"] == ["show_entry_greet", "greeting_text"]
        assert result["is_camera"] is True
        put_call = mock_req.await_args_list[1]
        assert put_call.args == ("PUT", f"device/{_READER_ID}/configs")
        assert put_call.kwargs["params"] == {"is_camera": "true"}
        assert put_call.kwargs["json"] == [
            {"key": "show_entry_greet", "tag": "device_setting", "value": "no"},
            {"key": "greeting_text", "tag": "device_setting", "value": "hello"},
        ]

    @pytest.mark.asyncio
    async def test_apply_hub_uses_is_camera_false(self, device_mgr_proxy, cm_proxy):
        hub_configs = [{"device_id": _HUB_ID, "key": "led_mode", "value": "on", "tag": "device_setting"}]
        hub = {"unique_id": _HUB_ID, "name": "Door Hub", "configs": hub_configs}
        topology = _topology_with(hub)
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [{"data": topology}, {"code": 1}]
            result = await device_mgr_proxy.apply_update_device_config(_HUB_ID, {"led_mode": "off"})
        assert result["is_camera"] is False
        assert mock_req.await_args_list[1].kwargs["params"] == {"is_camera": "false"}

    @pytest.mark.asyncio
    async def test_apply_is_camera_override_respected(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.side_effect = [{"data": topology}, {"code": 1}]
            await device_mgr_proxy.apply_update_device_config(_READER_ID, {"show_entry_greet": "no"}, is_camera=False)
        assert mock_req.await_args_list[1].kwargs["params"] == {"is_camera": "false"}

    @pytest.mark.asyncio
    async def test_apply_rejects_unknown_key(self, device_mgr_proxy, cm_proxy):
        topology = _topology_with(_reader_with_configs(_GREETING_CONFIGS))
        with patch.object(cm_proxy, "proxy_request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = {"data": topology}
            with pytest.raises(ValueError, match="Unknown config key"):
                await device_mgr_proxy.apply_update_device_config(_READER_ID, {"bogus": "x"})

    @pytest.mark.asyncio
    async def test_apply_no_proxy_raises(self, device_mgr_none):
        with pytest.raises(UniFiConnectionError, match="No proxy session"):
            await device_mgr_none.apply_update_device_config(_READER_ID, {"show_entry_greet": "no"})


# ---------------------------------------------------------------------------
# MCP tool layer: access_get_device_configs / access_update_device_config
# ---------------------------------------------------------------------------


def _configs_info() -> dict:
    return {
        "device_id": _READER_ID,
        "device_name": "Entry Reader",
        "is_camera": True,
        "configs": [
            {"device_id": _READER_ID, "key": "show_entry_greet", "value": "yes", "tag": "device_setting"},
            {"device_id": _READER_ID, "key": "ssh_password", "value": "s3cr3t", "tag": "credential"},
            {"device_id": _READER_ID, "key": "nacl_private_key", "value": "AbCd==", "tag": "device_extra"},
        ],
    }


class TestGetDeviceConfigsTool:
    @pytest.mark.asyncio
    async def test_redacts_credential_and_sensitive_values_by_default(self):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            mock_mgr.get_device_configs = AsyncMock(return_value=_configs_info())
            from unifi_access_mcp.tools.devices import access_get_device_configs

            result = await access_get_device_configs(_READER_ID)

        configs = result["data"]["configs"]
        by_key = {c["key"]: c for c in configs}
        assert result["success"] is True
        assert by_key["ssh_password"]["value"] == REDACTED
        assert by_key["nacl_private_key"]["value"] == REDACTED
        assert by_key["show_entry_greet"]["value"] == "yes"

    @pytest.mark.asyncio
    async def test_policy_disable_returns_raw_values(self, monkeypatch):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            mock_mgr.get_device_configs = AsyncMock(return_value=_configs_info())
            from unifi_access_mcp.tools.devices import access_get_device_configs

            monkeypatch.setenv("UNIFI_ACCESS_REDACT_SENSITIVE_FIELDS", "false")
            result = await access_get_device_configs(_READER_ID)

        by_key = {c["key"]: c for c in result["data"]["configs"]}
        assert by_key["ssh_password"]["value"] == "s3cr3t"

    @pytest.mark.asyncio
    async def test_not_found_returns_error_envelope(self):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            mock_mgr.get_device_configs = AsyncMock(side_effect=UniFiNotFoundError("device", "x"))
            from unifi_access_mcp.tools.devices import access_get_device_configs

            result = await access_get_device_configs("x")

        assert result["success"] is False
        assert "error" in result


class TestUpdateDeviceConfigTool:
    @pytest.mark.asyncio
    async def test_preview_returns_requires_confirmation(self):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            mock_mgr.update_device_config = AsyncMock(
                return_value={
                    "device_id": _READER_ID,
                    "device_name": "Entry Reader",
                    "current_state": {"show_entry_greet": "yes"},
                    "proposed_changes": {"show_entry_greet": "no"},
                }
            )
            from unifi_access_mcp.tools.devices import access_update_device_config

            result = await access_update_device_config(_READER_ID, {"show_entry_greet": "no"}, confirm=False)

        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["current"] == {"show_entry_greet": "yes"}
        assert result["preview"]["proposed"] == {"show_entry_greet": "no"}

    @pytest.mark.asyncio
    async def test_confirm_calls_apply_and_returns_success(self):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            apply_result = {
                "device_id": _READER_ID,
                "action": "update_config",
                "result": "success",
                "updated_keys": ["show_entry_greet"],
                "is_camera": True,
            }
            mock_mgr.apply_update_device_config = AsyncMock(return_value=apply_result)
            from unifi_access_mcp.tools.devices import access_update_device_config

            result = await access_update_device_config(_READER_ID, {"show_entry_greet": "no"}, confirm=True)

        assert result["success"] is True
        assert result["data"] == apply_result
        mock_mgr.apply_update_device_config.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirm_passes_is_camera_override(self):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            mock_mgr.apply_update_device_config = AsyncMock(return_value={"result": "success"})
            from unifi_access_mcp.tools.devices import access_update_device_config

            await access_update_device_config(_READER_ID, {"show_entry_greet": "no"}, is_camera=False, confirm=True)

        _, kwargs = mock_mgr.apply_update_device_config.await_args
        assert kwargs.get("is_camera") is False

    @pytest.mark.asyncio
    async def test_validation_error_returns_error_envelope(self):
        with patch("unifi_access_mcp.tools.devices.device_manager") as mock_mgr:
            mock_mgr.update_device_config = AsyncMock(side_effect=ValueError("Unknown config key(s): ['x']"))
            from unifi_access_mcp.tools.devices import access_update_device_config

            result = await access_update_device_config(_READER_ID, {"x": "1"}, confirm=False)

        assert result["success"] is False
        assert "Unknown config key" in result["error"]
