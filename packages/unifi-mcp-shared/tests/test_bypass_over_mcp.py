"""Bypass mode over a real MCP dispatch.

FastMCP calls a tool with every parameter, defaults included, so an omitted
``confirm`` reaches the permissioned wrapper as ``confirm=False``. These tests
go through ``StrictKwargFastMCP.call_tool`` rather than calling the wrapped
function directly, which is the path the original unit tests missed.
"""

import inspect
import logging
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import ToolAnnotations
from unifi_mcp_shared.call_arguments import caller_supplied, recording_supplied_arguments, supplied_arguments
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP
from unifi_mcp_shared.tool_gate import make_call_classifier


def _server_with_mutating_tool(seen: list[bool]) -> StrictKwargFastMCP:
    server = StrictKwargFastMCP("bypass-test")
    checker = MagicMock()
    checker.check.return_value = True
    server.tool = create_permissioned_tool(
        original_tool_decorator=server.tool,
        policy_gate_checker=checker,
        server_prefix="network",
        register_tool_fn=lambda **_: None,
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda func, _name: func,
        logger=logging.getLogger("test-bypass"),
    )

    @server.tool(name="mut_tool", description="t", permission_category="cat", permission_action="update")
    async def mut_tool(name: str, confirm: bool = False) -> dict:
        seen.append(confirm)
        return {"success": True}

    @server.tool(name="outer_tool", description="t", annotations=ToolAnnotations(readOnlyHint=True))
    async def outer_tool(confirm: bool = False) -> dict:
        # Dispatch the mutating tool the way unifi_execute does, without confirm.
        await server.call_tool("mut_tool", {"name": "inner"})
        return {"success": True, "outer_supplied": sorted(supplied_arguments() or ())}

    return server


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "arguments", "expected_confirm"),
    [
        ("bypass", {"name": "x"}, True),
        ("bypass", {"name": "x", "confirm": False}, False),
        ("bypass", {"name": "x", "confirm": True}, True),
        ("confirm", {"name": "x"}, False),
        ("confirm", {"name": "x", "confirm": True}, True),
    ],
)
async def test_bypass_injects_confirm_only_when_the_mcp_caller_omits_it(mode, arguments, expected_confirm):
    seen: list[bool] = []
    server = _server_with_mutating_tool(seen)

    with patch("unifi_mcp_shared.permissioned_tool.resolve_permission_mode", return_value=mode):
        await server.call_tool("mut_tool", dict(arguments))

    assert seen == [expected_confirm]
    assert supplied_arguments() is None


@pytest.mark.asyncio
async def test_nested_dispatch_records_its_own_arguments_and_restores_the_outer_ones():
    seen: list[bool] = []
    server = _server_with_mutating_tool(seen)

    with patch("unifi_mcp_shared.permissioned_tool.resolve_permission_mode", return_value="bypass"):
        result = await server.call_tool("outer_tool", {"confirm": False})

    # The outer call sent confirm=false, but the inner call omitted it.
    assert seen == [True]
    structured = result.structured_content if hasattr(result, "structured_content") else None
    if structured is not None:
        assert structured.get("outer_supplied") == ["confirm"]
    assert supplied_arguments() is None


def test_caller_supplied_falls_back_to_kwargs_outside_an_mcp_dispatch():
    assert supplied_arguments() is None
    assert caller_supplied("confirm", {"confirm": False}) is True
    assert caller_supplied("confirm", {}) is False


def test_caller_supplied_uses_the_recorded_arguments_inside_a_dispatch():
    with recording_supplied_arguments({"name": "x"}):
        assert caller_supplied("confirm", {"name": "x", "confirm": False}) is False
        assert caller_supplied("name", {"name": "x", "confirm": False}) is True
    assert supplied_arguments() is None


async def _with_confirm(name: str, confirm: bool = False): ...


@pytest.mark.parametrize(
    ("sent", "bypass", "expected"),
    [
        ({"name": "x"}, True, "write"),
        ({"name": "x"}, False, "read"),
        ({"name": "x", "confirm": False}, True, "read"),
        ({"name": "x", "confirm": True}, False, "write"),
    ],
)
def test_gate_classifies_an_omitted_confirm_from_what_the_caller_sent(sent, bypass, expected):
    classify = make_call_classifier(
        action="update", parameters=inspect.signature(_with_confirm).parameters, bypass_mode=lambda: bypass
    )
    # FastMCP-filled kwargs: confirm is always present, defaulted to False.
    filled = {"name": "x", "confirm": sent.get("confirm", False)}
    with recording_supplied_arguments(sent):
        assert classify(filled) == expected
