"""MCP alternate-address read symmetry, closed schema, confirmation and privacy."""

import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jsonschema import Draft202012Validator

from unifi_core.network.managers.vpn_manager import VpnManager
from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP
from unifi_network_mcp.tools import vpn

TOOL = "unifi_update_vpn_server_alternate_address"
ENABLED = "vpn_client_configuration_remote_ip_override_enabled"
ADDRESS = "vpn_client_configuration_remote_ip_override"
SECRET = "synthetic-private-vpn-value"


def test_real_mcp_schema_is_closed_and_strict():
    tool = vpn.server._tool_manager.get_tool(TOOL)
    assert tool.annotations.read_only_hint is False
    assert tool.annotations.idempotent_hint is True
    assert tool.annotations.destructive_hint is False
    schema = tool.parameters
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for fields in [{}, {"unknown": True}, {"alternate_address": None}, {"alternate_address_enabled": "false"}]:
        assert list(validator.iter_errors({"server_id": "srv", "update_data": fields}))
    assert not list(validator.iter_errors({"server_id": "srv", "update_data": {"alternate_address_enabled": False}}))


@pytest.mark.parametrize("mode", ["lazy", "eager", "meta_only"])
def test_production_registry_keeps_schema_and_local_auth_in_fresh_process(mode):
    program = (
        "import json; import unifi_network_mcp.main; import unifi_network_mcp.tools.vpn; "
        "from unifi_network_mcp.runtime import get_tool_registry; "
        f"t=get_tool_registry()['{TOOL}']; "
        "print(json.dumps({'schema':t.input_schema,'auth':t.auth_method}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "UNIFI_TOOL_REGISTRATION_MODE": mode},
    )
    metadata = json.loads(result.stdout)
    assert metadata["auth"] == "local_only"
    fields = metadata["schema"]["properties"]["update_data"]
    assert fields["additionalProperties"] is False
    assert fields["properties"]["alternate_address_enabled"]["type"] == "boolean"
    assert fields["properties"]["alternate_address"]["type"] == "string"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "record, expected",
    [
        ({"_id": "srv", "name": "Unchanged"}, {"alternate_address_enabled": None, "alternate_address": None}),
        (
            {"_id": "srv", ENABLED: False, ADDRESS: "vpn.example"},
            {"alternate_address_enabled": False, "alternate_address": "vpn.example"},
        ),
    ],
)
async def test_read_aliases_preserve_existing_fields_and_absence(record, expected):
    with patch.object(vpn, "vpn_manager") as manager:
        manager.get_vpn_servers = AsyncMock(return_value=[record])
        manager.get_vpn_server_details = AsyncMock(return_value=record)
        manager._connection.site = "default"
        listed = await vpn.list_vpn_servers()
        detail = await vpn.get_vpn_server_details("srv")
    assert listed["vpn_servers"] == [{**record, **expected}]
    assert detail["details"] == {**record, **expected}
    assert "alternate_address" not in record


@pytest.mark.asyncio
async def test_real_manager_preview_and_confirm_are_fresh_safe_and_verified(caplog):
    before = {"_id": "srv", "vpn_type": "wireguard-server", ENABLED: False, ADDRESS: "vpn.example", "opaque": SECRET}
    after = {**before, ENABLED: True}
    conn = MagicMock()
    conn.site = "default"
    conn.ensure_session_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(side_effect=[[before], [before], {}, [after]])
    with patch.object(vpn, "vpn_manager", VpnManager(conn)):
        preview = await vpn.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True})
        assert preview["requires_confirmation"] is True
        assert preview["preview"]["current"]["alternate_address_enabled"] is False
        assert preview["preview"]["proposed"]["alternate_address_enabled"] is True
        assert conn.request.await_count == 1
        result = await vpn.update_vpn_server_alternate_address("srv", {"alternate_address_enabled": True}, True)
    assert result["success"] is True
    assert result["details"]["alternate_address_enabled"] is True
    assert SECRET not in repr(preview) + repr(result) + caplog.text
    assert [call.args[0].method for call in conn.request.call_args_list] == ["get", "get", "put", "get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
@pytest.mark.parametrize("confirm", [False, True])
async def test_errors_never_echo_exception_or_values(caplog, error_type, confirm):
    with patch.object(vpn, "vpn_manager") as manager:
        manager.prepare_vpn_server_alternate_address = AsyncMock(side_effect=error_type(SECRET))
        manager.update_vpn_server_alternate_address = AsyncMock(side_effect=error_type(SECRET))
        result = await vpn.update_vpn_server_alternate_address("srv", {"opaque": SECRET}, confirm=confirm)
    assert result["success"] is False
    assert SECRET not in repr(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_update_policy_gate_denies_before_manager(monkeypatch, confirm):
    monkeypatch.setenv("UNIFI_POLICY_NETWORK_VPN_SERVERS_UPDATE", "false")
    decorator = create_permissioned_tool(
        original_tool_decorator=lambda **kwargs: lambda fn: fn,
        policy_gate_checker=PolicyGateChecker("network", NETWORK_CATEGORY_MAP),
        server_prefix="NETWORK",
        register_tool_fn=MagicMock(),
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda fn, name: fn,
        logger=vpn.logger,
    )
    gated = decorator(name=TOOL, permission_category="vpn_servers", permission_action="update")(
        vpn.update_vpn_server_alternate_address
    )
    with patch.object(vpn, "vpn_manager") as manager:
        result = await gated("srv", {"alternate_address_enabled": False}, confirm=confirm)
        assert result["success"] is False
        assert "disabled" in result["error"].lower()
        manager.prepare_vpn_server_alternate_address.assert_not_called()
        manager.update_vpn_server_alternate_address.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize(
    "case, expected",
    [
        ("empty", "Supply at least one alternate-address field"),
        ("target", "require a WireGuard VPN server"),
        ("missing", "target was not found or is ambiguous"),
        ("session", "requires Network session authentication"),
        ("address", "Enabling the alternate address requires a valid alternate_address (supplied or already stored)."),
    ],
)
async def test_known_preflight_errors_are_actionable_without_writes(case, expected, confirm):
    record = {"_id": "srv", "vpn_type": "wireguard-server", ADDRESS: "vpn.example", "opaque": SECRET}
    if case == "target":
        record["vpn_type"] = "wireguard-client"
    if case == "address":
        record.pop(ADDRESS)
    conn = MagicMock()
    conn.site = "default"
    conn.ensure_session_connected = AsyncMock(return_value=case != "session")
    conn.request = AsyncMock(return_value=[] if case == "missing" else [record])
    with patch.object(vpn, "vpn_manager", VpnManager(conn)):
        result = await vpn.update_vpn_server_alternate_address(
            "srv", {} if case == "empty" else {"alternate_address_enabled": True}, confirm=confirm
        )
    assert result["success"] is False
    assert expected in result["error"]
    if confirm:
        assert result["mutation_applied"] is False
    assert SECRET not in repr(result)
    assert all(call.args[0].method == "get" for call in conn.request.call_args_list)
