"""Tests for firewall tool enhancements: zone-based targeting, auto-detection, and delete tool."""

import copy
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.redaction import REDACTED

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_LEGACY_POLICY_RAW = {
    "_id": "pol_legacy_001",
    "name": "Block Xbox LAN Out",
    "enabled": True,
    "action": "drop",
    "index": 2010,
    "ruleset": "LAN_OUT",
    "description": "Block Xbox from WAN",
    "predefined": False,
}

SAMPLE_ZONE_POLICY_RAW = {
    "_id": "pol_zone_001",
    "name": "Allow IoT to HomeAssistant",
    "enabled": True,
    "action": "ALLOW",
    "index": 3000,
    "predefined": False,
    "protocol": "all",
    "ip_version": "BOTH",
    "logging": False,
    "connection_state_type": "ALL",
    "source": {
        "zone_id": "internal-zone-id",
        "matching_target": "NETWORK",
        "matching_target_type": "OBJECT",
        "network_ids": ["iot-network-id"],
    },
    "destination": {
        "zone_id": "internal-zone-id",
        "matching_target": "IP",
        "matching_target_type": "SPECIFIC",
        "ips": ["192.168.1.100"],
    },
}


def _make_policy(raw: dict):
    """Create a mock FirewallPolicy with the given raw dict."""
    policy = MagicMock()
    policy.raw = copy.deepcopy(raw)
    policy.id = raw["_id"]
    policy.enabled = raw.get("enabled", True)
    policy.predefined = raw.get("predefined", False)
    return policy


# ---------------------------------------------------------------------------
# list_firewall_policies — v2 targeting fields
# ---------------------------------------------------------------------------


