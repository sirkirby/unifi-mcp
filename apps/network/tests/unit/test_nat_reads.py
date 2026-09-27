"""Read-only NAT tool contract and runtime wiring."""

from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError
from unifi_network_mcp.tools import nat

RULE = {
    "_id": "nat-1",
    "type": "DNAT",
    "enabled": False,
    "source_filter": {"filter_type": "NONE", "x_password": "private-value"},
    "destination_filter": {"filter_type": "ADDRESS_AND_PORT", "port": "53"},
}


def test_runtime_nat_manager_factory_reuses_connection(monkeypatch):
    from unifi_network_mcp import runtime

    connection = object()
    monkeypatch.setattr(runtime, "get_connection_manager", lambda: connection)
    runtime.get_nat_manager.cache_clear()
    try:
        first = runtime.get_nat_manager()
        assert first is runtime.get_nat_manager()
        assert first._connection is connection
    finally:
        runtime.get_nat_manager.cache_clear()


def test_nat_reads_register_as_read_only_with_v2_ids():
    from unifi_network_mcp.categories import NETWORK_CATEGORY_MAP, TOOL_MODULE_MAP

    assert NETWORK_CATEGORY_MAP["nat"] == "nat_rules"
    for name in ("unifi_list_nat_rules", "unifi_get_nat_rule"):
        assert TOOL_MODULE_MAP[name] == "unifi_network_mcp.tools.nat"
        tool = nat.server._tool_manager.get_tool(name)
        assert tool is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False
        assert "V2" in tool.description
        assert "Integration API" in tool.description


@pytest.mark.asyncio
async def test_list_projects_nulls_and_redacts_nested_filters():
    with (
        patch.object(nat, "nat_manager") as manager,
        patch.object(nat, "should_redact_sensitive_fields", return_value=True),
    ):
        manager.list_nat_rules = AsyncMock(return_value=[RULE])
        result = await nat.list_nat_rules()

    assert result["success"] is True
    assert result["data"][0]["id"] == "nat-1"
    assert result["data"][0]["enabled"] is False
    assert result["data"][0]["description"] is None
    assert result["data"][0]["source_filter"]["x_password"] == "***REDACTED***"
    manager.list_nat_rules.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_get_success_and_missing_id():
    with (
        patch.object(nat, "nat_manager") as manager,
        patch.object(nat, "should_redact_sensitive_fields", return_value=False),
    ):
        manager.get_nat_rule = AsyncMock(return_value=RULE)
        assert (await nat.get_nat_rule("nat-1"))["data"]["source_filter"]["x_password"] == "private-value"
        assert (await nat.get_nat_rule(" "))["success"] is False
        assert (await nat.get_nat_rule(None))["success"] is False
    manager.get_nat_rule.assert_awaited_once_with("nat-1")


@pytest.mark.asyncio
async def test_not_found_and_controller_failure_do_not_expose_values(caplog):
    secret = "private-value 192.0.2.53"
    with patch.object(nat, "nat_manager") as manager:
        manager.get_nat_rule = AsyncMock(side_effect=UniFiNotFoundError("nat_rule", secret))
        assert (await nat.get_nat_rule("nat-absent"))["error"] == "Failed to get NAT rule: rule not found."
        manager.get_nat_rule = AsyncMock(side_effect=RuntimeError(secret))
        get_result = await nat.get_nat_rule("nat-1")
        manager.list_nat_rules = AsyncMock(side_effect=RuntimeError(secret))
        list_result = await nat.list_nat_rules()

    assert get_result == {"success": False, "error": "Failed to get NAT rule (RuntimeError)."}
    assert list_result == {"success": False, "error": "Failed to list NAT rules (RuntimeError)."}
    assert secret not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_fixed_unavailable_guidance_reaches_read_caller():
    guidance = "NAT rules need Network 9.0+ with a UniFi gateway."
    with patch.object(nat, "nat_manager") as manager:
        manager.list_nat_rules = AsyncMock(side_effect=UniFiOperationError(guidance))
        result = await nat.list_nat_rules()
    assert guidance in result["error"]
