"""Smoke tests for the UniFi Access MCP server scaffold."""


def test_package_importable():
    """Verify the unifi_access_mcp package can be imported."""
    import unifi_access_mcp

    assert unifi_access_mcp.__doc__ is not None


def test_managers_importable():
    """Verify all manager stubs can be imported."""
    from unifi_core.access.managers.connection_manager import AccessConnectionManager
    from unifi_core.access.managers.credential_manager import CredentialManager
    from unifi_core.access.managers.device_manager import DeviceManager
    from unifi_core.access.managers.door_manager import DoorManager
    from unifi_core.access.managers.event_manager import EventManager
    from unifi_core.access.managers.policy_manager import PolicyManager
    from unifi_core.access.managers.system_manager import SystemManager
    from unifi_core.access.managers.visitor_manager import VisitorManager

    # Verify all classes can be instantiated with a mock connection manager
    cm = AccessConnectionManager(host="test", username="test", password="test")
    assert DoorManager(cm) is not None
    assert PolicyManager(cm) is not None
    assert CredentialManager(cm) is not None
    assert VisitorManager(cm) is not None
    assert EventManager(cm) is not None
    assert DeviceManager(cm) is not None
    assert SystemManager(cm) is not None


def test_categories_importable():
    """Verify categories module loads correctly."""
    from unifi_access_mcp.categories import ACCESS_CATEGORY_MAP, TOOL_MODULE_MAP

    assert isinstance(ACCESS_CATEGORY_MAP, dict)
    assert "door" in ACCESS_CATEGORY_MAP
    assert "policy" in ACCESS_CATEGORY_MAP
    assert "schedule" in ACCESS_CATEGORY_MAP
    assert "credential" in ACCESS_CATEGORY_MAP
    assert "visitor" in ACCESS_CATEGORY_MAP
    assert "event" in ACCESS_CATEGORY_MAP
    assert "device" in ACCESS_CATEGORY_MAP
    assert "system" in ACCESS_CATEGORY_MAP
    assert "user" in ACCESS_CATEGORY_MAP
    assert isinstance(TOOL_MODULE_MAP, dict)


def test_tool_index_importable():
    """Verify tool_index module loads correctly."""
    from unifi_access_mcp.tool_index import TOOL_REGISTRY, ToolMetadata, register_tool

    assert isinstance(TOOL_REGISTRY, dict)
    assert ToolMetadata is not None
    assert register_tool is not None


def test_config_helpers_importable():
    """Verify config helpers module loads correctly."""
    from unifi_access_mcp.utils.config_helpers import parse_config_bool

    assert parse_config_bool("true") is True
    assert parse_config_bool("false") is False
    assert parse_config_bool(None, default=True) is True


def test_connection_manager_properties():
    """Verify AccessConnectionManager stores connection params."""
    from unifi_core.access.managers.connection_manager import AccessConnectionManager

    cm = AccessConnectionManager(
        host="192.168.1.1",
        username="admin",
        password="secret",
        port=7443,
        verify_ssl=True,
    )
    assert cm.host == "192.168.1.1"
    assert cm.username == "admin"
    assert cm.port == 7443
    assert cm.verify_ssl is True
    assert cm.is_connected is False


def test_access_category_map_values():
    """Verify category map values match config.yaml permissions keys."""
    from unifi_access_mcp.categories import ACCESS_CATEGORY_MAP

    expected_values = {"doors", "policies", "credentials", "visitors", "events", "devices", "system"}
    assert set(ACCESS_CATEGORY_MAP.values()) == expected_values


def test_event_buffer():
    """Verify EventBuffer works correctly."""
    from unifi_core.access.managers.event_manager import EventBuffer

    buf = EventBuffer(max_size=10, ttl_seconds=300)
    assert len(buf) == 0

    buf.add({"type": "door_open", "door_id": "door-1"})
    buf.add({"type": "access_denied", "door_id": "door-2"})
    assert len(buf) == 2

    # Get all recent
    events = buf.get_recent()
    assert len(events) == 2

    # Filter by type
    events = buf.get_recent(event_type="door_open")
    assert len(events) == 1
    assert events[0]["type"] == "door_open"

    # Filter by door
    events = buf.get_recent(door_id="door-2")
    assert len(events) == 1
    assert events[0]["door_id"] == "door-2"

    # Limit
    events = buf.get_recent(limit=1)
    assert len(events) == 1

    # Clear
    buf.clear()
    assert len(buf) == 0