class TestListFirewallPolicies:
    """Test that list_firewall_policies includes zone-based targeting fields."""

    @pytest.mark.asyncio
    async def test_legacy_policy_includes_ruleset(self):
        """Legacy policies are shaped via the model — unknown fields like ruleset are dropped.

        The model-based from_controller does not include unknown controller fields;
        callers needing raw ruleset should use get_firewall_policy_details.
        """
        mock_policy = _make_policy(SAMPLE_LEGACY_POLICY_RAW)
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(include_predefined=False)

        assert result["success"] is True
        assert result["total_count"] == 1
        assert result["returned_count"] == 1
        # back-compat: legacy `count` key preserved alongside returned_count
        assert result["count"] == result["returned_count"]
        policy = result["policies"][0]
        # Model-based shaping: id, name, action, enabled surface correctly
        assert policy["id"] == "pol_legacy_001"
        assert policy["name"] == "Block Xbox LAN Out"
        assert policy["action"] == "drop"
        # ruleset is not a model field and is not surfaced
        assert "ruleset" not in policy

    @pytest.mark.asyncio
    async def test_zone_policy_includes_targeting(self):
        """Zone-based policies should include source/destination targeting details."""
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(include_predefined=False)

        assert result["success"] is True
        policy = result["policies"][0]
        # Should NOT have ruleset (zone-based policy)
        assert "ruleset" not in policy
        # Should have source/destination targeting
        assert policy["source"]["zone_id"] == "internal-zone-id"
        assert policy["source"]["matching_target"] == "NETWORK"
        assert policy["source"]["matching_target_type"] == "OBJECT"
        assert policy["source"]["network_ids"] == ["iot-network-id"]
        assert policy["destination"]["matching_target"] == "IP"
        assert policy["destination"]["ips"] == ["192.168.1.100"]

    @pytest.mark.asyncio
    async def test_action_filter_uppercase_v2(self):
        """Action filter must match V2 uppercase values (ALLOW/BLOCK/REJECT) case-insensitively."""
        allow_policy_raw = {**SAMPLE_ZONE_POLICY_RAW, "_id": "pol_allow", "action": "ALLOW"}
        block_policy_raw = {**SAMPLE_ZONE_POLICY_RAW, "_id": "pol_block", "action": "BLOCK"}
        reject_policy_raw = {**SAMPLE_ZONE_POLICY_RAW, "_id": "pol_reject", "action": "REJECT"}
        policies = [_make_policy(p) for p in (allow_policy_raw, block_policy_raw, reject_policy_raw)]

        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=policies)
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            uppercase_result = await list_firewall_policies(action="ALLOW", include_predefined=False)
            lowercase_result = await list_firewall_policies(action="allow", include_predefined=False)
            block_result = await list_firewall_policies(action="block", include_predefined=False)

        assert uppercase_result["success"] is True
        assert uppercase_result["returned_count"] == 1
        assert uppercase_result["policies"][0]["id"] == "pol_allow"

        assert lowercase_result["returned_count"] == 1
        assert lowercase_result["policies"][0]["id"] == "pol_allow"

        assert block_result["returned_count"] == 1
        assert block_result["policies"][0]["id"] == "pol_block"

    @pytest.mark.asyncio
    async def test_filter_composition_action_enabled_only_search(self):
        """action + enabled_only + search compose correctly (all three must match)."""
        # 4 policies covering the truth table of the composed filter.
        p_match = {
            **SAMPLE_ZONE_POLICY_RAW,
            "_id": "p_match",
            "name": "match-target",
            "enabled": True,
            "action": "ALLOW",
        }
        p_wrong_action = {
            **SAMPLE_ZONE_POLICY_RAW,
            "_id": "p_wa",
            "name": "match-target",
            "enabled": True,
            "action": "BLOCK",
        }
        p_disabled = {
            **SAMPLE_ZONE_POLICY_RAW,
            "_id": "p_dis",
            "name": "match-target",
            "enabled": False,
            "action": "ALLOW",
        }
        p_wrong_name = {**SAMPLE_ZONE_POLICY_RAW, "_id": "p_wn", "name": "no-match", "enabled": True, "action": "ALLOW"}
        policies = [_make_policy(p) for p in (p_match, p_wrong_action, p_disabled, p_wrong_name)]

        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=policies)
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(
                action="ALLOW", enabled_only=True, search="match-target", include_predefined=False
            )

        assert result["returned_count"] == 1
        assert result["policies"][0]["id"] == "p_match"

    @pytest.mark.asyncio
    async def test_zero_items_case(self):
        """Controller returns no policies -> total_count=0, returned_count=0, policies=[]."""
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[])
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(include_predefined=False)

        assert result["total_count"] == 0 and result["returned_count"] == 0
        assert result["count"] == 0
        assert result["policies"] == []

    @pytest.mark.asyncio
    async def test_summary_false_returns_full_model_dump(self):
        """summary=False returns the legacy fw_from_controller().model_dump() shape —
        protocol/ip_version/logging/index present, not narrowed to the curated 6 keys."""
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            curated = await list_firewall_policies(include_predefined=False)  # default summary=True
            raw = await list_firewall_policies(summary=False, include_predefined=False)

        # curated path: narrowed 6-key entry + targeting; protocol/logging absent
        cp = curated["policies"][0]
        assert "protocol" not in cp and "logging" not in cp and "ip_version" not in cp
        # raw path: full model dump fields present
        rp = raw["policies"][0]
        assert rp.get("protocol") == "all"
        assert rp.get("ip_version") == "BOTH"
        assert rp.get("logging") is False


