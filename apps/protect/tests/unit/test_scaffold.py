"""Smoke tests for the UniFi Protect MCP server scaffold."""

import pytest


def test_package_importable():
    """Verify the unifi_protect_mcp package can be imported."""
    import unifi_protect_mcp

    assert unifi_protect_mcp.__doc__ is not None


def test_managers_importable():
    """Verify all manager stubs can be imported."""
    from unifi_core.protect.managers.camera_manager import CameraManager
    from unifi_core.protect.managers.chime_manager import ChimeManager
    from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
    from unifi_core.protect.managers.event_manager import EventManager
    from unifi_core.protect.managers.light_manager import LightManager
    from unifi_core.protect.managers.liveview_manager import LiveviewManager
    from unifi_core.protect.managers.recognition_manager import RecognitionManager
    from unifi_core.protect.managers.recording_manager import RecordingManager
    from unifi_core.protect.managers.sensor_manager import SensorManager
    from unifi_core.protect.managers.system_manager import SystemManager

    # Verify all classes can be instantiated with a mock connection manager
    cm = ProtectConnectionManager(host="test", username="test", password="test")
    assert CameraManager(cm) is not None
    assert ChimeManager(cm) is not None
    assert EventManager(cm) is not None
    assert LightManager(cm) is not None
    assert LiveviewManager(cm) is not None
    assert RecordingManager(cm) is not None
    assert RecognitionManager(cm) is not None
    assert SensorManager(cm) is not None
    assert SystemManager(cm) is not None


@pytest.mark.parametrize("check", ["keys", "values"])
def test_categories(check):
    """Verify categories module loads correctly."""
    from unifi_protect_mcp.categories import PROTECT_CATEGORY_MAP, TOOL_MODULE_MAP

    assert isinstance(PROTECT_CATEGORY_MAP, dict)
    assert isinstance(TOOL_MODULE_MAP, dict)
    if check == "keys":
        assert {
            "camera",
            "event",
            "recording",
            "light",
            "sensor",
            "chime",
            "liveview",
            "recognition",
            "system",
        }.issubset(PROTECT_CATEGORY_MAP)
    else:
        assert set(PROTECT_CATEGORY_MAP.values()) == {
            "cameras",
            "events",
            "recordings",
            "lights",
            "sensors",
            "chimes",
            "liveviews",
            "recognition",
            "system",
            "alarm",
        }


def test_tool_index_importable():
    """Verify tool_index module loads correctly."""
    from unifi_protect_mcp.tool_index import TOOL_REGISTRY, ToolMetadata, register_tool

    assert isinstance(TOOL_REGISTRY, dict)
    assert ToolMetadata is not None
    assert register_tool is not None


def test_config_helpers_importable():
    """Verify config helpers module loads correctly."""
    from unifi_protect_mcp.utils.config_helpers import parse_config_bool

    assert parse_config_bool("true") is True
    assert parse_config_bool("false") is False
    assert parse_config_bool(None, default=True) is True
