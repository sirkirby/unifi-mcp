"""The registered tool set per registration mode: the read and write tools, the meta-tools, nothing else.

Lazy mode lists only the read tools directly; the write tools are reached through innerspace_execute (or
innerspace_load_tools), and in meta_only mode every tool is, writes behind their confirm.
"""

from __future__ import annotations

import inspect
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolRequestParams

from tests.unit.harness import fresh_registrations, run_main  # noqa: F401
from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
from unifi_innerspace_mcp import main, runtime
from unifi_innerspace_mcp.categories import LAZY_DIRECT_TOOLS
from unifi_innerspace_mcp.runtime import server
from unifi_innerspace_mcp.tool_index import tool_index_handler

READ_TOOLS = {
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
# Write tool: (category, action, destructiveHint, idempotentHint)
WRITE_TOOLS = {
    "innerspace_create_walls": ("walls", "create", False, False),
    "innerspace_update_walls": ("walls", "update", False, True),
    "innerspace_remove_walls": ("walls", "delete", True, True),
    "innerspace_create_wall_type": ("wall_types", "create", False, False),
    "innerspace_update_wall_type": ("wall_types", "update", False, True),
    "innerspace_create_attenuation_objects": ("attenuation", "create", False, False),
    "innerspace_update_attenuation_objects": ("attenuation", "update", False, True),
    "innerspace_remove_attenuation_objects": ("attenuation", "delete", True, True),
    "innerspace_create_attenuation_object_type": ("attenuation", "create", False, False),
    "innerspace_update_attenuation_object_type": ("attenuation", "update", False, True),
    "innerspace_rename_floor_plan": ("floor_plans", "update", False, True),
    "innerspace_set_floor_attenuation": ("floor_plans", "update", False, True),
    "innerspace_reorder_floor_plans": ("floor_plans", "update", False, True),
    "innerspace_set_plan_scale": ("floor_plans", "delete", True, True),
    "innerspace_set_project_unit": ("project", "update", False, True),
}
DOMAIN_TOOLS = READ_TOOLS | set(WRITE_TOOLS)
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
        ("lazy", META_TOOLS | {"innerspace_load_tools"} | READ_TOOLS),
        ("eager", META_TOOLS | DOMAIN_TOOLS),
        ("meta_only", META_TOOLS),
    ],
)
async def test_server_startup_registers_the_tool_set(monkeypatch, fresh_registrations, mode, expected):  # noqa: F811
    listed = await start_in_mode(monkeypatch, mode)

    assert set(listed) == expected
    assert "innerspace_get_support_bundle" not in listed
    for name in READ_TOOLS & set(listed):
        tool = listed[name]
        assert tool.annotations.read_only_hint is True, name
        assert tool.annotations.idempotent_hint is True and tool.annotations.open_world_hint is False, name
        assert tool.title, name
    for name in set(WRITE_TOOLS) & set(listed):
        _category, _action, destructive, idempotent = WRITE_TOOLS[name]
        annotations = listed[name].annotations
        assert annotations.read_only_hint is False and annotations.open_world_hint is False, name
        assert (annotations.destructive_hint, annotations.idempotent_hint) == (destructive, idempotent), name
        assert listed[name].title, name


async def test_every_tool_is_reachable_in_meta_only_mode(monkeypatch, fresh_registrations):  # noqa: F811
    await start_in_mode(monkeypatch, "meta_only")

    index = await tool_index_handler({})

    assert {tool["name"] for tool in index["tools"] if tool["name"] in DOMAIN_TOOLS} == DOMAIN_TOOLS


CONFIRM = (
    "When true, re-reads, sends one request and reads the change back; if the outcome is unknown, read before "
    "retrying. When false (default), returns a preview from a fresh read."
)
CONFIRM_CREATE = (
    CONFIRM + " New ids follow from the arguments, so repeating a confirm that already landed sends nothing and "
    "reports already applied; use different arguments for an intentional copy."
)


