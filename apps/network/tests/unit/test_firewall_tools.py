"""Tests for firewall tool enhancements: zone-based targeting, auto-detection, and delete tool."""

import copy
import json
import logging
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


_ACTION_POLICIES = {
    "pol_allow": {"action": "ALLOW"},
    "pol_block": {"action": "BLOCK"},
    "pol_reject": {"action": "REJECT"},
}

# Truth table of the composed filter: only p_match is ALLOW, enabled and named match-target.
_COMPOSED_POLICIES = {
    "p_match": {"name": "match-target", "enabled": True, "action": "ALLOW"},
    "p_wa": {"name": "match-target", "enabled": True, "action": "BLOCK"},
    "p_dis": {"name": "match-target", "enabled": False, "action": "ALLOW"},
    "p_wn": {"name": "no-match", "enabled": True, "action": "ALLOW"},
}


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
    @pytest.mark.parametrize(
        ("raws", "kwargs", "expected_id"),
        [
            (_ACTION_POLICIES, {"action": "ALLOW"}, "pol_allow"),
            (_ACTION_POLICIES, {"action": "allow"}, "pol_allow"),
            (_ACTION_POLICIES, {"action": "block"}, "pol_block"),
            (
                _COMPOSED_POLICIES,
                {"action": "ALLOW", "enabled_only": True, "search": "match-target"},
                "p_match",
            ),
        ],
        ids=["action_upper", "action_lower", "action_block", "action_enabled_only_search_compose"],
    )
    async def test_filters_match_case_insensitively_and_compose(self, raws, kwargs, expected_id):
        """Action matches V2 uppercase values case-insensitively; action + enabled_only + search
        must all match."""
        policies = [_make_policy({**SAMPLE_ZONE_POLICY_RAW, "_id": pid, **fields}) for pid, fields in raws.items()]
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=policies)
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(include_predefined=False, **kwargs)

        assert result["success"] is True
        assert result["returned_count"] == 1
        assert result["policies"][0]["id"] == expected_id

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kwargs", [{"include_predefined": False}, {}], ids=["no_predefined", "default"])
    async def test_zero_items_case(self, kwargs):
        """Controller returns no policies -> zero counts, policies=[] and the legacy-engine hint."""
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[])
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(**kwargs)

        assert result["total_count"] == 0 and result["returned_count"] == 0
        assert result["count"] == 0
        assert result["policies"] == []
        assert "unifi_list_legacy_firewall_rules" in result["note"]

    @pytest.mark.asyncio
    async def test_summary_false_returns_full_model_dump(self):
        """summary=False returns the legacy fw_from_controller().model_dump() shape —
        ip_version/logging/index present, not narrowed to the curated summary keys
        (protocol is part of the summary as well)."""
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
        assert "logging" not in cp and "ip_version" not in cp
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
# create_firewall_policy — V2 zone-based validation (legacy V1 path removed)
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
    @pytest.mark.parametrize(
        ("overrides", "key", "expected"),
        [
            ({}, "schedule", {"mode": "ALWAYS"}),
            ({"action": "BLOCK"}, "create_allow_respond", False),
            ({"action": "REJECT"}, "create_allow_respond", False),
            ({"ip_version": "IPv4"}, "ip_version", "IPV4"),
        ],
        ids=[
            "required_schedule_default",
            "block_create_allow_respond_false",
            "reject_create_allow_respond_false",
            "mixed_case_ip_version",
        ],
    )
    async def test_create_payload_defaults_and_normalization(self, overrides, key, expected):
        """UniFi requires a schedule on create even when callers omit it, BLOCK/REJECT must send
        create_allow_respond=false, and the strict upper-case ip_version enum is normalized before send."""
        zone_data = {
            "name": "Policy",
            "action": "ALLOW",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
            **overrides,
        }
        captured = {}

        async def capture_create(data):
            captured.update(data)
            mock = MagicMock()
            mock.raw = {**data, "_id": "new_policy"}
            return mock

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(side_effect=capture_create)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is True
        assert captured[key] == expected

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


# ---------------------------------------------------------------------------
# create_firewall_policy — zone targeting validation
# ---------------------------------------------------------------------------


