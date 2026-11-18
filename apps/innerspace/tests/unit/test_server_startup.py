"""The registered tool set per registration mode: nine read tools, the meta-tools, nothing else."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from mcp.types import CallToolRequestParams

from tests.unit.harness import fresh_registrations, run_main  # noqa: F401
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
from unifi_innerspace_mcp import main
from unifi_innerspace_mcp.categories import LAZY_DIRECT_TOOLS
from unifi_innerspace_mcp.runtime import server
from unifi_innerspace_mcp.tool_index import tool_index_handler

DOMAIN_TOOLS = {
    "innerspace_get_status",
    "innerspace_get_project",
    "innerspace_list_floor_plans",
    "innerspace_list_walls",
    "innerspace_list_placed_devices",
    "innerspace_list_access_points",
    "innerspace_list_switches",
    "innerspace_list_inventory",
    "innerspace_get_plan_asset",
}
META_TOOLS = {
    "innerspace_tool_index",
    "innerspace_execute",
    "innerspace_batch",
    "innerspace_batch_status",
    "innerspace_batch_cancel",
}


async def start_in_mode(monkeypatch, mode: str) -> dict[str, object]:
    """Run the real registration in ``mode`` and return the tools the server lists while serving."""
    monkeypatch.setattr(main, "UNIFI_TOOL_REGISTRATION_MODE", mode)
    # No host: the connect attempt ends at once without a request.
    cm = InnerSpaceConnectionManager("", "synthetic-admin", "synthetic-password-0123456789")
    listed: dict[str, object] = {}

    async def serving() -> None:
        listed.update({tool.name: tool for tool in await server.list_tools()})

    try:
        await run_main(monkeypatch, cm, serving, real_registration=True)
    finally:
        await cm.close()
    return listed


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("lazy", META_TOOLS | {"innerspace_load_tools"} | DOMAIN_TOOLS),
        ("eager", META_TOOLS | DOMAIN_TOOLS),
        ("meta_only", META_TOOLS),
    ],
)
async def test_server_startup_registers_the_tool_set(monkeypatch, fresh_registrations, mode, expected):  # noqa: F811
    listed = await start_in_mode(monkeypatch, mode)

    assert set(listed) == expected
    assert "innerspace_get_support_bundle" not in listed
    for name in DOMAIN_TOOLS & set(listed):
        tool = listed[name]
        assert tool.annotations.read_only_hint is True, name
        assert tool.annotations.idempotent_hint is True and tool.annotations.open_world_hint is False, name
        assert tool.title, name


async def test_all_nine_tools_are_reachable_in_meta_only_mode(monkeypatch, fresh_registrations):  # noqa: F811
    await start_in_mode(monkeypatch, "meta_only")

    index = await tool_index_handler({})

    assert {tool["name"] for tool in index["tools"] if tool["name"] in DOMAIN_TOOLS} == DOMAIN_TOOLS


async def test_lazy_mode_lists_only_read_only_tools_directly(monkeypatch, fresh_registrations):  # noqa: F811
    listed = await start_in_mode(monkeypatch, "lazy")

    assert set(LAZY_DIRECT_TOOLS) == DOMAIN_TOOLS
    for name in LAZY_DIRECT_TOOLS:
        assert listed[name].annotations.read_only_hint is True, name


def _plan_image_templates() -> list[str]:
    return [uri for uri in server._resource_manager._templates if uri.startswith("innerspace://")]


@pytest.mark.parametrize(
    ("mode", "categories", "tools", "registered"),
    [
        ("lazy", None, None, True),
        ("meta_only", None, None, True),
        ("eager", None, None, True),
        ("eager", "floor_plans", None, True),
        ("eager", "status,devices", None, False),
        ("eager", None, "innerspace_get_plan_asset", True),
        ("eager", None, "innerspace_get_status", False),
    ],
)
async def test_plan_image_resource_follows_the_plan_asset_tool(
    monkeypatch,
    fresh_registrations,  # noqa: F811
    mode,
    categories,
    tools,
    registered,
):
    monkeypatch.setattr(server._resource_manager, "_templates", {})
    monkeypatch.setitem(main.config.server, "enabled_categories", categories)
    monkeypatch.setitem(main.config.server, "enabled_tools", tools)

    await start_in_mode(monkeypatch, mode)

    assert _plan_image_templates() == (["innerspace://plans/{plan_id}/image"] if registered else [])


async def test_a_wrong_typed_argument_through_the_mcp_framework(monkeypatch, fresh_registrations, caplog):  # noqa: F811
    """Pins current behaviour: the framework rejects a wrong-typed argument before the tool runs.

    Its error, returned to the caller, quotes the value the caller sent; the log
    names only the field. The tools' own validation (a value of the right type
    outside its range) answers with fixed text instead.
    """
    marker = "SECRETMARK"
    await start_in_mode(monkeypatch, "eager")
    params = CallToolRequestParams(
        name="innerspace_list_walls",
        arguments={"plan_id": "00000000-0000-4000-8000-000000000003", "limit": marker},
    )

    with caplog.at_level(logging.DEBUG):
        result = await server._handle_call_tool(MagicMock(), params)

    assert result.is_error is True
    assert marker in result.content[0].text
    assert marker not in caplog.text
    assert "rejected arguments: ['limit']" in caplog.text


async def test_unit_and_limit_schemas_advertise_the_accepted_values(monkeypatch, fresh_registrations):  # noqa: F811
    schema = (await start_in_mode(monkeypatch, "eager"))["innerspace_list_walls"].input_schema

    assert schema["properties"]["limit"]["minimum"] == 1
    assert schema["properties"]["limit"]["maximum"] == 2000
    assert {"enum": ["metric", "imperial"], "type": "string"} in schema["properties"]["unit"]["anyOf"]
