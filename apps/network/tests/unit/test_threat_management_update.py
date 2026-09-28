"""Threat update schema, confirmation, policy and safe verified manager integration."""

import json
import os
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jsonschema import Draft202012Validator

from unifi_core.network.managers.system_manager import SystemManager
from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP
from unifi_network_mcp.tools import system

TOOL = "unifi_update_threat_management_settings"
SECRET = "private-threat-canary"


def test_closed_runtime_schema():
    tool = system.server._tool_manager.get_tool(TOOL)
    validator = Draft202012Validator(tool.parameters)
    assert tool.annotations.read_only_hint is False
    for update in [{"unknown": True}, {"ips_mode": None}, {"device_fingerprinting_enabled": "false"}]:
        assert list(validator.iter_errors({"update_data": update}))
    assert not list(validator.iter_errors({"update_data": {"device_fingerprinting_enabled": False}}))


@pytest.mark.parametrize("mode", ["lazy", "eager", "meta_only"])
def test_registry_mode_keeps_auth_and_closed_schema(mode):
    code = (
        "import json; import unifi_network_mcp.main; import unifi_network_mcp.tools.system; "
        "from unifi_network_mcp.runtime import get_tool_registry; "
        f't=get_tool_registry()["{TOOL}"]; '
        'print(json.dumps({"schema":t.input_schema,"auth":t.auth_method}))'
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "UNIFI_TOOL_REGISTRATION_MODE": mode},
    )
    metadata = json.loads(result.stdout)
    assert metadata["auth"] == "local_only"
    assert metadata["schema"]["properties"]["update_data"]["additionalProperties"] is False


@pytest.mark.asyncio
async def test_real_manager_preview_apply_readback_and_privacy():
    before = {"_id": "dpi", "enabled": True, "fingerprintingEnabled": True, "opaque": SECRET}
    after = {**before, "fingerprintingEnabled": False}
    conn = MagicMock()
    conn.site = "default"
    conn.ensure_session_connected = AsyncMock(return_value=True)
    conn.request = AsyncMock(side_effect=[[before], [before], [], [after]])
    with patch.object(system, "system_manager", SystemManager(conn)):
        preview = await system.update_threat_management_settings({"device_fingerprinting_enabled": False})
        assert preview["requires_confirmation"]
        assert preview["preview"]["current"]["device_fingerprinting_enabled"] is True
        assert preview["preview"]["proposed"]["device_fingerprinting_enabled"] is False
        assert conn.request.await_count == 1
        result = await system.update_threat_management_settings({"device_fingerprinting_enabled": False}, True)
    assert result["success"] and result["mutation_applied"] is True
    assert result["persisted_fields"] == ["device_fingerprinting_enabled"]
    assert SECRET not in repr(preview) + repr(result)
    assert [call.args[0].method for call in conn.request.await_args_list] == ["get", "get", "post", "get"]


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
async def test_policy_denies_before_read_or_write(monkeypatch, confirm):
    monkeypatch.setenv("UNIFI_POLICY_NETWORK_SYSTEM_UPDATE", "false")
    decorator = create_permissioned_tool(
        original_tool_decorator=lambda **kwargs: lambda fn: fn,
        policy_gate_checker=PolicyGateChecker("network", NETWORK_CATEGORY_MAP),
        server_prefix="NETWORK",
        register_tool_fn=MagicMock(),
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda fn, name: fn,
        logger=system.logger,
    )
    gated = decorator(name=TOOL, permission_category="system", permission_action="update")(
        system.update_threat_management_settings
    )
    with patch.object(system, "system_manager") as manager:
        result = await gated({"device_fingerprinting_enabled": False}, confirm=confirm)
        assert not result["success"] and "disabled" in result["error"].lower()
        manager.preview_threat_management_settings.assert_not_called()
        manager.update_threat_management_settings.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_untrusted_exception_text_never_exposed(confirm, error_type, caplog):
    with patch.object(system, "system_manager") as manager:
        manager.preview_threat_management_settings = AsyncMock(side_effect=error_type(SECRET))
        manager.update_threat_management_settings = AsyncMock(side_effect=error_type(SECRET))
        result = await system.update_threat_management_settings({"device_fingerprinting_enabled": False}, confirm)
    assert not result["success"]
    assert SECRET not in repr(result) + caplog.text
