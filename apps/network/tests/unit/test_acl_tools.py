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

    def test_netmask_bitmask_converters_round_trip(self):
        from unifi_core.network.models.acl import mac_mask_to_netmask, netmask_to_mac_mask

        assert netmask_to_mac_mask(24) == "ff:ff:ff:00:00:00"
        assert netmask_to_mac_mask(48) == "ff:ff:ff:ff:ff:ff"
        assert netmask_to_mac_mask(0) == "00:00:00:00:00:00"
        assert mac_mask_to_netmask("ff:ff:ff:00:00:00") == 24
        assert mac_mask_to_netmask("ff:ff:ff:ff:ff:ff") == 48
        # non-contiguous and malformed masks have no prefix length
        assert mac_mask_to_netmask("ff:00:ff:00:00:00") is None
        assert mac_mask_to_netmask("not-a-mask") is None

    def test_from_controller_reads_netmask_and_raw_mask(self):
        """A masked rule surfaces both the friendly number and the raw bitmask."""
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
                "mac_mask": "ff:ff:ff:00:00:00",
                "type": "CLIENT_MAC",
            },
        }
        rule = from_controller(raw)
        assert rule.destination_netmask == 24
        assert rule.destination_mac_mask == "ff:ff:ff:00:00:00"
        assert rule.source_netmask is None
        assert rule.source_mac_mask is None

    def test_non_contiguous_mask_stays_visible(self):
        """A mask the number can't express still round-trips via the read-only raw field."""
        from unifi_core.network.models.acl import from_controller

        raw = {
            "_id": "r2",
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
        rule = from_controller(raw)
        assert rule.destination_netmask is None
        assert rule.destination_mac_mask == "ff:00:ff:00:00:00"

    def test_create_converts_netmask_to_bitmask(self):
        from unifi_core.network.models.acl import AclRule, to_controller_create

        rule = AclRule(
            name="oui",
            acl_index=1,
            action="ALLOW",
            network_id="net1",
            destination_macs=["01:00:5e:00:00:00"],
            destination_netmask=24,
        )
        payload = to_controller_create(rule)
        assert payload["traffic_destination"]["mac_mask"] == "ff:ff:ff:00:00:00"
        # unset side carries no mask key (exact match)
        assert "mac_mask" not in payload["traffic_source"]

    def test_update_netmask_only_is_partial(self):
        """Updating just the netmask must not clobber the existing MACs (deep-merge preserves them)."""
        from unifi_core.network.models.acl import to_controller_update

        result = to_controller_update({"destination_netmask": 16})
        assert result["traffic_destination"]["mac_mask"] == "ff:ff:00:00:00:00"
        assert "specific_mac_addresses" not in result["traffic_destination"]

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

    def test_update_source_and_dest_netmask(self):
        """Both sides translate independently; source path is exercised too (not just dest)."""
        from unifi_core.network.models.acl import to_controller_update

        result = to_controller_update({"source_netmask": 24, "destination_netmask": 16})
        assert result["traffic_source"]["mac_mask"] == "ff:ff:ff:00:00:00"
        assert result["traffic_destination"]["mac_mask"] == "ff:ff:00:00:00:00"

    def test_update_macs_and_netmask_together(self):
        """A single update setting both MACs and netmask populates both sub-keys."""
        from unifi_core.network.models.acl import to_controller_update

        result = to_controller_update({"source_macs": ["01:00:5e:00:00:00"], "source_netmask": 24})
        assert result["traffic_source"]["specific_mac_addresses"] == ["01:00:5e:00:00:00"]
        assert result["traffic_source"]["mac_mask"] == "ff:ff:ff:00:00:00"

    def test_create_source_netmask(self):
        """The source-side create path (separate from destination) converts correctly."""
        from unifi_core.network.models.acl import AclRule, to_controller_create

        rule = AclRule(
            name="oui",
            acl_index=1,
            action="ALLOW",
            network_id="net1",
            source_macs=["01:00:5e:00:00:00"],
            source_netmask=24,
        )
        payload = to_controller_create(rule)
        assert payload["traffic_source"]["mac_mask"] == "ff:ff:ff:00:00:00"
        assert "mac_mask" not in payload["traffic_destination"]

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

        assert mac_mask_to_netmask(["ff", "ff"]) is None  # non-string -> no AttributeError
        assert mac_mask_to_netmask(None) is None
        assert mac_mask_to_netmask("ff:ff:ff") is None  # wrong octet count
        assert mac_mask_to_netmask("0xff:00:00:00:00:00") is None  # 0x-prefixed token
        assert mac_mask_to_netmask(" ff:ff:ff:ff:ff:ff ") is None  # surrounding whitespace
        assert mac_mask_to_netmask("ff:ff:f:00:00:00") is None  # single-digit octet rejected (strict 2-digit)
        assert mac_mask_to_netmask("FF:FF:FF:00:00:00") == 24  # uppercase still accepted
        assert mac_mask_to_netmask("ff:ff:ff:00:00:00") == 24  # the valid form still works

    def test_converter_partial_octet_boundaries(self):
        """Off-by-one in the intra-octet shift/mask math would only show at non-byte-aligned widths."""
        from unifi_core.network.models.acl import mac_mask_to_netmask, netmask_to_mac_mask

        for bits, mask in [(1, "80:00:00:00:00:00"), (9, "ff:80:00:00:00:00"), (47, "ff:ff:ff:ff:ff:fe")]:
            assert netmask_to_mac_mask(bits) == mask, bits
            assert mac_mask_to_netmask(mask) == bits, bits

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

    def test_update_macs_only_preserves_existing_mask(self):
        """Updating only MACs emits no mac_mask, so the manager's deep_merge keeps the existing one."""
        from unifi_core.merge import deep_merge
        from unifi_core.network.models.acl import to_controller_update

        existing = {
            "traffic_destination": {
                "mac_mask": "ff:ff:ff:00:00:00",
                "specific_mac_addresses": ["01:00:5e:00:00:00"],
                "type": "CLIENT_MAC",
            }
        }
        partial = to_controller_update({"destination_macs": ["aa:bb:cc:dd:ee:ff"]})
        assert "mac_mask" not in partial["traffic_destination"]
        merged = deep_merge(existing, partial)
        assert merged["traffic_destination"]["mac_mask"] == "ff:ff:ff:00:00:00"  # preserved
        assert merged["traffic_destination"]["specific_mac_addresses"] == ["aa:bb:cc:dd:ee:ff"]  # updated

    def test_clear_netmask_sentinel_and_manager_pop(self):
        """clear_<side>_netmask emits a None sentinel that the manager turns into key removal,
        clearing the mask while preserving the MACs."""
        from unifi_core.merge import deep_merge
        from unifi_core.network.models.acl import to_controller_update

        partial = to_controller_update({"clear_destination_netmask": True})
        assert partial["traffic_destination"]["mac_mask"] is None  # sentinel
        existing = {
            "traffic_destination": {
                "mac_mask": "ff:ff:ff:00:00:00",
                "specific_mac_addresses": ["01:00:5e:00:00:00"],
                "type": "CLIENT_MAC",
            }
        }
        merged = deep_merge(existing, partial)
        # replicate the manager's pop-None-mask step
        for sk in ("traffic_source", "traffic_destination"):
            s = merged.get(sk)
            if isinstance(s, dict) and s.get("mac_mask", "keep") is None:
                s.pop("mac_mask", None)
        assert "mac_mask" not in merged["traffic_destination"]  # cleared
        assert merged["traffic_destination"]["specific_mac_addresses"] == ["01:00:5e:00:00:00"]  # MACs kept

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