class TestFirewallToolRedaction:
    @pytest.mark.asyncio
    async def test_policy_details_redacts_by_default_and_uses_policy_opt_out(self, monkeypatch):
        policy_raw = {
            **SAMPLE_ZONE_POLICY_RAW,
            "source": {**SAMPLE_ZONE_POLICY_RAW["source"], "auth_key": "secret"},
        }
        mock_policy = _make_policy(policy_raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import get_firewall_policy_details

            default = await get_firewall_policy_details("pol_zone_001")
            monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
            raw = await get_firewall_policy_details("pol_zone_001")

        assert default["details"]["source"]["auth_key"] == REDACTED
        assert raw["details"]["source"]["auth_key"] == "secret"

    @pytest.mark.asyncio
    async def test_update_policy_preview_redacts_current_and_proposed_nested_secret(self):
        policy_raw = {
            **SAMPLE_ZONE_POLICY_RAW,
            "source": {**SAMPLE_ZONE_POLICY_RAW["source"], "auth_key": "old-secret"},
        }
        mock_policy = _make_policy(policy_raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                "pol_zone_001",
                {"source": {"zone_id": "internal-zone-id", "matching_target": "ANY", "auth_key": "new-secret"}},
                confirm=False,
            )

        assert result["preview"]["current"]["source"]["auth_key"] == REDACTED
        assert result["preview"]["proposed"]["source"]["auth_key"] == REDACTED


# ---------------------------------------------------------------------------
# create_firewall_policy — V2 zone-based validation (legacy V1 path removed in #210)
# ---------------------------------------------------------------------------


class TestCreateFirewallPolicyV2Validation:
    """Test that create_firewall_policy validates against the V2 zone-based schema."""

    @pytest.mark.asyncio
    async def test_v2_policy_with_source_zone_id(self):
        """Policy with source/destination zone_id is validated by the V2 schema."""
        zone_data = {
            "name": "Allow IoT",
            "action": "ALLOW",
            "source": {
                "zone_id": "internal",
                "matching_target": "ANY",
            },
            "destination": {
                "zone_id": "internal",
                "matching_target": "IP",
                "matching_target_type": "SPECIFIC",
                "ips": ["10.0.0.1"],
            },
        }
        created_raw = {**zone_data, "_id": "new_002"}
        mock_created = MagicMock()
        mock_created.raw = created_raw

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(return_value=mock_created)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert result["policy_id"] == "new_002"

    @pytest.mark.asyncio
    async def test_create_adds_required_schedule_default(self):
        """UniFi requires a schedule object on create even when callers omit it."""
        zone_data = {
            "name": "Allow HA to Hue",
            "action": "ALLOW",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }
        captured = {}

        async def capture_create(data):
            captured.update(data)
            mock = MagicMock()
            mock.raw = {**data, "_id": "new_schedule"}
            return mock

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(side_effect=capture_create)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert captured["schedule"] == {"mode": "ALWAYS"}

    @pytest.mark.asyncio
    async def test_create_adds_block_create_allow_respond_false(self):
        """BLOCK/REJECT creates must send create_allow_respond=false."""
        zone_data = {
            "name": "Block Clients to Management",
            "action": "BLOCK",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }
        captured = {}

        async def capture_create(data):
            captured.update(data)
            mock = MagicMock()
            mock.raw = {**data, "_id": "new_block"}
            return mock

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(side_effect=capture_create)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert captured["create_allow_respond"] is False

    @pytest.mark.asyncio
    async def test_create_adds_reject_create_allow_respond_false(self):
        """REJECT creates must also send create_allow_respond=false."""
        zone_data = {
            "name": "Reject from External",
            "action": "REJECT",
            "source": {"zone_id": "external", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }
        captured = {}

        async def capture_create(data):
            captured.update(data)
            mock = MagicMock()
            mock.raw = {**data, "_id": "new_reject"}
            return mock

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(side_effect=capture_create)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert captured["create_allow_respond"] is False

    @pytest.mark.asyncio
    async def test_create_rejects_block_create_allow_respond_true(self):
        """A BLOCK policy cannot ask UniFi to create an allow-respond rule."""
        zone_data = {
            "name": "Bad Block",
            "action": "BLOCK",
            "create_allow_respond": True,
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "create_allow_respond" in result["error"]

    @pytest.mark.asyncio
    async def test_v2_policy_with_uppercase_action(self):
        """Uppercase ALLOW/BLOCK/REJECT action validates against the V2 schema."""
        zone_data = {
            "name": "Block Zone",
            "action": "BLOCK",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "wan", "matching_target": "ANY"},
        }
        created_raw = {**zone_data, "_id": "new_003"}
        mock_created = MagicMock()
        mock_created.raw = created_raw

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(return_value=mock_created)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_normalizes_mixed_case_ip_version(self):
        """Mixed-case ip_version ('IPv4') must be normalized before reaching the controller.

        Regression test for issue #203: the V2 enum is strict upper-case (BOTH/IPV4/IPV6).
        The wrapper must accept the natural form ('IPv4') and uppercase it before send.
        """
        zone_data = {
            "name": "Allow IoT v4",
            "action": "ALLOW",
            "ip_version": "IPv4",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }
        captured = {}

        async def capture_create(data):
            captured.update(data)
            mock = MagicMock()
            mock.raw = {**data, "_id": "new_v4"}
            return mock

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(side_effect=capture_create)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert captured["ip_version"] == "IPV4", (
            "ip_version must be normalized to upper-case before being sent to the controller"
        )


# ---------------------------------------------------------------------------
# create_firewall_policy — zone targeting validation
# ---------------------------------------------------------------------------


class TestCreateZoneTargetingValidation:
    """Test matching_target_type validation for zone-based policies."""

    @pytest.mark.asyncio
    async def test_missing_matching_target_type_for_ip(self):
        """IP targeting without matching_target_type should fail with helpful error."""
        zone_data = {
            "name": "Bad IP policy",
            "action": "ALLOW",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {
                "zone_id": "internal",
                "matching_target": "IP",
                # missing matching_target_type and ips
            },
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "matching_target_type" in result["error"]
        assert "SPECIFIC" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_matching_target_type_for_network(self):
        """Network targeting without matching_target_type should fail with helpful error."""
        zone_data = {
            "name": "Bad network policy",
            "action": "BLOCK",
            "source": {
                "zone_id": "internal",
                "matching_target": "NETWORK",
                # missing matching_target_type
            },
            "destination": {"zone_id": "wan", "matching_target": "ANY"},
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "matching_target_type" in result["error"]
        assert "OBJECT" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_ips_for_ip_targeting(self):
        """IP targeting with matching_target_type but no ips should fail."""
        zone_data = {
            "name": "No IPs",
            "action": "ALLOW",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {
                "zone_id": "internal",
                "matching_target": "IP",
                "matching_target_type": "SPECIFIC",
                # missing ips
            },
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "ips" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_network_ids_for_network_targeting(self):
        """Network targeting without network_ids should fail."""
        zone_data = {
            "name": "No Network IDs",
            "action": "BLOCK",
            "source": {
                "zone_id": "internal",
                "matching_target": "NETWORK",
                "matching_target_type": "OBJECT",
                # missing network_ids
            },
            "destination": {"zone_id": "wan", "matching_target": "ANY"},
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "network_ids" in result["error"]

    @pytest.mark.asyncio
    async def test_ip_object_targeting_with_ip_group_id_passes_validation(self):
        """IP targeting with matching_target_type=OBJECT and ip_group_id (ips empty) should pass.

        UniFi V2 firewall policies that reference a reusable IP group object use this
        pattern: source/destination has matching_target_type=OBJECT, ip_group_id set,
        and ips=[]. The validator must allow this combination.
        """
        zone_data = {
            "name": "Allow VLAN to internal host",
            "action": "ALLOW",
            "protocol": "all",
            "source": {
                "zone_id": "internal-zone",
                "matching_target": "IP",
                "matching_target_type": "OBJECT",
                "ip_group_id": "group_internal_hosts",
                "ips": [],
            },
            "destination": {
                "zone_id": "trusted-zone",
                "matching_target": "IP",
                "matching_target_type": "SPECIFIC",
                "ips": ["192.168.1.100"],
            },
        }
        created_raw = {**zone_data, "_id": "new_obj_001"}
        mock_created = MagicMock()
        mock_created.raw = created_raw

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(return_value=mock_created)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert result["policy_id"] == "new_obj_001"

    @pytest.mark.asyncio
    async def test_ip_object_targeting_without_ip_group_id_fails(self):
        """IP targeting with matching_target_type=OBJECT but no ip_group_id should fail."""
        zone_data = {
            "name": "Bad object policy",
            "action": "ALLOW",
            "source": {
                "zone_id": "internal",
                "matching_target": "IP",
                "matching_target_type": "OBJECT",
                "ips": [],
                # missing ip_group_id
            },
            "destination": {"zone_id": "wan", "matching_target": "ANY"},
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "ip_group_id" in result["error"]


# ---------------------------------------------------------------------------
# Legacy V1 field migration errors (#210)
# ---------------------------------------------------------------------------


class TestLegacyFieldMigration:
    """Test that legacy V1 firewall fields produce a #210 migration error
    instead of being silently forwarded to a V2 endpoint that rejects them."""

    @pytest.mark.asyncio
    async def test_create_with_ruleset_returns_migration_error(self):
        """ruleset is a legacy V1 field — must produce a migration error."""
        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(
            policy_data={
                "name": "Block Xbox",
                "ruleset": "LAN_OUT",
                "action": "drop",
                "index": 2000,
            },
            confirm=True,
        )

        assert result["success"] is False
        assert "#210" in result["error"]

    @pytest.mark.asyncio
    async def test_create_with_lowercase_action_returns_migration_error(self):
        """Lowercase accept/drop/reject is the V1 enum — must migrate to ALLOW/BLOCK/REJECT."""
        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(
            policy_data={
                "name": "Block IoT",
                "action": "drop",
                "source": {"zone_id": "internal", "matching_target": "ANY"},
                "destination": {"zone_id": "wan", "matching_target": "ANY"},
            },
            confirm=True,
        )

        assert result["success"] is False
        assert "#210" in result["error"]

    @pytest.mark.asyncio
    async def test_update_with_ruleset_returns_migration_error(self):
        """Updating a policy with a legacy ruleset field must surface a migration error."""
        from unifi_network_mcp.tools.firewall import update_firewall_policy

        result = await update_firewall_policy(
            policy_id="pol_001",
            update_data={"ruleset": "WAN_OUT"},
            confirm=True,
        )

        assert result["success"] is False
        assert "#210" in result["error"]

    @pytest.mark.asyncio
    async def test_update_with_src_address_returns_migration_error(self):
        """src_address is a legacy V1 field — must produce a migration error on update."""
        from unifi_network_mcp.tools.firewall import update_firewall_policy

        result = await update_firewall_policy(
            policy_id="pol_001",
            update_data={"src_address": "10.0.0.1"},
            confirm=True,
        )

        assert result["success"] is False
        assert "#210" in result["error"]


# ---------------------------------------------------------------------------
# update_firewall_policy — V2 zone-based fields (legacy V1 path removed in #210)
# ---------------------------------------------------------------------------


class TestUpdateFirewallPolicyV2Fields:
    """Test that update_firewall_policy validates V2 zone-based fields."""

    @pytest.mark.asyncio
    async def test_v2_fields_pass_through(self):
        """Update with source/destination is validated by the V2 schema."""
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)
        updated_raw = copy.deepcopy(SAMPLE_ZONE_POLICY_RAW)
        updated_raw["action"] = "BLOCK"
        updated_raw["source"]["zone_id"] = "wan"
        updated_raw["source"]["matching_target"] = "ANY"
        mock_updated = _make_policy(updated_raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[mock_policy], [mock_updated]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={
                    "action": "BLOCK",
                    "source": {"zone_id": "wan", "matching_target": "ANY"},
                },
                confirm=True,
            )

        assert result["success"] is True
        assert "action" in result["updated_fields"]
        assert "source" in result["updated_fields"]

    @pytest.mark.asyncio
    async def test_action_and_ip_version_normalization(self):
        """Mixed-case action and ip_version should be normalized to controller-accepted form.

        Regression test for issue #203: the controller's V2 firewall enum is strict
        upper-case (BOTH/IPV4/IPV6); accepting "IPv4" wrapper-side then sending it raw
        produced a cryptic deserialization error.
        """
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            # Preview mode lets us inspect the normalized payload without hitting the manager
            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"action": "REJECT", "ip_version": "IPv4"},
                confirm=False,
            )

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        proposed = result["preview"]["proposed"]
        assert proposed["ip_version"] == "IPV4"
        assert proposed["action"] == "REJECT"

    @pytest.mark.asyncio
    async def test_ip_version_lowercase_normalized(self):
        """Lowercase ip_version ('ipv6') should also be accepted and normalized."""
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"ip_version": "ipv6"},
                confirm=False,
            )

        assert result["success"] is True
        assert result["preview"]["proposed"]["ip_version"] == "IPV6"

    @pytest.mark.asyncio
    async def test_invalid_ip_version_not_rejected_at_tool_boundary(self):
        """Model-based update does not reject ip_version values at the tool boundary.

        Enum validation now happens at the controller level. The preview path
        confirms the field passes through to the proposed update.
        """
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"ip_version": "v4"},
                confirm=False,
            )

        # Preview should succeed (not rejected at tool boundary)
        assert result["success"] is True
        assert result["preview"]["proposed"]["ip_version"] == "V4"

    @pytest.mark.asyncio
    async def test_connection_state_normalized(self):
        """Mixed-case connection_state_type and connection_states get normalized.

        Live controller (issue #203 follow-up) accepts only:
          connection_state_type: [ALL, RESPOND_ONLY, CUSTOM]
          connection_states[]:    [NEW, RELATED, INVALID, ESTABLISHED]
        """
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={
                    "connection_state_type": "custom",
                    "connection_states": ["new", "ESTABLISHED"],
                },
                confirm=False,
            )

        assert result["success"] is True
        proposed = result["preview"]["proposed"]
        assert proposed["connection_state_type"] == "CUSTOM"
        assert proposed["connection_states"] == ["NEW", "ESTABLISHED"]

    @pytest.mark.asyncio
    async def test_invalid_connection_state_type_not_rejected_at_tool_boundary(self):
        """Model-based update does not reject connection_state_type at the tool boundary.

        The preview path confirms the field passes through to the proposed update.
        """
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"connection_state_type": "INCLUSIVE"},
                confirm=False,
            )

        assert result["success"] is True
        assert result["preview"]["proposed"]["connection_state_type"] == "INCLUSIVE"

    @pytest.mark.asyncio
    async def test_invalid_connection_state_not_rejected_at_tool_boundary(self):
        """Unrecognised connection_states items pass through to the controller.

        The preview path confirms the list passes through without enum checking.
        """
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={
                    "connection_state_type": "CUSTOM",
                    "connection_states": ["NEW", "BOGUS"],
                },
                confirm=False,
            )

        assert result["success"] is True
        assert result["preview"]["proposed"]["connection_states"] == ["NEW", "BOGUS"]

    @pytest.mark.asyncio
    async def test_v2_update_drops_unknown_key(self):
        """Model-based update silently drops unknown keys (not in MUTABLE_FIELDS).

        Unknown keys like dst_port_group_id are filtered out by to_controller_update.
        If the only key provided is unknown, the update is rejected as empty.
        """
        from unifi_network_mcp.tools.firewall import update_firewall_policy

        result = await update_firewall_policy(
            policy_id="pol_zone_001",
            update_data={"dst_port_group_id": "abc123"},
            confirm=True,
        )

        # dst_port_group_id is not in MUTABLE_FIELDS, so validated_data is empty
        assert result["success"] is False
        assert "empty" in result["error"].lower() or "invalid" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_v2_create_rejects_unknown_key(self):
        """V2 create now rejects unknown top-level keys instead of forwarding them."""
        zone_data = {
            "name": "Reject unknown",
            "action": "ALLOW",
            "dst_port_group_id": "abc123",  # silent-drop case from comment on #136
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "dst_port_group_id" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_action_rejected(self):
        """Invalid action values should be rejected."""
        from unifi_network_mcp.tools.firewall import update_firewall_policy

        result = await update_firewall_policy(
            policy_id="pol_001",
            update_data={"action": "INVALID"},
            confirm=True,
        )

        assert result["success"] is False
        assert "Invalid action" in result["error"]

    @pytest.mark.asyncio
    async def test_update_detects_silently_discarded_change(self):
        """Post-update verification should catch when controller ignores a field."""
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)
        # Simulate controller ignoring the logging change (returns original value)
        unchanged_raw = copy.deepcopy(SAMPLE_ZONE_POLICY_RAW)
        mock_unchanged = _make_policy(unchanged_raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[mock_policy], [mock_unchanged]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"logging": True},
                confirm=True,
            )

        assert result["success"] is False
        assert "logging" in result["error"]
        assert "did not apply" in result["error"]


