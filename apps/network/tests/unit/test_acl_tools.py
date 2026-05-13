"""Tests for ACL rule tool functions and the shared AclRule model.

Tests tool-layer behavior (create, update, list, preview), model
translation (from_controller, to_controller_create, to_controller_update),
and field symmetry guarantees.
"""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


# Controller-shaped sample (what the manager returns)
SAMPLE_CONTROLLER_RULE = {
    "_id": "rule001",
    "name": "Test Rule",
    "acl_index": 5,
    "action": "ALLOW",
    "enabled": True,
    "mac_acl_network_id": "net001",
    "traffic_source": {
        "type": "CLIENT_MAC",
        "specific_mac_addresses": ["aa:bb:cc:dd:ee:ff"],
        "ips_or_subnets": [],
        "network_ids": [],
        "ports": [],
    },
    "traffic_destination": {
        "type": "CLIENT_MAC",
        "specific_mac_addresses": [],
        "ips_or_subnets": [],
        "network_ids": [],
        "ports": [],
    },
}


# ---------------------------------------------------------------------------
# Model translation tests
# ---------------------------------------------------------------------------


class TestAclRuleModel:
    """Test the shared AclRule model and its translation helpers."""

    def test_from_controller_flattens_correctly(self):
        """from_controller extracts nested MACs into flat fields."""
        from unifi_core.network.models.acl import from_controller

        rule = from_controller(SAMPLE_CONTROLLER_RULE)
        assert rule.id == "rule001"
        assert rule.name == "Test Rule"
        assert rule.network_id == "net001"
        assert rule.source_macs == ["aa:bb:cc:dd:ee:ff"]
        assert rule.destination_macs == []
        assert rule.source_type == "CLIENT_MAC"
        assert rule.action == "ALLOW"

    def test_to_controller_create_nests_correctly(self):
        """to_controller_create builds the nested traffic_source/destination."""
        from unifi_core.network.models.acl import AclRule, to_controller_create

        rule = AclRule(
            name="New Rule",
            acl_index=10,
            action="BLOCK",
            network_id="net002",
            source_macs=["11:22:33:44:55:66"],
            destination_macs=["aa:bb:cc:dd:ee:ff"],
        )
        payload = to_controller_create(rule)

        assert payload["name"] == "New Rule"
        assert payload["mac_acl_network_id"] == "net002"
        assert payload["traffic_source"]["specific_mac_addresses"] == ["11:22:33:44:55:66"]
        assert payload["traffic_destination"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]
        assert payload["type"] == "MAC"

    def test_round_trip_preserves_data(self):
        """from_controller → to_controller_create preserves all mutable fields."""
        from unifi_core.network.models.acl import from_controller, to_controller_create

        rule = from_controller(SAMPLE_CONTROLLER_RULE)
        payload = to_controller_create(rule)

        assert payload["name"] == SAMPLE_CONTROLLER_RULE["name"]
        assert payload["acl_index"] == SAMPLE_CONTROLLER_RULE["acl_index"]
        assert payload["action"] == SAMPLE_CONTROLLER_RULE["action"]
        assert payload["mac_acl_network_id"] == SAMPLE_CONTROLLER_RULE["mac_acl_network_id"]
        assert (
            payload["traffic_source"]["specific_mac_addresses"]
            == SAMPLE_CONTROLLER_RULE["traffic_source"]["specific_mac_addresses"]
        )

    def test_to_controller_update_partial(self):
        """to_controller_update only includes provided fields."""
        from unifi_core.network.models.acl import to_controller_update

        result = to_controller_update({"source_macs": ["11:22:33:44:55:66"], "name": "Renamed"})

        assert result["traffic_source"]["specific_mac_addresses"] == ["11:22:33:44:55:66"]
        assert result["name"] == "Renamed"
        assert "traffic_destination" not in result  # not provided, not included
        assert "acl_index" not in result

    def test_to_controller_update_network_id_maps(self):
        """network_id in model maps to mac_acl_network_id in controller."""
        from unifi_core.network.models.acl import to_controller_update

        result = to_controller_update({"network_id": "net999"})
        assert result["mac_acl_network_id"] == "net999"
        assert "network_id" not in result

    def test_mutable_fields_excludes_read_only(self):
        """MUTABLE_FIELDS does not contain read-only fields."""
        from unifi_core.network.models.acl import MUTABLE_FIELDS, READ_ONLY_FIELDS

        assert "id" not in MUTABLE_FIELDS
        assert "source_type" not in MUTABLE_FIELDS
        assert "destination_type" not in MUTABLE_FIELDS
        assert "source_macs" in MUTABLE_FIELDS
        assert "name" in MUTABLE_FIELDS

        assert "id" in READ_ONLY_FIELDS
        assert "source_macs" not in READ_ONLY_FIELDS