class TestCreateZoneTargetingValidation:
    """Test matching_target_type and port validation for zone-based policies."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("confirm", [False, True])
    @pytest.mark.parametrize("direction", ["source", "destination"])
    @pytest.mark.parametrize(
        "endpoint",
        [
            {"ports": ["445"]},
            {"port_matching_type": "SPECIFIC"},
            {"port_matching_type": "SPECIFIC", "port": 445},
            {"port_matching_type": "SPECIFIC", "port": " "},
        ],
    )
    async def test_invalid_ports_never_reach_manager(self, confirm, direction, endpoint):
        from unifi_network_mcp.tools.firewall import create_firewall_policy

        data = {
            "name": "Invalid port",
            "action": "ALLOW",
            "source": {"zone_id": "source", "matching_target": "ANY"},
            "destination": {"zone_id": "destination", "matching_target": "ANY"},
        }
        data[direction].update(endpoint)
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as manager:
            manager.create_firewall_policy = AsyncMock()
            result = await create_firewall_policy(policy_data=data, confirm=confirm)
        assert result["success"] is False
        assert direction + ".port" in result["error"]
        manager.create_firewall_policy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ports_array_is_rejected_not_silently_accepted(self):
        """A 'ports' array (the plural, undocumented guess) must be rejected at
        preview/create time instead of being echoed back and only failing on the
        live controller write with MissingFirewallDestinationPort."""
        zone_data = {
            "name": "Bad port shape",
            "action": "ALLOW",
            "protocol": "tcp",
            "source": {
                "zone_id": "untrusted",
                "matching_target": "IP",
                "matching_target_type": "SPECIFIC",
                "ips": ["10.0.28.10"],
                "port_matching_type": "ANY",
            },
            "destination": {
                "zone_id": "internal",
                "matching_target": "IP",
                "matching_target_type": "SPECIFIC",
                "ips": ["10.0.15.10"],
                "port_matching_type": "SPECIFIC",
                "ports": ["445"],
            },
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "ports" in result["error"]
        assert "port" in result["error"]


# ---------------------------------------------------------------------------
# Legacy V1 field migration errors
# ---------------------------------------------------------------------------


class TestCreatePortAndClientTargetingValidation:
    """CLIENT targeting and the port OBJECT mode, plus the rule that a selector only
    travels with the enum that activates it. The SPECIFIC port *shape* is Core's
    validate_policy_port_targeting and is already covered by its own tests."""

    @staticmethod
    def _policy(**destination):
        return {
            "name": "Port matched policy",
            "action": "BLOCK",
            "protocol": "tcp_udp",
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "external", "matching_target": "ANY", **destination},
        }

    @pytest.mark.asyncio
    async def test_preview_rejects_an_inactive_selector_before_the_manager_is_reached(self):
        """confirm=False never touches the manager, so the tool layer must run the same
        selector check the Core create path runs."""
        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_policy = AsyncMock(return_value=None)

            from unifi_network_mcp.tools.firewall import create_firewall_policy

            result = await create_firewall_policy(policy_data=self._policy(port_matching_type="OBJECT"), confirm=False)

        assert result["success"] is False
        assert "port_group_id" in result["error"]
        mock_fm.create_firewall_policy.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("destination", "present", "absent"),
        [
            ({"port_matching_type": "specific", "port": "53,853"}, ("53,853", '"SPECIFIC"'), ('"specific"',)),
            ({"matching_target": "APP", "app_ids": ["app-1"], "port_matching_type": "FUTURE"}, ("APP",), ()),
        ],
        ids=["specific_port_upper_cased", "unknown_enums_pass_through"],
    )
    async def test_preview_echoes_port_and_passes_unknown_enums_through(self, destination, present, absent):
        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=self._policy(**destination), confirm=False)

        assert result["success"] is True
        dumped = json.dumps(result)
        for text in present:
            assert text in dumped
        for text in absent:
            assert text not in dumped

    @pytest.mark.asyncio
    async def test_lowercase_enum_still_fails_validation_on_create(self):
        """Normalization must run before validation, or a lower-case enum would skip the port check."""
        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=self._policy(port_matching_type="specific"), confirm=True)

        assert result["success"] is False
        assert "destination.port" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("source", "destination", "expected"),
        [
            (None, {"matching_target": "IP"}, ("matching_target_type", "SPECIFIC")),
            (None, {"matching_target": "NETWORK"}, ("matching_target_type", "OBJECT")),
            ({"zone_id": "internal", "matching_target": "CLIENT"}, {}, ("source.client_macs",)),
        ],
        ids=["ip_without_type", "network_without_type", "client_without_macs"],
    )
    async def test_zone_and_client_targeting_rules_still_apply(self, source, destination, expected):
        """The IP/NETWORK requirements stay where main put them; adding selector checks
        must not displace them. The full message table is Core's validate_zone_targeting."""
        from unifi_network_mcp.tools.firewall import create_firewall_policy

        policy = self._policy(**destination)
        if source:
            policy["source"] = source
        result = await create_firewall_policy(policy_data=policy, confirm=True)

        assert result["success"] is False
        for text in expected:
            assert text in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("update", "expected"),
        [
            ({"matching_target": "IP"}, "matching_target_type is required"),
            ({"matching_target": "NETWORK", "matching_target_type": "OBJECT"}, "network_ids array is required"),
        ],
    )
    async def test_update_rejects_a_target_with_nothing_to_match(self, update, expected):
        """A BLOCK policy whose source targets IP with no ips matches nothing. The
        completeness rules used to be checked on create only."""
        raw = copy.deepcopy(SAMPLE_ZONE_POLICY_RAW)
        raw["source"] = {"zone_id": "z1", "matching_target": "ANY"}
        mock_policy = _make_policy(raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001", update_data={"source": update}, confirm=True
            )

        assert result["success"] is False
        assert expected in result["error"]
        mock_fm.update_firewall_policy.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_port_without_specific_matching_is_rejected(self):
        """A port sent to a policy whose stored port_matching_type is ANY would be ignored by the controller."""
        raw = copy.deepcopy(SAMPLE_ZONE_POLICY_RAW)
        raw["destination"]["port_matching_type"] = "ANY"
        mock_policy = _make_policy(raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"destination": {"port": "53,853"}},
                confirm=True,
            )

        assert result["success"] is False
        assert "port_matching_type" in result["error"]
        mock_fm.update_firewall_policy.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_rejects_non_dict_endpoint(self):
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(policy_id="pol_zone_001", update_data={"source": "ANY"}, confirm=True)

        assert result["success"] is False
        assert "source" in result["error"]
        mock_fm.update_firewall_policy.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_does_not_reject_preexisting_targeting_gaps(self):
        """A controller-stored CLIENT match with an empty MAC list must still accept a port change."""
        raw = copy.deepcopy(SAMPLE_ZONE_POLICY_RAW)
        raw["destination"] = {
            "zone_id": "z2",
            "matching_target": "CLIENT",
            "client_macs": [],
            "port_matching_type": "ANY",
        }
        mock_policy = _make_policy(raw)
        updated = copy.deepcopy(raw)
        updated["destination"].update({"port_matching_type": "SPECIFIC", "port": "53"})

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[mock_policy], [_make_policy(updated)]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"destination": {"port_matching_type": "SPECIFIC", "port": "53"}},
                confirm=True,
            )

        assert result["success"] is True
        mock_fm.update_firewall_policy.assert_called_once()