# ---------------------------------------------------------------------------
# firewall policy ordering
# ---------------------------------------------------------------------------


class TestFirewallPolicyOrderingTools:
    """Tools for the dedicated UniFi policy ordering endpoint."""

    ORDERING = {
        "beforeSystemDefined": ["allow-1", "allow-2"],
        "afterSystemDefined": ["block-1"],
    }

    @pytest.mark.asyncio
    async def test_get_policy_ordering_success(self):
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policy_ordering = AsyncMock(
                return_value={"orderedFirewallPolicyIds": copy.deepcopy(self.ORDERING)}
            )

            from unifi_network_mcp.tools.firewall import get_firewall_policy_ordering

            result = await get_firewall_policy_ordering("zone-src", "zone-dst")

        assert result["success"] is True
        assert result["ordering"] == self.ORDERING
        mock_fm.get_firewall_policy_ordering.assert_called_once_with("zone-src", "zone-dst")

    @pytest.mark.asyncio
    async def test_reorder_rejects_payload_missing_after_key(self):
        """A payload that omits afterSystemDefined entirely must be rejected."""
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            from unifi_network_mcp.tools.firewall import reorder_firewall_policies

            result = await reorder_firewall_policies(
                source_firewall_zone_id="zone-src",
                destination_firewall_zone_id="zone-dst",
                ordered_firewall_policy_ids={"beforeSystemDefined": ["allow-1"]},
                confirm=True,
            )

        assert result["success"] is False
        assert "beforeSystemDefined" in result["error"]
        assert "afterSystemDefined" in result["error"]
        mock_fm.get_firewall_policy_ordering.assert_not_called()
        mock_fm.reorder_firewall_policies.assert_not_called()

    @pytest.mark.asyncio
    async def test_reorder_preview_preserves_current_id_set(self):
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policy_ordering = AsyncMock(
                return_value={"orderedFirewallPolicyIds": copy.deepcopy(self.ORDERING)}
            )

            from unifi_network_mcp.tools.firewall import reorder_firewall_policies

            result = await reorder_firewall_policies(
                source_firewall_zone_id="zone-src",
                destination_firewall_zone_id="zone-dst",
                ordered_firewall_policy_ids={
                    "beforeSystemDefined": ["allow-2", "allow-1"],
                    "afterSystemDefined": ["block-1"],
                },
                confirm=False,
            )

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        assert result["preview"]["current"]["orderedFirewallPolicyIds"] == self.ORDERING
        assert result["preview"]["proposed"]["orderedFirewallPolicyIds"] == {
            "beforeSystemDefined": ["allow-2", "allow-1"],
            "afterSystemDefined": ["block-1"],
        }

    @pytest.mark.asyncio
    async def test_reorder_rejects_missing_policy_id(self):
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policy_ordering = AsyncMock(
                return_value={"orderedFirewallPolicyIds": copy.deepcopy(self.ORDERING)}
            )

            from unifi_network_mcp.tools.firewall import reorder_firewall_policies

            result = await reorder_firewall_policies(
                source_firewall_zone_id="zone-src",
                destination_firewall_zone_id="zone-dst",
                ordered_firewall_policy_ids={
                    "beforeSystemDefined": ["allow-1"],
                    "afterSystemDefined": ["block-1"],
                },
                confirm=True,
            )

        assert result["success"] is False
        assert "Missing: allow-2" in result["error"]
        mock_fm.reorder_firewall_policies.assert_not_called()

    @pytest.mark.asyncio
    async def test_reorder_rejects_duplicate_policy_id(self):
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            from unifi_network_mcp.tools.firewall import reorder_firewall_policies

            result = await reorder_firewall_policies(
                source_firewall_zone_id="zone-src",
                destination_firewall_zone_id="zone-dst",
                ordered_firewall_policy_ids={
                    "beforeSystemDefined": ["allow-1", "allow-1"],
                    "afterSystemDefined": ["block-1"],
                },
                confirm=True,
            )

        assert result["success"] is False
        assert "duplicate policy IDs: allow-1" in result["error"]
        mock_fm.get_firewall_policy_ordering.assert_not_called()
        mock_fm.reorder_firewall_policies.assert_not_called()

    @pytest.mark.asyncio
    async def test_reorder_rejects_non_string_policy_id(self):
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            from unifi_network_mcp.tools.firewall import reorder_firewall_policies

            result = await reorder_firewall_policies(
                source_firewall_zone_id="zone-src",
                destination_firewall_zone_id="zone-dst",
                ordered_firewall_policy_ids={
                    "beforeSystemDefined": ["allow-1", None],
                    "afterSystemDefined": ["block-1"],
                },
                confirm=True,
            )

        assert result["success"] is False
        assert "non-empty policy ID strings" in result["error"]
        mock_fm.get_firewall_policy_ordering.assert_not_called()
        mock_fm.reorder_firewall_policies.assert_not_called()

    @pytest.mark.asyncio
    async def test_reorder_confirm_calls_manager(self):
        requested = {"beforeSystemDefined": ["allow-2", "allow-1"], "afterSystemDefined": ["block-1"]}
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policy_ordering = AsyncMock(
                return_value={"orderedFirewallPolicyIds": copy.deepcopy(self.ORDERING)}
            )
            mock_fm.reorder_firewall_policies = AsyncMock(return_value={"orderedFirewallPolicyIds": requested})

            from unifi_network_mcp.tools.firewall import reorder_firewall_policies

            result = await reorder_firewall_policies(
                source_firewall_zone_id="zone-src",
                destination_firewall_zone_id="zone-dst",
                ordered_firewall_policy_ids=requested,
                confirm=True,
            )

        assert result["success"] is True
        assert result["ordering"] == requested
        mock_fm.reorder_firewall_policies.assert_called_once_with("zone-src", "zone-dst", requested)


