"""Tests for device managers (Light, Sensor, Chime) and device tools."""

from datetime import datetime, timedelta, timezone
from enum import Enum
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from unifi_core.exceptions import UniFiNotFoundError

# ---------------------------------------------------------------------------
# Fake enum types
# ---------------------------------------------------------------------------


class _FakeStateType(Enum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"


class _FakeLightModeType(Enum):
    MOTION = "motion"
    WHEN_DARK = "always"
    MANUAL = "off"


class _FakeLightModeEnableType(Enum):
    DARK = "dark"
    ALWAYS = "fulltime"


class _FakeMountType(Enum):
    DOOR = "door"
    WINDOW = "window"
    LEAK = "leak"


class _FakeSensorStatusType(Enum):
    SAFE = "safe"
    WARNING = "warning"


# ---------------------------------------------------------------------------
# Mock factory: Light
# ---------------------------------------------------------------------------


def _make_light(**overrides):
    """Build a mock Light object."""
    light = MagicMock()
    light.id = overrides.get("id", "light-001")
    light.name = overrides.get("name", "Front Flood")
    light.type = overrides.get("type", "UP FloodLight")
    light.market_name = overrides.get("market_name", "Floodlight")
    light.state = overrides.get("state", _FakeStateType.CONNECTED)
    light.is_connected = overrides.get("is_connected", True)
    light.firmware_version = overrides.get("firmware_version", "2.8.35")
    light.last_seen = overrides.get("last_seen", datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc))
    light.is_light_on = overrides.get("is_light_on", False)
    light.is_dark = overrides.get("is_dark", True)
    light.is_pir_motion_detected = overrides.get("is_pir_motion_detected", False)
    light.last_motion = overrides.get("last_motion", datetime(2026, 3, 16, 11, 30, tzinfo=timezone.utc))
    light.camera_id = overrides.get("camera_id", "cam-001")
    light.is_camera_paired = overrides.get("is_camera_paired", True)

    # Device settings
    ds = MagicMock()
    ds.is_indicator_enabled = overrides.get("is_indicator_enabled", True)
    ds.led_level = overrides.get("led_level", 6)
    ds.pir_duration = overrides.get("pir_duration", timedelta(seconds=30))
    ds.pir_sensitivity = overrides.get("pir_sensitivity", 50)
    light.light_device_settings = ds

    # Light on settings
    light_on = MagicMock()
    light_on.is_led_force_on = overrides.get("is_led_force_on", False)
    light.light_on_settings = light_on

    # Mode settings
    ms = MagicMock()
    ms.mode = overrides.get("light_mode", _FakeLightModeType.MOTION)
    ms.enable_at = overrides.get("enable_at", _FakeLightModeEnableType.DARK)
    light.light_mode_settings = ms

    # Async methods
    light.set_light = AsyncMock()
    light.set_led_level = AsyncMock()
    light.set_sensitivity = AsyncMock()
    light.set_duration = AsyncMock()
    light.set_status_light = AsyncMock()
    light.set_name = AsyncMock()

    return light


# ---------------------------------------------------------------------------
# Mock factory: Sensor
# ---------------------------------------------------------------------------