# ---------------------------------------------------------------------------
# Create tool tests
# ---------------------------------------------------------------------------


class TestCreateAclRule:
    """Test create_acl_rule using the shared model."""

    @pytest.mark.asyncio
    async def test_create_with_macs(self):
        """source_macs and destination_macs flow through to controller payload."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.create_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import create_acl_rule

            result = await create_acl_rule(
                name="Test",
                acl_index=5,
                action="ALLOW",
                network_id="net001",
                source_macs=["aa:bb:cc:dd:ee:ff"],
                destination_macs=[],
                confirm=True,
            )

        assert result["success"] is True
        call_args = mock_mgr.create_acl_rule.call_args[0][0]
        assert call_args["traffic_source"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]
        assert call_args["traffic_destination"]["specific_mac_addresses"] == []

    @pytest.mark.asyncio
    async def test_no_macs_defaults_to_any(self):
        """Omitting source_macs and destination_macs defaults to ANY (empty list)."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.create_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import create_acl_rule

            result = await create_acl_rule(
                name="Block All",
                acl_index=99,
                action="BLOCK",
                network_id="net001",
                confirm=True,
            )

        assert result["success"] is True
        call_args = mock_mgr.create_acl_rule.call_args[0][0]
        assert call_args["traffic_source"]["specific_mac_addresses"] == []
        assert call_args["traffic_destination"]["specific_mac_addresses"] == []

    @pytest.mark.asyncio
    async def test_preview_includes_macs(self):
        """Preview mode shows the resolved MAC addresses in the rule data."""
        from unifi_network_mcp.tools.acl import create_acl_rule

        result = await create_acl_rule(
            name="Test Preview",
            acl_index=5,
            action="ALLOW",
            network_id="net001",
            source_macs=["aa:bb:cc:dd:ee:ff"],
            confirm=False,
        )

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        preview_data = result.get("preview", {}).get("will_create", {})
        assert preview_data["traffic_source"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]

    @pytest.mark.asyncio
    async def test_create_returns_model_shape(self):
        """Successful create returns the rule in model shape (flat fields)."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.create_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import create_acl_rule

            result = await create_acl_rule(
                name="Test",
                acl_index=5,
                action="ALLOW",
                network_id="net001",
                source_macs=["aa:bb:cc:dd:ee:ff"],
                confirm=True,
            )

        assert result["success"] is True
        rule = result["rule"]
        # Model shape: flat source_macs, not nested traffic_source
        assert "source_macs" in rule
        assert rule["source_macs"] == ["aa:bb:cc:dd:ee:ff"]
        assert rule["network_id"] == "net001"


# ---------------------------------------------------------------------------
# Update tool tests
# ---------------------------------------------------------------------------


class TestUpdateAclRule:
    """Test update_acl_rule with model field names."""

    @pytest.mark.asyncio
    async def test_source_macs_translated(self):
        """source_macs in rule_data is translated to controller shape."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)
            mock_mgr.update_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import update_acl_rule

            result = await update_acl_rule(
                rule_id="rule001",
                rule_data={"source_macs": ["11:22:33:44:55:66"]},
                confirm=True,
            )

        assert result["success"] is True
        call_args = mock_mgr.update_acl_rule.call_args[0]
        update_data = call_args[1]
        assert update_data["traffic_source"]["specific_mac_addresses"] == ["11:22:33:44:55:66"]

    @pytest.mark.asyncio
    async def test_empty_source_macs_clears(self):
        """source_macs=[] clears the MAC list (not a no-op)."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)
            mock_mgr.update_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import update_acl_rule

            result = await update_acl_rule(
                rule_id="rule001",
                rule_data={"source_macs": []},
                confirm=True,
            )

        assert result["success"] is True
        call_args = mock_mgr.update_acl_rule.call_args[0]
        assert call_args[1]["traffic_source"]["specific_mac_addresses"] == []

    @pytest.mark.asyncio
    async def test_sibling_fields_preserved(self):
        """source_macs alongside name/action — siblings survive translation."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)
            mock_mgr.update_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import update_acl_rule

            result = await update_acl_rule(
                rule_id="rule001",
                rule_data={
                    "source_macs": ["11:22:33:44:55:66"],
                    "name": "Renamed Rule",
                    "action": "BLOCK",
                },
                confirm=True,
            )

        assert result["success"] is True
        call_args = mock_mgr.update_acl_rule.call_args[0]
        update_data = call_args[1]
        assert update_data["traffic_source"]["specific_mac_addresses"] == ["11:22:33:44:55:66"]
        assert update_data["name"] == "Renamed Rule"
        assert update_data["action"] == "BLOCK"

    @pytest.mark.asyncio
    async def test_unknown_field_rejected(self):
        """Fields not in MUTABLE_FIELDS are rejected with a clear error."""
        from unifi_network_mcp.tools.acl import update_acl_rule

        result = await update_acl_rule(
            rule_id="rule001",
            rule_data={"traffic_source": {"type": "CLIENT_MAC", "specific_mac_addresses": []}},
            confirm=True,
        )

        assert result["success"] is False
        assert "Unknown or read-only" in result["error"]
        assert "traffic_source" in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_field_rejected(self):
        """Read-only fields (id, source_type) are rejected."""
        from unifi_network_mcp.tools.acl import update_acl_rule

        result = await update_acl_rule(
            rule_id="rule001",
            rule_data={"id": "new_id"},
            confirm=True,
        )

        assert result["success"] is False
        assert "Unknown or read-only" in result["error"]

    @pytest.mark.asyncio
    async def test_network_id_accepted(self):
        """network_id (model name) is accepted and translated to mac_acl_network_id."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)
            mock_mgr.update_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import update_acl_rule

            result = await update_acl_rule(
                rule_id="rule001",
                rule_data={"network_id": "net999"},
                confirm=True,
            )

        assert result["success"] is True
        call_args = mock_mgr.update_acl_rule.call_args[0]
        assert call_args[1]["mac_acl_network_id"] == "net999"

    @pytest.mark.asyncio
    async def test_invalid_action_enum_rejected(self):
        """action values outside ALLOW/BLOCK are rejected by type validation."""
        from unifi_network_mcp.tools.acl import update_acl_rule

        result = await update_acl_rule(
            rule_id="rule001",
            rule_data={"action": "DROP"},
            confirm=True,
        )

        assert result["success"] is False
        assert "action" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_int_rejected(self):
        """Non-integer acl_index is rejected by type validation."""
        from unifi_network_mcp.tools.acl import update_acl_rule

        result = await update_acl_rule(
            rule_id="rule001",
            rule_data={"acl_index": "five"},
            confirm=True,
        )

        assert result["success"] is False
        assert "acl_index" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_bool_rejected(self):
        """Non-boolean enabled is rejected by type validation."""
        from unifi_network_mcp.tools.acl import update_acl_rule

        result = await update_acl_rule(
            rule_id="rule001",
            rule_data={"enabled": "yes"},
            confirm=True,
        )

        assert result["success"] is False
        assert "enabled" in result["error"]


# ---------------------------------------------------------------------------
# Get details tool tests
# ---------------------------------------------------------------------------


class TestGetAclRuleDetails:
    """Test get_acl_rule_details returns model-shaped output."""

    @pytest.mark.asyncio
    async def test_returns_model_shape(self):
        """Happy path: returns flat model fields, not nested controller shape."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import get_acl_rule_details

            result = await get_acl_rule_details(rule_id="rule001")

        assert result["success"] is True
        assert result["rule_id"] == "rule001"
        details = result["details"]
        assert details["source_macs"] == ["aa:bb:cc:dd:ee:ff"]
        assert details["network_id"] == "net001"
        assert details["id"] == "rule001"
        assert "traffic_source" not in details
        assert "mac_acl_network_id" not in details

    @pytest.mark.asyncio
    async def test_empty_rule_id_rejected(self):
        """Empty rule_id returns a validation error."""
        from unifi_network_mcp.tools.acl import get_acl_rule_details

        result = await get_acl_rule_details(rule_id="")

        assert result["success"] is False
        assert "rule_id" in result["error"]

    @pytest.mark.asyncio
    async def test_not_found_returns_error(self):
        """Manager raises UniFiNotFoundError; tool surfaces the message."""
        from unifi_core.exceptions import UniFiNotFoundError

        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(
                side_effect=UniFiNotFoundError("acl_rule", "missing")
            )

            from unifi_network_mcp.tools.acl import get_acl_rule_details

            result = await get_acl_rule_details(rule_id="missing")

        assert result["success"] is False
        assert "missing" in result["error"]