# ---------------------------------------------------------------------------
# delete_firewall_policy
# ---------------------------------------------------------------------------


class TestDeleteFirewallPolicy:
    """Test the new delete_firewall_policy tool."""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Confirmed delete should call manager and return success."""
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.delete_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import delete_firewall_policy

            result = await delete_firewall_policy(policy_id="pol_001", confirm=True)

        assert result["success"] is True
        assert "deleted successfully" in result["message"]
        mock_fm.delete_firewall_policy.assert_called_once_with("pol_001")

    @pytest.mark.asyncio
    async def test_delete_preview(self):
        """Unconfirmed delete should return a preview."""
        from unifi_network_mcp.tools.firewall import delete_firewall_policy

        result = await delete_firewall_policy(policy_id="pol_001", confirm=False)

        assert result["success"] is True
        assert result.get("requires_confirmation") is True

    @pytest.mark.asyncio
    async def test_delete_manager_failure(self):
        """Delete should return error when manager returns False."""
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.delete_firewall_policy = AsyncMock(return_value=False)

            from unifi_network_mcp.tools.firewall import delete_firewall_policy

            result = await delete_firewall_policy(policy_id="pol_001", confirm=True)

        assert result["success"] is False
        assert "Failed to delete" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_exception_handled(self):
        """Delete should catch exceptions and return clean error."""
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.delete_firewall_policy = AsyncMock(side_effect=Exception("Connection refused"))

            from unifi_network_mcp.tools.firewall import delete_firewall_policy

            result = await delete_firewall_policy(policy_id="pol_001", confirm=True)

        assert result["success"] is False
        assert "Connection refused" in result["error"]


# ---------------------------------------------------------------------------
# list_firewall_zones — projection + error surfacing (issue #154)
# ---------------------------------------------------------------------------


class TestListFirewallZones:
    """Cover the tool wrapper's projection and error-surfacing behavior."""

    @pytest.mark.asyncio
    async def test_projects_zone_fields_and_includes_site(self):
        """Tool output projects id/name/zone_key and includes the site field."""
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_zones = AsyncMock(
                return_value=[
                    {"_id": "zone-internal", "name": "Internal", "zone_key": "internal"},
                    {"_id": "zone-external", "name": "External", "zone_key": "external"},
                ]
            )
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_zones

            result = await list_firewall_zones()

        assert result["success"] is True
        assert result["site"] == "default"
        assert result["count"] == 2
        # Model-based shaping: _id → id; FirewallZone fields surfaced
        zone0 = result["zones"][0]
        assert zone0["id"] == "zone-internal"
        assert zone0["name"] == "Internal"
        # zone_key is not a model field; not surfaced (unknown controller field)
        assert "zone_key" not in zone0
        zone1 = result["zones"][1]
        assert zone1["id"] == "zone-external"
        assert zone1["name"] == "External"

    @pytest.mark.asyncio
    async def test_surfaces_manager_exception_as_structured_error(self):
        """When the manager raises, the tool returns success=False with the error message — not an empty success."""
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_zones = AsyncMock(side_effect=Exception("Controller returned 404"))
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_zones

            result = await list_firewall_zones()

        assert result["success"] is False
        assert "Controller returned 404" in result["error"]
        # Crucially: no silent empty-list-as-success.
        assert "zones" not in result or result.get("zones") in (None, [])
        assert result.get("count", 0) == 0


@pytest.mark.asyncio
async def test_list_firewall_policies_routes_through_typed_model():
    """Discriminator for the model-routing path: FirewallRule coerces index str->int.

    A raw `p.get("index")` would keep the string "3000"; routing through
    fw_from_controller yields int 3000. This test fails if the tool reverts to
    reading raw dict values directly.
    """
    raw = {"_id": "pol_x", "name": "X", "enabled": True, "action": "ALLOW", "index": "3000"}
    mock_policy = _make_policy(raw)
    mock_conn = MagicMock()
    mock_conn.site = "default"

    with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
        mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
        mock_fm._connection = mock_conn

        from unifi_network_mcp.tools.firewall import list_firewall_policies

        result = await list_firewall_policies(include_predefined=False)

    policy = result["policies"][0]
    assert policy["rule_index"] == 3000
    assert isinstance(policy["rule_index"], int)  # int (model coercion), not "3000" from raw
