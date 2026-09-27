"""NAT MCP writes expose closed input schemas and delegate confirmation to Core."""

import json
import subprocess
import sys
from unittest.mock import AsyncMock, patch

import pytest
from jsonschema import Draft202012Validator

from unifi_core.network.managers.nat_manager import NatManager
from unifi_core.policy_gate import PolicyGateChecker
from unifi_core.write_verification import failed_write, noop_write
from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP
from unifi_network_mcp.tools import nat


def test_mutation_metadata_and_nested_schema():
    expected = {
        "unifi_create_nat_rule": (False, False),
        "unifi_update_nat_rule": (False, True),
        "unifi_delete_nat_rule": (True, False),
        "unifi_toggle_nat_rule": (False, True),
    }
    for name, (destructive, idempotent) in expected.items():
        tool = nat.server._tool_manager.get_tool(name)
        assert tool is not None
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is destructive
        assert tool.annotations.idempotent_hint is idempotent
        assert tool.annotations.open_world_hint is False
        assert "V2 NAT tool family" in tool.description
    schema = nat.server._tool_manager.get_tool("unifi_create_nat_rule").parameters
    Draft202012Validator.check_schema(schema)
    nested = schema["properties"]["rule_data"]["properties"]["destination_filter"]["anyOf"][0]
    assert nested["additionalProperties"] is False
    assert list(Draft202012Validator(schema).iter_errors({"rule_data": {"destination_filter": {"adress": "x"}}}))


def test_manifest_registry_keeps_nested_schema_in_fresh_process():
    program = (
        "import unifi_network_mcp.main; import unifi_network_mcp.tools.nat; "
        "from unifi_network_mcp.runtime import get_tool_registry; "
        "s=get_tool_registry()['unifi_create_nat_rule'].input_schema; "
        "print(s['properties']['rule_data']['properties']['destination_filter']['anyOf'][0]['additionalProperties'])"
    )
    result = subprocess.run([sys.executable, "-c", program], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


def test_nat_policy_gate_denies_each_write_action(monkeypatch):
    checker = PolicyGateChecker("network", NETWORK_CATEGORY_MAP)
    for action in ("create", "update", "delete"):
        name = f"UNIFI_POLICY_NETWORK_NAT_RULES_{action.upper()}"
        monkeypatch.setenv(name, "false")
        assert checker.check("nat", action) is False
        assert name in checker.denial_message("nat", action)
        monkeypatch.delenv(name)


@pytest.mark.asyncio
async def test_create_preview_defaults_disabled_and_never_writes():
    fields = {
        "type": "DNAT",
        "in_interface": "network-1",
        "ip_address": "192.0.2.53",
        "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
    }
    with patch.object(nat, "nat_manager") as manager:
        preview = await nat.create_nat_rule(fields)
        assert preview["requires_confirmation"] is True
        assert preview["preview"]["will_create"]["enabled"] is False
        manager.create_nat_rule_verified.assert_not_called()
        result = await nat.create_nat_rule({**fields, "destination_filter": {"adress": "private-value"}})
        assert result["success"] is False
        assert "private-value" not in result["error"]
        manager.create_nat_rule_verified.assert_not_called()


@pytest.mark.asyncio
async def test_update_preview_merges_fresh_and_confirm_preserves_failed_result():
    current = {"_id": "nat-1", "description": "before", "enabled": False}
    merged = {**current, "description": "after"}
    with patch.object(nat, "nat_manager") as manager:
        manager.preview_nat_update = AsyncMock(return_value=(current, merged))
        manager.update_nat_rule_verified = AsyncMock(
            return_value=failed_write("Controller rejected NAT update.", operation="update")
        )
        preview = await nat.update_nat_rule("nat-1", {"description": "after"})
        assert preview["preview"]["current"]["id"] == "nat-1"
        assert preview["preview"]["current"]["description"] == "before"
        assert preview["preview"]["proposed"]["description"] == "after"
        manager.update_nat_rule_verified.assert_not_awaited()
        result = await nat.update_nat_rule("nat-1", {"description": "after"}, confirm=True)
        assert result["success"] is False and result["mutation_applied"] is False


@pytest.mark.asyncio
async def test_explicit_toggle_and_delete_preview():
    current = {"_id": "nat-1", "enabled": False}
    with patch.object(nat, "nat_manager") as manager:
        manager.preview_nat_update = AsyncMock(return_value=(current, current))
        manager.toggle_nat_rule_verified = AsyncMock(return_value=noop_write(resource=current))
        assert (await nat.toggle_nat_rule("nat-1", False))["requires_confirmation"] is True
        assert (await nat.toggle_nat_rule("nat-1", "false"))["success"] is False
        assert (await nat.toggle_nat_rule("nat-1", False, confirm=True))["mutation_applied"] is False
        assert (await nat.delete_nat_rule("nat-1"))["requires_confirmation"] is True
        manager.delete_nat_rule_verified.assert_not_called()


class _RecordingConnection:
    site = "default"

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def ensure_connected(self):
        return True

    async def request(self, request):
        self.requests.append(request)
        return self.responses.pop(0)

    def get_cached(self, _key):
        return None

    def _update_cache(self, _key, _value):
        pass

    def _invalidate_cache(self, _prefix):
        pass


@pytest.mark.asyncio
async def test_previews_project_unknown_top_level_fields_but_full_put_preserves_them():
    secret = "synthetic-secret-55"
    stored = {
        "_id": "nat-1",
        "type": "DNAT",
        "description": "before",
        "enabled": False,
        "setting_preference": "manual",
        "is_predefined": False,
        "in_interface": "network-1",
        "ip_address": "192.0.2.53",
        "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
        "x_future_secret": secret,
        "controller_only_scalar": "preserve-me",
    }
    updated = {**stored, "description": "after"}
    connection = _RecordingConnection([[stored], [stored], [stored], [stored], {}, [updated]])
    with (
        patch.object(nat, "nat_manager", NatManager(connection)),
        patch.object(nat, "should_redact_sensitive_fields", return_value=False),
    ):
        update_preview = await nat.update_nat_rule("nat-1", {"description": "after"})
        toggle_preview = await nat.toggle_nat_rule("nat-1", True)
        delete_preview = await nat.delete_nat_rule("nat-1")
        confirmed = await nat.update_nat_rule("nat-1", {"description": "after"}, confirm=True)

    for preview in (update_preview, toggle_preview, delete_preview):
        assert preview["success"] and preview["requires_confirmation"]
        assert secret not in json.dumps(preview)
        assert "x_future_secret" not in json.dumps(preview)
        assert "controller_only_scalar" not in json.dumps(preview)
    assert update_preview["preview"]["current"]["id"] == "nat-1"
    assert update_preview["preview"]["proposed"]["description"] == "after"
    assert toggle_preview["preview"]["proposed"]["enabled"] is True
    assert delete_preview["preview"]["will_delete"]["id"] == "nat-1"
    assert confirmed["success"] is True
    put = [request for request in connection.requests if request.method == "put"]
    assert len(put) == 1
    assert put[0].data["x_future_secret"] == secret
    assert put[0].data["controller_only_scalar"] == "preserve-me"