async def test_write_tools_are_gated_by_category_and_action(monkeypatch, fresh_registrations):  # noqa: F811
    await start_in_mode(monkeypatch, "eager")
    from unifi_innerspace_mcp.tool_index import TOOL_REGISTRY

    for name, (category, action, _destructive, _idempotent) in WRITE_TOOLS.items():
        entry = TOOL_REGISTRY[name]
        assert (entry.permission_category, entry.permission_action) == (category, action), name
        properties = entry.input_schema["properties"]
        assert properties["confirm"]["default"] is False and properties["confirm"]["type"] == "boolean", name
        # Only a create derives its ids from the arguments, so only a create's repeat sends nothing.
        assert properties["confirm"]["description"] == (CONFIRM_CREATE if action == "create" else CONFIRM), name
        # An update sends each object whole, so the item list tells the agent what a concurrent edit loses.
        for prop in properties.values():
            if prop.get("type") == "array" and prop["items"].get("type") == "object" and action == "update":
                assert "is overwritten" in prop["description"], name
        # Lean descriptions: purpose and shape; the confirm flow and field detail live in the schema.
        assert len(entry.description) <= 450, name
        # The remaining race of a write is stated in its docstring or its module's.
        tool_fn = server._tool_manager._tools[name].fn
        assert "Remaining race" in (inspect.getdoc(tool_fn) or "") + (inspect.getmodule(tool_fn).__doc__ or ""), name
        assert entry.input_schema["additionalProperties"] is False, name
        # The schema the index and manifest publish lists exactly the tool's parameters.
        parameters = inspect.signature(server._tool_manager._tools[name].fn).parameters
        assert list(properties) == list(parameters), name
        required = [p for p, spec in parameters.items() if spec.default is inspect.Parameter.empty]
        assert entry.input_schema["required"] == required, name


async def test_lazy_mode_lists_only_read_only_tools_directly(monkeypatch, fresh_registrations):  # noqa: F811
    listed = await start_in_mode(monkeypatch, "lazy")

    assert set(LAZY_DIRECT_TOOLS) == READ_TOOLS
    assert not set(WRITE_TOOLS) & set(listed)
    for name in LAZY_DIRECT_TOOLS:
        assert listed[name].annotations.read_only_hint is True, name


def _remove_walls_manager():
    preview = {"operation": "remove InnerSpace walls", "no_op": False, "effects": {}, "warnings": []}
    return SimpleNamespace(preview_remove_walls=AsyncMock(return_value=preview), apply_remove_walls=AsyncMock())


@pytest.mark.parametrize("mode", ["lazy", "meta_only"])
async def test_execute_reaches_a_write_and_previews_without_confirm(monkeypatch, fresh_registrations, mode):  # noqa: F811
    manager = _remove_walls_manager()
    # The run imports the tool modules afresh, so they take the manager from runtime.
    monkeypatch.setattr(runtime, "wall_manager", manager)
    results = []
    monkeypatch.setattr(main, "UNIFI_TOOL_REGISTRATION_MODE", mode)
    cm = InnerSpaceConnectionManager("", "synthetic-admin", "synthetic-password-0123456789")

    async def serving() -> None:
        arguments = {
            "plan_id": "00000000-0000-4000-8000-000000000003",
            "wall_ids": ["00000000-0000-4000-8000-000000000008"],
        }
        results.append(
            await server.call_tool("innerspace_execute", {"tool": "innerspace_remove_walls", "arguments": arguments})
        )

    try:
        await run_main(monkeypatch, cm, serving, real_registration=True)
    finally:
        await cm.close()

    (result,) = results
    payload = json.loads(result.content[0].text)
    assert payload["success"] is True and payload["requires_confirmation"] is True
    manager.preview_remove_walls.assert_awaited_once()
    manager.apply_remove_walls.assert_not_awaited()


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

    expected = ["innerspace://plans/{plan_id}/image", "innerspace://plans/{plan_id}/image.jpg"]
    assert sorted(_plan_image_templates()) == (expected if registered else [])


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