# ---------------------------------------------------------------------------
# List tool tests
# ---------------------------------------------------------------------------


class TestListAclRules:
    """Test list_acl_rules returns model-shaped output."""

    @pytest.mark.asyncio
    async def test_list_returns_model_shape(self):
        """List output uses model field names (flat), not controller shape (nested)."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rules = AsyncMock(return_value=[SAMPLE_CONTROLLER_RULE])
            mock_mgr._connection.site = "default"

            from unifi_network_mcp.tools.acl import list_acl_rules

            result = await list_acl_rules()

        assert result["success"] is True
        assert result["count"] == 1
        rule = result["rules"][0]
        # Model shape: flat fields
        assert rule["source_macs"] == ["aa:bb:cc:dd:ee:ff"]
        assert rule["destination_macs"] == []
        assert rule["network_id"] == "net001"
        assert rule["id"] == "rule001"
        # No nested controller fields
        assert "traffic_source" not in rule
        assert "mac_acl_network_id" not in rule

    def test_update_path_covers_all_mutable_fields(self):
        """Every mutable field is handled by to_controller_update.

        Prevents a contributor from adding a mutable field to AclRule that
        passes MUTABLE_FIELDS validation but gets silently dropped by
        to_controller_update because it's not in UPDATE_FIELD_MAP or the
        MAC translation branches.
        """
        from unifi_core.network.models.acl import (
            MAC_TRANSLATED_FIELDS,
            MUTABLE_FIELDS,
            UPDATE_FIELD_MAP,
        )

        covered_fields = set(UPDATE_FIELD_MAP.keys()) | MAC_TRANSLATED_FIELDS
        for field in MUTABLE_FIELDS:
            assert field in covered_fields, (
                f"Mutable field '{field}' is not handled by to_controller_update — "
                f"it's not in UPDATE_FIELD_MAP or MAC_TRANSLATED_FIELDS. "
                f"It would pass MUTABLE_FIELDS validation but be silently dropped."
            )

    @pytest.mark.asyncio
    async def test_list_and_create_field_symmetry(self):
        """Every mutable field in list output is accepted by create_acl_rule.

        This is the structural guarantee from #137 — round-tripping works
        by construction because both tools derive from the same model.
        """
        import inspect

        from unifi_core.network.models.acl import MUTABLE_FIELDS

        # Get the create tool's param names
        from unifi_network_mcp.tools.acl import create_acl_rule

        create_params = set(inspect.signature(create_acl_rule).parameters.keys())
        create_params.discard("confirm")  # not a data field

        # Every mutable field should be a create param
        for field in MUTABLE_FIELDS:
            assert field in create_params, (
                f"Mutable field '{field}' in AclRule is not a param on create_acl_rule — field symmetry violation"
            )