class TestUpdatePreviewAndVerification:
    """confirm=False must reach the same verdict as confirm=True, and the post-PUT
    re-read must not read a completed retirement as an unapplied change."""

    @staticmethod
    def _stored(**destination):
        raw = copy.deepcopy(SAMPLE_ZONE_POLICY_RAW)
        raw["destination"] = {"zone_id": "z2", "matching_target": "ANY", **destination}
        return raw

    @pytest.mark.asyncio
    async def test_preview_rejects_a_selector_the_stored_enum_does_not_activate(self):
        mock_policy = _make_policy(self._stored(port_matching_type="ANY"))

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001", update_data={"destination": {"port": "53"}}, confirm=False
            )

        assert result["success"] is False
        assert "port_matching_type" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_shows_the_retirement_the_confirmed_call_will_perform(self):
        mock_policy = _make_policy(self._stored(port_matching_type="SPECIFIC", port="53"))

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"destination": {"port_matching_type": "ANY"}},
                confirm=False,
            )

        assert result["success"] is True
        assert '"port": null' in json.dumps(result)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("echoed", [{}, {"port": ""}, {"port": None}])
    async def test_a_retired_selector_the_controller_answers_as_empty_is_applied(self, echoed):
        """The controller may drop the key or answer with its own empty default; both
        mean retired, and reporting either as 'not applied' fails a write that landed."""
        raw = self._stored(port_matching_type="SPECIFIC", port="53")
        after = copy.deepcopy(raw)
        after["destination"] = {"zone_id": "z2", "matching_target": "ANY", "port_matching_type": "ANY", **echoed}

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[_make_policy(raw)], [_make_policy(after)]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"destination": {"port_matching_type": "ANY"}},
                confirm=True,
            )

        assert result["success"] is True
        sent = mock_fm.update_firewall_policy.call_args[0][1]
        assert sent["destination"] == {"port_matching_type": "ANY", "port": None}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("update_data", "after_destination", "field"),
        [
            ({"destination": {"port_matching_type": "ANY"}}, {"port_matching_type": "ANY"}, "destination"),
            # The controller ignores the logging change and returns the original value.
            ({"logging": True}, {}, "logging"),
        ],
        ids=["selector_kept", "silently_discarded_change"],
    )
    async def test_a_change_the_controller_kept_is_still_reported_as_not_applied(
        self, update_data, after_destination, field
    ):
        raw = self._stored(port_matching_type="SPECIFIC", port="53")
        after = copy.deepcopy(raw)
        after["destination"].update(after_destination)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[_make_policy(raw)], [_make_policy(after)]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(policy_id="pol_zone_001", update_data=update_data, confirm=True)

        assert result["success"] is False
        assert f"did not apply changes to: {field}" in result["error"]

    @pytest.mark.asyncio
    async def test_a_non_dict_reread_is_reported_without_logging_the_update(self, caplog):
        """When the controller answers with a non-dict endpoint the comparison falls to the
        scalar branch, where the whole submitted endpoint used to go to the log."""
        raw = self._stored(matching_target="CLIENT", client_macs=["aa:bb:cc:dd:ee:ff"])
        after = copy.deepcopy(raw)
        after["destination"] = None

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[_make_policy(raw)], [_make_policy(after)]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            with caplog.at_level(logging.DEBUG):
                result = await update_firewall_policy(
                    policy_id="pol_zone_001",
                    update_data={"destination": {"client_macs": ["11:22:33:44:55:66"]}},
                    confirm=True,
                )

        assert result["success"] is False
        assert "11:22:33:44:55:66" not in caplog.text

    @pytest.mark.asyncio
    async def test_a_client_macs_mismatch_is_reported_without_logging_a_mac(self, caplog):
        """AGENTS.md: a Network tool logs operation context, never a MAC address."""
        raw = self._stored(matching_target="CLIENT", client_macs=["aa:bb:cc:dd:ee:ff"])
        after = copy.deepcopy(raw)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(side_effect=[[_make_policy(raw)], [_make_policy(after)]])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            with caplog.at_level(logging.DEBUG):
                result = await update_firewall_policy(
                    policy_id="pol_zone_001",
                    update_data={"destination": {"client_macs": ["11:22:33:44:55:66"]}},
                    confirm=True,
                )

        assert result["success"] is False
        assert "11:22:33:44:55:66" not in caplog.text
        assert "aa:bb:cc:dd:ee:ff" not in caplog.text


