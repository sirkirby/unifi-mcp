"""Tests for the shared confirmation/preview utilities."""

from unifi_core.confirmation import (
    create_preview,
    preview_response,
    toggle_preview,
    update_preview,
)


class TestPreviewResponse:
    """Tests for the preview_response helper."""

    def test_returns_success_true(self):
        result = preview_response(
            action="create",
            resource_type="firewall_policy",
            resource_id="new",
            current_state={},
            proposed_changes={"name": "test"},
        )
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["action"] == "create"

    def test_includes_preview_payload(self):
        result = preview_response(
            action="update",
            resource_type="port_forward",
            resource_id="abc123",
            current_state={"enabled": True},
            proposed_changes={"enabled": False},
        )
        assert result["preview"]["current"] == {"enabled": True}
        assert result["preview"]["proposed"] == {"enabled": False}

    def test_includes_resource_name_when_provided(self):
        result = preview_response(
            action="toggle",
            resource_type="port_forward",
            resource_id="abc123",
            current_state={},
            proposed_changes={},
            resource_name="SSH Access",
        )
        assert result["resource_name"] == "SSH Access"

    def test_excludes_resource_name_when_not_provided(self):
        result = preview_response(
            action="toggle",
            resource_type="port_forward",
            resource_id="abc123",
            current_state={},
            proposed_changes={},
        )
        assert "resource_name" not in result

    def test_includes_warnings_when_provided(self):
        result = preview_response(
            action="delete",
            resource_type="network",
            resource_id="net123",
            current_state={},
            proposed_changes={},
            warnings=["This will affect connected clients"],
        )
        assert result["warnings"] == ["This will affect connected clients"]

    def test_excludes_warnings_when_not_provided(self):
        result = preview_response(
            action="delete",
            resource_type="network",
            resource_id="net123",
            current_state={},
            proposed_changes={},
        )
        assert "warnings" not in result

    def test_includes_message(self):
        result = preview_response(
            action="update",
            resource_type="device",
            resource_id="dev1",
            current_state={},
            proposed_changes={},
        )
        assert "confirm=true" in result["message"]


class TestTogglePreview:
    """Tests for toggle_preview helper."""

    def test_toggle_from_enabled(self):
        result = toggle_preview(
            resource_type="port_forward",
            resource_id="pf1",
            resource_name="SSH",
            current_enabled=True,
        )
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"] == {"enabled": False}
        assert "disabled" in result["message"]

    def test_toggle_from_disabled(self):
        result = toggle_preview(
            resource_type="port_forward",
            resource_id="pf2",
            resource_name="HTTP",
            current_enabled=False,
        )
        assert result["preview"]["proposed"] == {"enabled": True}
        assert "enabled" in result["message"]

    def test_includes_additional_info(self):
        result = toggle_preview(
            resource_type="firewall_rule",
            resource_id="fw1",
            resource_name="Block DNS",
            current_enabled=True,
            additional_info={"name": "Block DNS"},
        )
        assert result["preview"]["current"]["name"] == "Block DNS"
        assert result["preview"]["current"]["enabled"] is True


class TestUpdatePreview:
    """Tests for update_preview helper."""

    def test_filters_current_state(self):
        result = update_preview(
            resource_type="device",
            resource_id="dev1",
            resource_name="My AP",
            current_state={"name": "Old Name", "ip": "10.0.0.1", "mac": "aa:bb:cc"},
            updates={"name": "New Name"},
        )
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        # Only shows fields being changed
        assert result["preview"]["current"] == {"name": "Old Name"}
        assert result["preview"]["proposed"] == {"name": "New Name"}

    def test_message_includes_field_names(self):
        result = update_preview(
            resource_type="device",
            resource_id="dev1",
            resource_name="My AP",
            current_state={"tx_power": 16},
            updates={"tx_power": 20},
        )
        assert "tx_power" in result["message"]


class TestCreatePreview:
    """Tests for create_preview helper."""

    def test_basic_create_preview(self):
        result = create_preview(
            resource_type="firewall_rule",
            resource_data={"name": "Block SSH", "action": "deny"},
        )
        assert result["success"] is True
        assert result["requires_confirmation"] is True
        assert result["action"] == "create"
        assert result["preview"]["will_create"] == {"name": "Block SSH", "action": "deny"}

    def test_with_resource_name(self):
        result = create_preview(
            resource_type="network",
            resource_data={"vlan": 100},
            resource_name="Guest VLAN",
        )
        assert result["resource_name"] == "Guest VLAN"
        assert "Guest VLAN" in result["message"]

    def test_with_warnings(self):
        result = create_preview(
            resource_type="network",
            resource_data={},
            warnings=["DHCP range overlaps"],
        )
        assert result["warnings"] == ["DHCP range overlaps"]