def _make_sensor(**overrides):
    """Build a mock Sensor object."""
    sensor = MagicMock()
    sensor.id = overrides.get("id", "sensor-001")
    sensor.name = overrides.get("name", "Front Door Sensor")
    sensor.type = overrides.get("type", "UP Sensor")
    sensor.market_name = overrides.get("market_name", "Protect Sensor")
    sensor.state = overrides.get("state", _FakeStateType.CONNECTED)
    sensor.is_connected = overrides.get("is_connected", True)
    sensor.firmware_version = overrides.get("firmware_version", "1.3.0")
    sensor.last_seen = overrides.get("last_seen", datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc))
    sensor.mount_type = overrides.get("mount_type", _FakeMountType.DOOR)
    sensor.is_motion_detected = overrides.get("is_motion_detected", False)
    sensor.is_opened = overrides.get("is_opened", False)
    sensor.motion_detected_at = overrides.get("motion_detected_at", None)
    sensor.open_status_changed_at = overrides.get("open_status_changed_at", None)
    sensor.alarm_triggered_at = overrides.get("alarm_triggered_at", None)
    sensor.leak_detected_at = overrides.get("leak_detected_at", None)
    sensor.tampering_detected_at = overrides.get("tampering_detected_at", None)
    sensor.camera_id = overrides.get("camera_id", None)

    # Battery status
    battery = MagicMock()
    battery.percentage = overrides.get("battery_percentage", 95)
    battery.is_low = overrides.get("battery_is_low", False)
    sensor.battery_status = battery

    # Stats
    stats = MagicMock()
    for stat_name in ("light", "humidity", "temperature"):
        stat = MagicMock()
        stat.value = overrides.get(f"{stat_name}_value", 22.5 if stat_name == "temperature" else 50.0)
        stat.status = overrides.get(f"{stat_name}_status", _FakeSensorStatusType.SAFE)
        setattr(stats, stat_name, stat)
    sensor.stats = stats

    return sensor


# ---------------------------------------------------------------------------
# Mock factory: Chime
# ---------------------------------------------------------------------------


def _make_chime(**overrides):
    """Build a mock Chime object."""
    chime = MagicMock()
    chime.id = overrides.get("id", "chime-001")
    chime.name = overrides.get("name", "Front Door Chime")
    chime.type = overrides.get("type", "UP Chime")
    chime.market_name = overrides.get("market_name", "Protect Chime")
    chime.state = overrides.get("state", _FakeStateType.CONNECTED)
    chime.is_connected = overrides.get("is_connected", True)
    chime.firmware_version = overrides.get("firmware_version", "1.0.12")
    chime.last_seen = overrides.get("last_seen", datetime(2026, 3, 16, 12, 0, tzinfo=timezone.utc))
    chime.volume = overrides.get("volume", 80)
    chime.last_ring = overrides.get("last_ring", datetime(2026, 3, 16, 11, 0, tzinfo=timezone.utc))
    chime.camera_ids = overrides.get("camera_ids", ["cam-001", "cam-002"])
    chime.repeat_times = overrides.get("repeat_times", 1)

    # Ring settings
    rs = MagicMock()
    rs.camera_id = "cam-001"
    rs.volume = 80
    rs.repeat_times = 1
    rs.ringtone_id = None
    rs.track_no = 0
    chime.ring_settings = overrides.get("ring_settings", [rs])

    # Speaker tracks
    track = MagicMock()
    track.track_no = 0
    track.name = "Default"
    track.state = "ready"
    chime.speaker_track_list = overrides.get("speaker_track_list", [track])

    # Async methods
    chime.play = AsyncMock()
    chime.play_buzzer = AsyncMock()
    chime.set_volume = AsyncMock()
    chime.set_repeat_times = AsyncMock()
    chime.set_name = AsyncMock()

    return chime


# ---------------------------------------------------------------------------
# Bootstrap and CM fixtures
# ---------------------------------------------------------------------------


def _make_bootstrap(lights=None, sensors=None, chimes=None):
    bs = MagicMock()
    bs.lights = lights or {}
    bs.sensors = sensors or {}
    bs.chimes = chimes or {}
    return bs


@pytest.fixture
def mock_cm_lights():
    cm = MagicMock()
    light = _make_light()
    cm.client.bootstrap = _make_bootstrap(lights={"light-001": light})
    return cm


@pytest.fixture
def mock_cm_sensors():
    cm = MagicMock()
    sensor = _make_sensor()
    cm.client.bootstrap = _make_bootstrap(sensors={"sensor-001": sensor})
    return cm