class TestLegacyFieldMigration:
    """Test that legacy V1 firewall fields produce a migration error
    instead of being silently forwarded to a V2 endpoint that rejects them."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tool", "payload"),
        [
            ("create", {"name": "Block Xbox", "ruleset": "LAN_OUT", "action": "drop", "index": 2000}),
            (
                "create",
                {
                    "name": "Block IoT",
                    "action": "drop",
                    "source": {"zone_id": "internal", "matching_target": "ANY"},
                    "destination": {"zone_id": "wan", "matching_target": "ANY"},
                },
            ),
            ("update", {"ruleset": "WAN_OUT"}),
            ("update", {"src_address": "10.0.0.1"}),
        ],
        ids=["create_ruleset", "create_lowercase_action", "update_ruleset", "update_src_address"],
    )
    async def test_legacy_fields_return_migration_error(self, tool, payload):
        """ruleset/src_address and the lowercase accept/drop/reject enum are V1 — must produce a migration error."""
        from unifi_network_mcp.tools.firewall import create_firewall_policy, update_firewall_policy

        if tool == "create":
            result = await create_firewall_policy(policy_data=payload, confirm=True)
        else:
            result = await update_firewall_policy(policy_id="pol_001", update_data=payload, confirm=True)

        assert result["success"] is False
        assert "no longer supported" in result["error"]
        assert "V2 zone-based fields" in result["error"]


# ---------------------------------------------------------------------------
# update_firewall_policy — V2 zone-based fields (legacy V1 path removed)
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
    @pytest.mark.parametrize("confirm", [False, True])
    async def test_v2_update_rejects_index_before_any_manager_call(self, confirm):
        """index is not a write field on the V2 policy endpoint; the controller accepts
        the request and silently leaves the order unchanged. Reject it before the
        current-state read and before any mutation, on preview and on confirm, and
        name the tool that does reorder."""
        from unifi_network_mcp.tools.firewall import update_firewall_policy

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[])
            mock_fm.update_firewall_policy = AsyncMock(return_value=True)

            result = await update_firewall_policy(
                policy_id="pol_zone_001",
                update_data={"index": 2000, "enabled": True},
                confirm=confirm,
            )

        assert result["success"] is False
        assert "index" in result["error"]
        assert "unifi_reorder_firewall_policies" in result["error"]
        mock_fm.get_firewall_policies.assert_not_awaited()
        mock_fm.update_firewall_policy.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_v2_create_rejects_unknown_key(self):
        """V2 create now rejects unknown top-level keys instead of forwarding them."""
        zone_data = {
            "name": "Reject unknown",
            "action": "ALLOW",
            "dst_port_group_id": "abc123",  # silent-drop case
            "source": {"zone_id": "internal", "matching_target": "ANY"},
            "destination": {"zone_id": "internal", "matching_target": "ANY"},
        }

        from unifi_network_mcp.tools.firewall import create_firewall_policy

        result = await create_firewall_policy(policy_data=zone_data, confirm=True)

        assert result["success"] is False
        assert "dst_port_group_id" in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("update_data", "expected"),
        [
            # Unknown keys are filtered out by to_controller_update; with nothing left the update is empty.
            ({"dst_port_group_id": "abc123"}, "empty"),
            ({"action": "INVALID"}, "Invalid action"),
        ],
        ids=["unknown_key_dropped", "invalid_action"],
    )
    async def test_update_rejects_unusable_data(self, update_data, expected):
        from unifi_network_mcp.tools.firewall import update_firewall_policy

        result = await update_firewall_policy(policy_id="pol_zone_001", update_data=update_data, confirm=True)

        assert result["success"] is False
        assert expected in result["error"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("update_data", "expected"),
        [
            ({"action": "REJECT", "ip_version": "IPv4"}, {"action": "REJECT", "ip_version": "IPV4"}),
            ({"ip_version": "ipv6"}, {"ip_version": "IPV6"}),
            (
                {"connection_state_type": "custom", "connection_states": ["new", "ESTABLISHED"]},
                {"connection_state_type": "CUSTOM", "connection_states": ["NEW", "ESTABLISHED"]},
            ),
            # Unrecognised values are not rejected at the tool boundary; enum validation is the controller's.
            ({"ip_version": "v4"}, {"ip_version": "V4"}),
            ({"connection_state_type": "INCLUSIVE"}, {"connection_state_type": "INCLUSIVE"}),
            (
                {"connection_state_type": "CUSTOM", "connection_states": ["NEW", "BOGUS"]},
                {"connection_states": ["NEW", "BOGUS"]},
            ),
        ],
        ids=[
            "action_and_mixed_case_ip_version",
            "lowercase_ip_version",
            "connection_state_normalized",
            "unknown_ip_version_passes_through",
            "unknown_connection_state_type_passes_through",
            "unknown_connection_state_passes_through",
        ],
    )
    async def test_update_preview_normalizes_enums(self, update_data, expected):
        """The controller's V2 enums are strict upper-case; sending "IPv4" raw produced a cryptic
        deserialization error. Preview exposes the normalized payload without hitting the manager."""
        mock_policy = _make_policy(SAMPLE_ZONE_POLICY_RAW)

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(return_value=[mock_policy])

            from unifi_network_mcp.tools.firewall import update_firewall_policy

            result = await update_firewall_policy(policy_id="pol_zone_001", update_data=update_data, confirm=False)

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        proposed = result["preview"]["proposed"]
        for key, value in expected.items():
            assert proposed[key] == value


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
# list_firewall_zones — projection + error surfacing
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# list_legacy_firewall_rules — raw rule projection and error surfacing
# ---------------------------------------------------------------------------


class TestListLegacyFirewallRules:
    """Cover the read-only wrapper for legacy firewall rules."""

    @pytest.mark.asyncio
    async def test_projects_rules_through_the_model_with_engine_site_and_count(self):
        """The tool projects through LegacyFirewallRule, matching the zone/group tools."""
        mock_conn = MagicMock()
        mock_conn.site = "default"
        legacy_rules = [
            {
                "_id": "rule-001",
                "name": "Allow established traffic",
                "ruleset": "LAN_IN",
                "rule_index": 2000,
                "action": "accept",
                "enabled": True,
                "state_established": True,
                "src_firewallgroup_ids": ["grp-1"],
                "src_networkconf_id": "net-1",
                "unmapped_controller_field": "dropped by the model",
            },
            {
                "_id": "rule-002",
                "name": "Block guest access",
                "ruleset": "GUEST_IN",
                "rule_index": 2010,
                "action": "drop",
                "enabled": True,
            },
        ]

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_legacy_firewall_rules = AsyncMock(return_value=legacy_rules)
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import (
                list_legacy_firewall_rules,
            )

            result = await list_legacy_firewall_rules()

        assert result["success"] is True
        assert result["engine"] == "legacy"
        assert result["site"] == "default"
        assert result["count"] == 2

        first = result["rules"][0]
        assert first["id"] == "rule-001"
        assert first["ruleset"] == "LAN_IN"
        assert first["rule_index"] == 2000
        assert first["action"] == "accept"
        assert first["state_established"] is True
        assert first["src_firewallgroup_ids"] == ["grp-1"]
        assert first["src_networkconf_id"] == "net-1"
        # The model curates the shape: unknown controller keys do not leak through,
        # and the raw "_id" is normalised to "id".
        assert "unmapped_controller_field" not in first
        assert "_id" not in first

    @pytest.mark.asyncio
    async def test_surfaces_manager_exception_as_structured_error(self):
        """Manager failures are returned as explicit legacy-engine errors."""
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_legacy_firewall_rules = AsyncMock(side_effect=Exception("Controller returned 404"))
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import (
                list_legacy_firewall_rules,
            )

            result = await list_legacy_firewall_rules()

        assert result["success"] is False
        assert result["engine"] == "legacy"
        assert "Controller returned 404" in result["error"]
        assert "rules" not in result
        assert "count" not in result


class TestLegacyEngineHint:
    """An empty V2 result must not read as 'no firewall rules configured'."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("zones", "has_note"),
        [([], True), ([{"_id": "z1", "name": "Internal"}], False)],
        ids=["empty_gets_hint", "populated_no_hint"],
    )
    async def test_zones_hint_only_when_empty(self, zones, has_note):
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_zones = AsyncMock(return_value=zones)
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_zones

            result = await list_firewall_zones()

        assert result["count"] == len(zones)
        if has_note:
            assert "unifi_list_legacy_firewall_rules" in result["note"]
        else:
            assert "note" not in result

    @pytest.mark.asyncio
    async def test_policies_no_hint_when_filter_excludes_everything(self):
        """A filter matching nothing is not the same as the engine having no policies."""
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_policies = AsyncMock(
                return_value=[{"_id": "p1", "name": "Allow LAN", "action": "ALLOW", "enabled": True}]
            )
            mock_fm._connection = mock_conn

            from unifi_network_mcp.tools.firewall import list_firewall_policies

            result = await list_firewall_policies(search="no-such-policy-name")

        # total_count is post-filter, so it is legitimately 0 here. The hint must key
        # off the pre-filter controller result, not this.
        assert result["returned_count"] == 0
        assert "note" not in result


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


