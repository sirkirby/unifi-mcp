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

    def test_update_action_case_insensitive(self):
        """Lowercase action is accepted on update (parity with create) and emitted uppercase."""
        from unifi_core.network.models.acl import to_controller_update, validate_update_fields

        ok, _ = validate_update_fields({"action": "allow"})
        assert ok is True
        assert to_controller_update({"action": "block"})["action"] == "BLOCK"

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


class TestAclNetmask:
    """Netmask handling: the UI's 'Netmask' dropdown number <-> controller bitmask."""

    @pytest.mark.parametrize(
        ("bits", "mask"),
        [
            (0, "00:00:00:00:00:00"),
            (1, "80:00:00:00:00:00"),
            (9, "ff:80:00:00:00:00"),
            (24, "ff:ff:ff:00:00:00"),
            (47, "ff:ff:ff:ff:ff:fe"),
            (48, "ff:ff:ff:ff:ff:ff"),
        ],
    )
    def test_netmask_bitmask_converters_round_trip(self, bits, mask):
        """Both directions agree at byte-aligned and intra-octet widths (off-by-one shows at the latter)."""
        from unifi_core.network.models.acl import mac_mask_to_netmask, netmask_to_mac_mask

        assert netmask_to_mac_mask(bits) == mask
        assert mac_mask_to_netmask(mask) == bits

    @pytest.mark.parametrize(
        ("mask", "netmask"),
        [("ff:ff:ff:00:00:00", 24), ("ff:00:ff:00:00:00", None)],
        ids=["contiguous", "non_contiguous_stays_visible"],
    )
    def test_from_controller_reads_netmask_and_raw_mask(self, mask, netmask):
        """A masked rule surfaces the friendly number (when expressible) and always the raw bitmask."""
        from unifi_core.network.models.acl import from_controller

        raw = {
            "_id": "r1",
            "name": "multicast",
            "acl_index": 1,
            "action": "ALLOW",
            "enabled": True,
            "mac_acl_network_id": "net1",
            "traffic_source": {"specific_mac_addresses": [], "type": "CLIENT_MAC"},
            "traffic_destination": {
                "specific_mac_addresses": ["01:00:5e:00:00:00"],
                "mac_mask": mask,
                "type": "CLIENT_MAC",
            },
        }
        rule = from_controller(raw)
        assert rule.destination_netmask == netmask
        assert rule.destination_mac_mask == mask
        assert rule.source_netmask is None
        assert rule.source_mac_mask is None

    @pytest.mark.parametrize(("side", "other"), [("destination", "source"), ("source", "destination")])
    def test_create_converts_netmask_to_bitmask(self, side, other):
        from unifi_core.network.models.acl import AclRule, to_controller_create

        rule = AclRule(
            name="oui",
            acl_index=1,
            action="ALLOW",
            network_id="net1",
            **{f"{side}_macs": ["01:00:5e:00:00:00"], f"{side}_netmask": 24},
        )
        payload = to_controller_create(rule)
        assert payload[f"traffic_{side}"]["mac_mask"] == "ff:ff:ff:00:00:00"
        # unset side carries no mask key (exact match)
        assert "mac_mask" not in payload[f"traffic_{other}"]

    @pytest.mark.parametrize(
        ("update", "expected"),
        [
            ({"destination_netmask": 16}, {"traffic_destination": ("ff:ff:00:00:00:00", None)}),
            (
                {"source_netmask": 24, "destination_netmask": 16},
                {"traffic_source": ("ff:ff:ff:00:00:00", None), "traffic_destination": ("ff:ff:00:00:00:00", None)},
            ),
            (
                {"source_macs": ["01:00:5e:00:00:00"], "source_netmask": 24},
                {"traffic_source": ("ff:ff:ff:00:00:00", ["01:00:5e:00:00:00"])},
            ),
        ],
        ids=["netmask_only_is_partial", "both_sides_independent", "macs_and_netmask_together"],
    )
    def test_update_netmask_translation(self, update, expected):
        """Netmask translates to a mac_mask per side; MACs are only written when provided (deep-merge keeps the rest)."""
        from unifi_core.network.models.acl import to_controller_update

        result = to_controller_update(update)
        for side, (mask, macs) in expected.items():
            assert result[side]["mac_mask"] == mask
            if macs is None:
                assert "specific_mac_addresses" not in result[side]
            else:
                assert result[side]["specific_mac_addresses"] == macs

    def test_update_netmask_none_is_no_op(self):
        """netmask=None means 'leave unchanged', NOT clear-to-'' (the controller 400s on '')."""
        from unifi_core.network.models.acl import to_controller_update

        # netmask=None alone produces no traffic_destination block at all (pure no-op).
        result = to_controller_update({"destination_netmask": None})
        assert "traffic_destination" not in result
        # netmask=None alongside a MAC change updates the MACs but never touches the mask.
        result = to_controller_update({"destination_macs": ["aa:bb:cc:dd:ee:ff"], "destination_netmask": None})
        assert result["traffic_destination"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]
        assert "mac_mask" not in result["traffic_destination"]
        # MACs alone also emit no mask, so deep-merge keeps the existing one
        result = to_controller_update({"destination_macs": ["aa:bb:cc:dd:ee:ff"]})
        assert "mac_mask" not in result["traffic_destination"]

    def test_non_contiguous_mask_preserved_on_recreate(self):
        """from_controller -> to_controller_create must NOT drop a non-contiguous mask
        (netmask is None for it, so the raw mac_mask fallback carries it)."""
        from unifi_core.network.models.acl import from_controller, to_controller_create

        raw = {
            "_id": "r",
            "name": "weird",
            "acl_index": 1,
            "action": "ALLOW",
            "enabled": True,
            "mac_acl_network_id": "net1",
            "traffic_source": {"specific_mac_addresses": [], "type": "CLIENT_MAC"},
            "traffic_destination": {
                "specific_mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "mac_mask": "ff:00:ff:00:00:00",
                "type": "CLIENT_MAC",
            },
        }
        payload = to_controller_create(from_controller(raw))
        assert payload["traffic_destination"]["mac_mask"] == "ff:00:ff:00:00:00"
        # the rest of the rule survives the round trip too
        assert payload["name"] == raw["name"]
        assert payload["acl_index"] == raw["acl_index"]
        assert payload["action"] == raw["action"]
        assert payload["mac_acl_network_id"] == raw["mac_acl_network_id"]
        assert payload["traffic_destination"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]

    def test_netmask_to_mac_mask_rejects_out_of_range(self):
        """The converter raises rather than silently producing a match-everything/garbage mask."""
        import pytest as _pytest

        from unifi_core.network.models.acl import netmask_to_mac_mask

        with _pytest.raises(ValueError):
            netmask_to_mac_mask(-1)
        with _pytest.raises(ValueError):
            netmask_to_mac_mask(49)

    def test_mac_mask_to_netmask_rejects_malformed(self):
        """Non-string, wrong octet count, and lenient int forms (0x/whitespace) return None, not a bogus number."""
        from unifi_core.network.models.acl import mac_mask_to_netmask

        assert mac_mask_to_netmask("ff:00:ff:00:00:00") is None  # non-contiguous
        assert mac_mask_to_netmask("not-a-mask") is None
        assert mac_mask_to_netmask(["ff", "ff"]) is None  # non-string -> no AttributeError
        assert mac_mask_to_netmask(None) is None
        assert mac_mask_to_netmask("ff:ff:ff") is None  # wrong octet count
        assert mac_mask_to_netmask("0xff:00:00:00:00:00") is None  # 0x-prefixed token
        assert mac_mask_to_netmask(" ff:ff:ff:ff:ff:ff ") is None  # surrounding whitespace
        assert mac_mask_to_netmask("ff:ff:f:00:00:00") is None  # single-digit octet rejected (strict 2-digit)
        assert mac_mask_to_netmask("FF:FF:FF:00:00:00") == 24  # uppercase still accepted
        assert mac_mask_to_netmask("ff:ff:ff:00:00:00") == 24  # the valid form still works

    def test_field_validator_rejects_on_construction(self):
        """The model's own field_validator (the create/from_controller path) rejects out-of-range,
        independently of validate_update_fields (the update path)."""
        import pytest as _pytest
        from pydantic import ValidationError

        from unifi_core.network.models.acl import AclRule

        with _pytest.raises(ValidationError):
            AclRule(name="x", acl_index=1, action="ALLOW", network_id="n", source_netmask=99)

    def test_netmask_zero_round_trips_as_match_any(self):
        """netmask=0 is accepted and means match-any (all bits wildcarded), distinct from omit/None."""
        from unifi_core.network.models.acl import AclRule, mac_mask_to_netmask, to_controller_create

        rule = AclRule(name="z", acl_index=1, action="ALLOW", network_id="n", destination_netmask=0)
        payload = to_controller_create(rule)
        assert payload["traffic_destination"]["mac_mask"] == "00:00:00:00:00:00"
        assert mac_mask_to_netmask("00:00:00:00:00:00") == 0

    def test_update_clear_and_set_macs_same_side(self):
        """Clearing the mask AND changing MACs on the same side in one update: both apply
        (clear wins over any netmask, MACs still written)."""
        from unifi_core.network.models.acl import to_controller_update

        r = to_controller_update({"destination_macs": ["aa:bb:cc:dd:ee:ff"], "clear_destination_netmask": True})
        assert r["traffic_destination"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]
        assert r["traffic_destination"]["mac_mask"] is None  # clear sentinel emitted

    @pytest.mark.asyncio
    async def test_update_tool_clear_netmask(self):
        """The update tool's clear flag reaches the manager as a None mac_mask sentinel."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.update_acl_rule = AsyncMock(return_value={"name": "r"})

            from unifi_network_mcp.tools.acl import update_acl_rule

            result = await update_acl_rule(rule_id="r1", rule_data={}, clear_destination_netmask=True, confirm=True)
        assert result["success"] is True
        rule_id_arg, payload = mock_mgr.update_acl_rule.call_args[0]
        assert payload["traffic_destination"]["mac_mask"] is None

    @pytest.mark.asyncio
    async def test_create_tool_rejects_bad_netmask_gracefully(self):
        """An out-of-range netmask returns a {'success': False} dict, not an unhandled exception."""
        from unifi_network_mcp.tools.acl import create_acl_rule

        result = await create_acl_rule(
            name="bad",
            acl_index=1,
            action="ALLOW",
            network_id="net001",
            destination_netmask=99,
            confirm=True,
        )
        assert result["success"] is False
        assert "netmask" in result["error"].lower()

    def test_netmask_mutable_mask_read_only(self):
        from unifi_core.network.models.acl import MUTABLE_FIELDS, READ_ONLY_FIELDS

        assert {"source_netmask", "destination_netmask"} <= MUTABLE_FIELDS
        assert {"source_mac_mask", "destination_mac_mask"} <= READ_ONLY_FIELDS

    def test_netmask_out_of_range_rejected(self):
        from unifi_core.network.models.acl import validate_update_fields

        ok, _ = validate_update_fields({"destination_netmask": 24})
        assert ok is True
        bad, msg = validate_update_fields({"destination_netmask": 99})
        assert bad is False and "netmask" in msg

    @pytest.mark.asyncio
    async def test_create_tool_passes_netmask(self):
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.create_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import create_acl_rule

            result = await create_acl_rule(
                name="oui",
                acl_index=5,
                action="ALLOW",
                network_id="net001",
                destination_macs=["01:00:5e:00:00:00"],
                destination_netmask=24,
                confirm=True,
            )
        assert result["success"] is True
        payload = mock_mgr.create_acl_rule.call_args[0][0]
        assert payload["traffic_destination"]["mac_mask"] == "ff:ff:ff:00:00:00"
        assert payload["traffic_destination"]["specific_mac_addresses"] == ["01:00:5e:00:00:00"]
        assert payload["name"] == "oui"
        assert payload["mac_acl_network_id"] == "net001"
        assert payload["type"] == "MAC"
        # response is model-shaped (flat fields), not the nested controller shape
        assert result["rule"]["source_macs"] == ["aa:bb:cc:dd:ee:ff"]
        assert result["rule"]["network_id"] == "net001"


# ---------------------------------------------------------------------------
# Create tool tests
# ---------------------------------------------------------------------------


class TestCreateAclRule:
    """Test create_acl_rule using the shared model."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("kwargs", "expected_source"),
        [
            ({"source_macs": ["aa:bb:cc:dd:ee:ff"], "destination_macs": []}, ["aa:bb:cc:dd:ee:ff"]),
            ({}, []),
        ],
        ids=["with_macs", "defaults_to_any"],
    )
    async def test_create_macs_flow_to_payload(self, kwargs, expected_source):
        """source/destination MACs flow through to the controller payload; omitted MACs default to ANY (empty)."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.create_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import create_acl_rule

            result = await create_acl_rule(
                name="Test", acl_index=5, action="ALLOW", network_id="net001", confirm=True, **kwargs
            )

        assert result["success"] is True
        call_args = mock_mgr.create_acl_rule.call_args[0][0]
        assert call_args["traffic_source"]["specific_mac_addresses"] == expected_source
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


# ---------------------------------------------------------------------------
# Update tool tests
# ---------------------------------------------------------------------------


class TestUpdateAclRule:
    """Test update_acl_rule with model field names."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("macs", [["11:22:33:44:55:66"], []], ids=["set", "empty_clears"])
    async def test_source_macs_translated(self, macs):
        """source_macs in rule_data is translated to controller shape; [] clears the list (not a no-op)."""
        with patch("unifi_network_mcp.tools.acl.acl_manager") as mock_mgr:
            mock_mgr.get_acl_rule_by_id = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)
            mock_mgr.update_acl_rule = AsyncMock(return_value=SAMPLE_CONTROLLER_RULE)

            from unifi_network_mcp.tools.acl import update_acl_rule

            result = await update_acl_rule(rule_id="rule001", rule_data={"source_macs": macs}, confirm=True)

        assert result["success"] is True
        update_data = mock_mgr.update_acl_rule.call_args[0][1]
        assert update_data["traffic_source"]["specific_mac_addresses"] == macs

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
        # fields that were not provided are not emitted
        assert "traffic_destination" not in update_data
        assert "acl_index" not in update_data

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
        assert "network_id" not in call_args[1]

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
        assert details["name"] == "Test Rule"
        assert details["action"] == "ALLOW"
        assert details["source_type"] == "CLIENT_MAC"
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
            mock_mgr.get_acl_rule_by_id = AsyncMock(side_effect=UniFiNotFoundError("acl_rule", "missing"))

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

        This is the structural guarantee — round-tripping works
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