@pytest.fixture
def mock_cm_chimes():
    cm = MagicMock()
    chime = _make_chime()
    cm.client.bootstrap = _make_bootstrap(chimes={"chime-001": chime})
    return cm


# ===========================================================================
# LightManager tests
# ===========================================================================


class TestLightManagerListLights:
    @pytest.mark.asyncio
    async def test_empty(self):
        from unifi_core.protect.managers.light_manager import LightManager

        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(lights={})
        mgr = LightManager(cm)
        result = await mgr.list_lights()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_light(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        lights = await mgr.list_lights()
        assert len(lights) == 1
        light = lights[0]
        assert light["id"] == "light-001"
        assert light["name"] == "Front Flood"
        assert light["is_light_on"] is False
        assert light["is_dark"] is True
        assert light["device_settings"]["led_level"] == 6
        assert light["device_settings"]["pir_sensitivity"] == 50

    @pytest.mark.asyncio
    async def test_multiple_lights(self):
        from unifi_core.protect.managers.light_manager import LightManager

        cm = MagicMock()
        light1 = _make_light(id="light-001", name="Front")
        light2 = _make_light(id="light-002", name="Back", is_light_on=True)
        cm.client.bootstrap = _make_bootstrap(lights={"light-001": light1, "light-002": light2})
        mgr = LightManager(cm)
        lights = await mgr.list_lights()
        assert len(lights) == 2


class TestLightManagerUpdateLight:
    @pytest.mark.asyncio
    async def test_preview(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        result = await mgr.update_light("light-001", {"light_on": True})
        assert result["light_id"] == "light-001"
        assert result["current_state"]["light_on"] is False
        assert result["proposed_changes"]["light_on"] is True

    @pytest.mark.asyncio
    async def test_multiple_settings(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        result = await mgr.update_light("light-001", {"led_level": 3, "sensitivity": 80})
        assert result["proposed_changes"]["led_level"] == 3
        assert result["proposed_changes"]["sensitivity"] == 80

    @pytest.mark.asyncio
    async def test_not_found(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        with pytest.raises(UniFiNotFoundError):
            await mgr.update_light("bad-id", {"light_on": True})


class TestLightManagerApply:
    @pytest.mark.asyncio
    async def test_apply_light_on(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        light = mock_cm_lights.client.bootstrap.lights["light-001"]
        result = await mgr.apply_light_settings("light-001", {"light_on": True})
        assert "light_on=True" in result["applied"]
        light.set_light.assert_awaited_once_with(True)

    @pytest.mark.asyncio
    async def test_apply_led_level(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        light = mock_cm_lights.client.bootstrap.lights["light-001"]
        result = await mgr.apply_light_settings("light-001", {"led_level": 3})
        assert "led_level=3" in result["applied"]
        light.set_led_level.assert_awaited_once_with(3)

    @pytest.mark.asyncio
    async def test_apply_duration(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        mgr = LightManager(mock_cm_lights)
        light = mock_cm_lights.client.bootstrap.lights["light-001"]
        result = await mgr.apply_light_settings("light-001", {"duration_seconds": 60})
        assert "duration_seconds=60" in result["applied"]
        light.set_duration.assert_awaited_once_with(timedelta(seconds=60))

    @pytest.mark.asyncio
    async def test_apply_error(self, mock_cm_lights):
        from unifi_core.protect.managers.light_manager import LightManager

        light = mock_cm_lights.client.bootstrap.lights["light-001"]
        light.set_light = AsyncMock(side_effect=RuntimeError("API error"))
        mgr = LightManager(mock_cm_lights)
        result = await mgr.apply_light_settings("light-001", {"light_on": True})
        assert "errors" in result
        assert any("API error" in e for e in result["errors"])


# ===========================================================================
# SensorManager tests
# ===========================================================================


class TestSensorManagerListSensors:
    @pytest.mark.asyncio
    async def test_empty(self):
        from unifi_core.protect.managers.sensor_manager import SensorManager

        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(sensors={})
        mgr = SensorManager(cm)
        result = await mgr.list_sensors()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_sensor(self, mock_cm_sensors):
        from unifi_core.protect.managers.sensor_manager import SensorManager

        mgr = SensorManager(mock_cm_sensors)
        sensors = await mgr.list_sensors()
        assert len(sensors) == 1
        s = sensors[0]
        assert s["id"] == "sensor-001"
        assert s["name"] == "Front Door Sensor"
        assert s["battery"]["percentage"] == 95
        assert s["battery"]["is_low"] is False
        assert s["mount_type"] == "door"
        assert "temperature" in s["stats"]
        assert s["stats"]["temperature"]["value"] == 22.5

    @pytest.mark.asyncio
    async def test_multiple_sensors(self):
        from unifi_core.protect.managers.sensor_manager import SensorManager

        cm = MagicMock()
        s1 = _make_sensor(id="sensor-001", name="Front Door")
        s2 = _make_sensor(id="sensor-002", name="Garage", is_opened=True)
        cm.client.bootstrap = _make_bootstrap(sensors={"sensor-001": s1, "sensor-002": s2})
        mgr = SensorManager(cm)
        sensors = await mgr.list_sensors()
        assert len(sensors) == 2

    @pytest.mark.asyncio
    async def test_sensor_with_detections(self):
        from unifi_core.protect.managers.sensor_manager import SensorManager

        ts = datetime(2026, 3, 16, 11, 45, tzinfo=timezone.utc)
        s = _make_sensor(
            is_motion_detected=True,
            motion_detected_at=ts,
            is_opened=True,
            open_status_changed_at=ts,
        )
        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(sensors={"sensor-001": s})
        mgr = SensorManager(cm)
        sensors = await mgr.list_sensors()
        assert sensors[0]["is_motion_detected"] is True
        assert sensors[0]["motion_detected_at"] == ts.isoformat()
        assert sensors[0]["is_opened"] is True


# ===========================================================================
# ChimeManager tests
# ===========================================================================


class TestChimeManagerListChimes:
    @pytest.mark.asyncio
    async def test_empty(self):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        cm = MagicMock()
        cm.client.bootstrap = _make_bootstrap(chimes={})
        mgr = ChimeManager(cm)
        result = await mgr.list_chimes()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_chime(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        chimes = await mgr.list_chimes()
        assert len(chimes) == 1
        c = chimes[0]
        assert c["id"] == "chime-001"
        assert c["name"] == "Front Door Chime"
        assert c["volume"] == 80
        assert len(c["ring_settings"]) == 1
        assert len(c["available_tracks"]) == 1
        assert c["available_tracks"][0]["name"] == "Default"


class TestChimeManagerUpdateChime:
    @pytest.mark.asyncio
    async def test_preview(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        result = await mgr.update_chime("chime-001", {"volume": 50})
        assert result["chime_id"] == "chime-001"
        assert result["current_state"]["volume"] == 80
        assert result["proposed_changes"]["volume"] == 50

    @pytest.mark.asyncio
    async def test_not_found(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        with pytest.raises(UniFiNotFoundError):
            await mgr.update_chime("bad-id", {"volume": 50})


class TestChimeManagerApply:
    @pytest.mark.asyncio
    async def test_apply_volume(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        chime = mock_cm_chimes.client.bootstrap.chimes["chime-001"]
        result = await mgr.apply_chime_settings("chime-001", {"volume": 50})
        assert "volume=50" in result["applied"]
        chime.set_volume.assert_awaited_once_with(50)

    @pytest.mark.asyncio
    async def test_apply_repeat_times(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        chime = mock_cm_chimes.client.bootstrap.chimes["chime-001"]
        result = await mgr.apply_chime_settings("chime-001", {"repeat_times": 3})
        assert "repeat_times=3" in result["applied"]
        chime.set_repeat_times.assert_awaited_once_with(3)

    @pytest.mark.asyncio
    async def test_apply_error(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        chime = mock_cm_chimes.client.bootstrap.chimes["chime-001"]
        chime.set_volume = AsyncMock(side_effect=RuntimeError("API error"))
        mgr = ChimeManager(mock_cm_chimes)
        result = await mgr.apply_chime_settings("chime-001", {"volume": 50})
        assert "errors" in result


class TestChimeManagerTrigger:
    @pytest.mark.asyncio
    async def test_trigger_default(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        chime = mock_cm_chimes.client.bootstrap.chimes["chime-001"]
        result = await mgr.trigger_chime("chime-001")
        assert result["triggered"] is True
        assert result["volume"] == 80
        chime.play.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_trigger_with_overrides(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        chime = mock_cm_chimes.client.bootstrap.chimes["chime-001"]
        result = await mgr.trigger_chime("chime-001", volume=50, repeat_times=3)
        assert result["triggered"] is True
        assert result["volume"] == 50
        assert result["repeat_times"] == 3
        chime.play.assert_awaited_once_with(volume=50, repeat_times=3)

    @pytest.mark.asyncio
    async def test_trigger_not_found(self, mock_cm_chimes):
        from unifi_core.protect.managers.chime_manager import ChimeManager

        mgr = ChimeManager(mock_cm_chimes)
        with pytest.raises(UniFiNotFoundError):
            await mgr.trigger_chime("bad-id")


# ===========================================================================
# Device tools tests
# ===========================================================================


@pytest.fixture
def mock_light_manager():
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.devices.light_manager", mgr):
        yield mgr


@pytest.fixture
def mock_sensor_manager():
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.devices.sensor_manager", mgr):
        yield mgr


@pytest.fixture
def mock_chime_manager():
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.devices.chime_manager", mgr):
        yield mgr


class TestProtectListLightsTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_light_manager):
        from unifi_protect_mcp.tools.devices import protect_list_lights

        mock_light_manager.list_lights = AsyncMock(return_value=[{"id": "light-001", "name": "Front Flood"}])
        result = await protect_list_lights()
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_empty(self, mock_light_manager):
        from unifi_protect_mcp.tools.devices import protect_list_lights

        mock_light_manager.list_lights = AsyncMock(return_value=[])
        result = await protect_list_lights()
        assert result["success"] is True
        assert result["data"]["count"] == 0

    @pytest.mark.asyncio
    async def test_error(self, mock_light_manager):
        from unifi_protect_mcp.tools.devices import protect_list_lights

        mock_light_manager.list_lights = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_list_lights()
        assert result["success"] is False


class TestProtectUpdateLightTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_light_manager):
        from unifi_protect_mcp.tools.devices import protect_update_light

        mock_light_manager.update_light = AsyncMock(
            return_value={
                "light_id": "light-001",
                "light_name": "Front Flood",
                "current_state": {"light_on": False},
                "proposed_changes": {"light_on": True},
            }
        )
        result = await protect_update_light("light-001", {"is_light_on": True}, confirm=False)
        assert result["success"] is True
        assert result["requires_confirmation"] is True

    @pytest.mark.asyncio
    async def test_confirm(self, mock_light_manager):
        from unifi_protect_mcp.tools.devices import protect_update_light

        mock_light_manager.update_light = AsyncMock(
            return_value={
                "light_id": "light-001",
                "light_name": "Front Flood",
                "current_state": {"light_on": False},
                "proposed_changes": {"light_on": True},
            }
        )
        mock_light_manager.apply_light_settings = AsyncMock(
            return_value={"light_id": "light-001", "applied": ["light_on=True"]}
        )
        result = await protect_update_light("light-001", {"is_light_on": True}, confirm=True)
        assert result["success"] is True
        assert "applied" in result["data"]

    @pytest.mark.asyncio
    async def test_empty_settings(self, mock_light_manager):
        from unifi_protect_mcp.tools.devices import protect_update_light

        result = await protect_update_light("light-001", {}, confirm=False)
        assert result["success"] is False
        assert "No settings" in result["error"]


class TestProtectListSensorsTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_sensor_manager):
        from unifi_protect_mcp.tools.devices import protect_list_sensors

        mock_sensor_manager.list_sensors = AsyncMock(return_value=[{"id": "sensor-001", "name": "Front Door"}])
        result = await protect_list_sensors()
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_error(self, mock_sensor_manager):
        from unifi_protect_mcp.tools.devices import protect_list_sensors

        mock_sensor_manager.list_sensors = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_list_sensors()
        assert result["success"] is False


class TestProtectListChimesTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_list_chimes

        mock_chime_manager.list_chimes = AsyncMock(return_value=[{"id": "chime-001", "name": "Front Door Chime"}])
        result = await protect_list_chimes()
        assert result["success"] is True
        assert result["data"]["count"] == 1

    @pytest.mark.asyncio
    async def test_error(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_list_chimes

        mock_chime_manager.list_chimes = AsyncMock(side_effect=RuntimeError("fail"))
        result = await protect_list_chimes()
        assert result["success"] is False


class TestProtectUpdateChimeTool:
    @pytest.mark.asyncio
    async def test_preview(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_update_chime

        mock_chime_manager.update_chime = AsyncMock(
            return_value={
                "chime_id": "chime-001",
                "chime_name": "Front Door Chime",
                "current_state": {"volume": 80},
                "proposed_changes": {"volume": 50},
            }
        )
        result = await protect_update_chime("chime-001", {"volume": 50}, confirm=False)
        assert result["success"] is True
        assert result["requires_confirmation"] is True

    @pytest.mark.asyncio
    async def test_confirm(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_update_chime

        mock_chime_manager.update_chime = AsyncMock(
            return_value={
                "chime_id": "chime-001",
                "chime_name": "Front Door Chime",
                "current_state": {"volume": 80},
                "proposed_changes": {"volume": 50},
            }
        )
        mock_chime_manager.apply_chime_settings = AsyncMock(
            return_value={"chime_id": "chime-001", "applied": ["volume=50"]}
        )
        result = await protect_update_chime("chime-001", {"volume": 50}, confirm=True)
        assert result["success"] is True
        assert "applied" in result["data"]

    @pytest.mark.asyncio
    async def test_empty_settings(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_update_chime

        result = await protect_update_chime("chime-001", {}, confirm=False)
        assert result["success"] is False


class TestProtectTriggerChimeTool:
    @pytest.mark.asyncio
    async def test_success(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_trigger_chime

        mock_chime_manager.trigger_chime = AsyncMock(
            return_value={"chime_id": "chime-001", "triggered": True, "volume": 80}
        )
        result = await protect_trigger_chime("chime-001")
        assert result["success"] is True
        assert result["data"]["triggered"] is True

    @pytest.mark.asyncio
    async def test_with_overrides(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_trigger_chime

        mock_chime_manager.trigger_chime = AsyncMock(
            return_value={"chime_id": "chime-001", "triggered": True, "volume": 50, "repeat_times": 3}
        )
        result = await protect_trigger_chime("chime-001", volume=50, repeat_times=3)
        assert result["success"] is True
        assert result["data"]["volume"] == 50

    @pytest.mark.asyncio
    async def test_not_found(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_trigger_chime

        mock_chime_manager.trigger_chime = AsyncMock(side_effect=ValueError("Chime not found: bad-id"))
        result = await protect_trigger_chime("bad-id")
        assert result["success"] is False
        assert "Chime not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error(self, mock_chime_manager):
        from unifi_protect_mcp.tools.devices import protect_trigger_chime

        mock_chime_manager.trigger_chime = AsyncMock(side_effect=RuntimeError("network error"))
        result = await protect_trigger_chime("chime-001")
        assert result["success"] is False