class TestFirewallZoneWriteTools:
    """Zone write tools: preview/confirm flow and manager delegation."""

    @pytest.mark.asyncio
    async def test_create_zone_preview(self) -> None:
        from unifi_network_mcp.tools.firewall import create_firewall_zone

        result = await create_firewall_zone(name="  IoT  ", confirm=False)

        assert result["success"] is True
        assert result["preview"]["will_create"]["name"] == "IoT"
        assert result["preview"]["will_create"]["networkIds"] == []

    @pytest.mark.asyncio
    async def test_create_zone_confirm(self) -> None:
        from unifi_network_mcp.tools.firewall import create_firewall_zone

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.create_firewall_zone = AsyncMock(
                return_value={"_id": "z1", "name": "IoT", "network_ids": [], "default_zone": False}
            )
            result = await create_firewall_zone(name="IoT", confirm=True)

        assert result["success"] is True
        assert result["zone"]["id"] == "z1"

    @pytest.mark.asyncio
    async def test_delete_zone_preview(self) -> None:
        from unifi_network_mcp.tools.firewall import delete_firewall_zone

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_zone_by_id = AsyncMock(
                return_value={"_id": "z1", "name": "IoT", "network_ids": ["network-1"]}
            )
            result = await delete_firewall_zone(zone_id="z1", confirm=False)

        assert result["success"] is True
        assert result["resource_id"] == "z1"
        assert result["preview"]["will_delete"]["name"] == "IoT"
        assert "Reassign member networks" in result["warnings"][1]

    @pytest.mark.asyncio
    async def test_delete_zone_confirm(self) -> None:
        from unifi_network_mcp.tools.firewall import delete_firewall_zone

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.delete_firewall_zone = AsyncMock(return_value=True)
            result = await delete_firewall_zone(zone_id="z1", confirm=True)

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_zone_preview(self) -> None:
        from unifi_network_mcp.tools.firewall import update_firewall_zone

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_zone_by_id = AsyncMock(return_value={"_id": "z1", "name": "IoT"})
            result = await update_firewall_zone(zone_id="z1", name="IoT2", confirm=False)

        assert result["success"] is True
        assert result["preview"]["current"]["name"] == "IoT"
        assert result["preview"]["proposed"]["name"] == "IoT2"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("operation", ["update", "delete"])
    async def test_system_zone_preview_is_refused(self, operation: str) -> None:
        from unifi_network_mcp.tools.firewall import delete_firewall_zone, update_firewall_zone

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.get_firewall_zone_by_id = AsyncMock(
                return_value={"_id": "z1", "name": "Internal", "default_zone": True}
            )
            if operation == "update":
                result = await update_firewall_zone(zone_id="z1", name="Renamed", confirm=False)
            else:
                result = await delete_firewall_zone(zone_id="z1", confirm=False)

        assert result == {
            "success": False,
            "error": f"Cannot {operation if operation == 'delete' else 'rename'} system-defined firewall zone 'Internal'.",
        }

    @pytest.mark.asyncio
    async def test_update_zone_confirm_delegates_trimmed_name(self) -> None:
        from unifi_network_mcp.tools.firewall import update_firewall_zone

        with patch("unifi_network_mcp.tools.firewall.firewall_manager") as mock_fm:
            mock_fm.update_firewall_zone = AsyncMock(return_value=True)
            result = await update_firewall_zone(zone_id="z1", name="  Devices  ", confirm=True)

        assert result["success"] is True
        mock_fm.update_firewall_zone.assert_awaited_once_with("z1", "Devices")

    @pytest.mark.asyncio
    async def test_zone_names_reject_whitespace_only(self) -> None:
        from unifi_network_mcp.tools.firewall import create_firewall_zone, update_firewall_zone

        create_result = await create_firewall_zone(name="   ", confirm=False)
        update_result = await update_firewall_zone(zone_id="z1", name="   ", confirm=False)

        assert create_result == {"success": False, "error": "name is required"}
        assert update_result == {"success": False, "error": "name is required"}
