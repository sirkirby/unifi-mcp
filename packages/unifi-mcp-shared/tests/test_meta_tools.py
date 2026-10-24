"""Tests for shared meta-tool registration helpers."""

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP
from mcp.types import (
    AudioContent,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)
from pydantic import BaseModel
from unifi_core.jobs import JobStore
from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.meta_tools import is_meta_tool, register_load_tools, register_meta_tools
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_mcp_shared.tool_index import TOOL_REGISTRY, get_tool_index, register_tool


class StructuredInnerResult(BaseModel):
    """Structured domain result returned by a real FastMCP inner tool."""

    success: bool
    data: dict[str, Any]


def _capture_tools():
    registered = {}

    def tool_decorator(**kwargs):
        def decorator(func):
            registered[kwargs["name"]] = {"handler": func, **kwargs}
            return func

        return decorator

    return registered, tool_decorator


def _context():
    return SimpleNamespace(notify_tools_changed=AsyncMock())


def _register_test_meta_tools(*, server, prefix, start_async_tool=None, get_job_status=None):
    registered, tool_decorator = _capture_tools()
    register_meta_tools(
        server=server,
        tool_decorator=tool_decorator,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=start_async_tool or AsyncMock(),
        get_job_status=get_job_status or AsyncMock(),
        register_tool=Mock(),
        support_bundle_handler=AsyncMock(return_value={"success": True, "data": {}}),
        prefix=prefix,
    )
    return registered


def test_meta_tool_registered_schemas_and_descriptions():
    register_tool = Mock()
    register_meta_tools(
        server=SimpleNamespace(),
        tool_decorator=_capture_tools()[1],
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=AsyncMock(),
        get_job_status=AsyncMock(),
        register_tool=register_tool,
        support_bundle_handler=AsyncMock(return_value={"success": True, "data": {}}),
        prefix="unifi",
    )

    calls = {call.kwargs["name"]: call.kwargs for call in register_tool.call_args_list}
    description = calls["unifi_tool_index"]["input_schema"]["properties"]["search"]["description"]
    assert "token search" in description
    assert "at most 20" in description
    assert "no usable terms returns no tools" in description
    assert "manifest-backed in lazy mode" in calls["unifi_tool_index"]["description"]
    assert "in meta-only mode it starts with registered meta-tools" in calls["unifi_tool_index"]["description"]

    assert calls["unifi_execute"]["input_schema"]["properties"]["arguments"]["type"] == ["object", "null"]

    operations_schema = calls["unifi_batch"]["input_schema"]["properties"]["operations"]
    tool_description = operations_schema["items"]["properties"]["tool"]["description"]
    arguments_description = operations_schema["items"]["properties"]["arguments"]["description"]
    assert "unifi_tool_index in lazy mode" in tool_description
    assert "known domain tool name in meta-only mode" in tool_description
    assert arguments_description == "Tool parameters matching the domain tool's input schema"


def test_meta_tool_index_objects_contain_declared_annotations():
    TOOL_REGISTRY.clear()
    try:
        register_meta_tools(
            server=SimpleNamespace(),
            tool_decorator=_capture_tools()[1],
            tool_index_handler=AsyncMock(return_value={}),
            start_async_tool=AsyncMock(),
            get_job_status=AsyncMock(),
            register_tool=register_tool,
            support_bundle_handler=AsyncMock(return_value={"success": True, "data": {}}),
            prefix="unifi",
        )
        register_load_tools(
            server=SimpleNamespace(),
            tool_decorator=_capture_tools()[1],
            lazy_loader=SimpleNamespace(load_tool=AsyncMock()),
            register_tool=register_tool,
            tool_module_map={},
            prefix="unifi",
        )

        tools = {
            tool["name"]: tool for tool in get_tool_index(registration_mode="eager", include_schemas=True)["tools"]
        }
        expected = {
            "unifi_tool_index": True,
            "unifi_execute": False,
            "unifi_batch": False,
            "unifi_batch_status": True,
            "unifi_load_tools": False,
            "unifi_get_support_bundle": True,
        }
        for name, read_only in expected.items():
            assert tools[name]["annotations"] == {
                "readOnlyHint": read_only,
                "destructiveHint": False,
                "idempotentHint": name
                in {"unifi_tool_index", "unifi_batch_status", "unifi_load_tools", "unifi_get_support_bundle"},
                "openWorldHint": False,
            }
    finally:
        TOOL_REGISTRY.clear()


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_legacy_positional_meta_registration_does_not_advertise_support(prefix, caplog):
    server = FastMCP("legacy-app")
    registered = Mock()
    with caplog.at_level("INFO"):
        register_meta_tools(
            server,
            server.tool,
            AsyncMock(),
            AsyncMock(),
            AsyncMock(),
            registered,
            prefix,
            "Legacy app",
            "legacy domain",
        )
    names = {tool.name for tool in await server.list_tools()}
    assert names == {f"{prefix}_{suffix}" for suffix in ("tool_index", "execute", "batch", "batch_status")}
    assert {call.kwargs["name"] for call in registered.call_args_list} == names
    assert "get_support_bundle" not in caplog.text


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_support_bundle_schema_annotations_and_behavior(prefix):
    handler = AsyncMock(return_value={"success": True, "data": {"schema_version": 1}})
    registered, tool_decorator = _capture_tools()
    register_tool_mock = Mock()
    register_meta_tools(
        server=SimpleNamespace(),
        tool_decorator=tool_decorator,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=AsyncMock(),
        get_job_status=AsyncMock(),
        register_tool=register_tool_mock,
        support_bundle_handler=handler,
        prefix=prefix,
    )

    name = f"{prefix}_get_support_bundle"
    tool = registered[name]
    assert tool["annotations"].read_only_hint is True
    assert tool["annotations"].destructive_hint is False
    assert tool["annotations"].idempotent_hint is True
    assert tool["annotations"].open_world_hint is False
    assert is_meta_tool(name) is True

    result = await tool["handler"]("summary", None)
    assert result == {"success": True, "data": {"schema_version": 1}}
    handler.assert_awaited_once_with(probe="summary", resource=None)

    registered_meta = next(call for call in register_tool_mock.call_args_list if call.kwargs["name"] == name)
    assert registered_meta.kwargs["input_schema"]["properties"]["probe"]["enum"] == [
        "summary",
        "connectivity",
        "resource_shape",
    ]
    assert registered_meta.kwargs["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }


async def test_support_bundle_wrapper_never_logs_raw_failures_or_payloads(caplog):
    canary = "token-DO-NOT-LOG"
    handler = AsyncMock(side_effect=RuntimeError(canary))
    registered, tool_decorator = _capture_tools()
    register_meta_tools(
        server=SimpleNamespace(),
        tool_decorator=tool_decorator,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=AsyncMock(),
        get_job_status=AsyncMock(),
        register_tool=Mock(),
        support_bundle_handler=handler,
        prefix="unifi",
    )

    result = await registered["unifi_get_support_bundle"]["handler"]("summary", None)

    assert result == {"success": False, "error": "Failed to generate support bundle."}
    assert canary not in caplog.text
    assert "traceback" not in caplog.text.lower()


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_execute_normalizes_structured_inner_result(prefix):
    payload = {"success": True, "data": {"id": "abc"}}
    content = [TextContent(type="text", text=json.dumps(payload))]
    server = SimpleNamespace(call_tool=AsyncMock(return_value=(content, payload)))
    registered = _register_test_meta_tools(server=server, prefix=prefix)

    result = await registered[f"{prefix}_execute"]["handler"](f"{prefix}_inner", {})

    assert result == payload


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_batch_stores_normalized_structured_result(prefix):
    stored = {}

    async def start_async_tool(executor, arguments):
        stored["result"] = await executor(**arguments)
        return {"jobId": "job-1"}

    payload = {"success": True, "count": 2}
    content = [TextContent(type="text", text=json.dumps(payload))]
    server = SimpleNamespace(call_tool=AsyncMock(return_value=(content, payload)))
    registered = _register_test_meta_tools(
        server=server,
        prefix=prefix,
        start_async_tool=start_async_tool,
    )

    await registered[f"{prefix}_batch"]["handler"]([{"tool": f"{prefix}_inner", "arguments": {}}])

    assert stored["result"] == payload


CONTENT_ONLY_RESULTS = [
    pytest.param([TextContent(type="text", text="plain text")], id="plain-text"),
    pytest.param(
        [ImageContent(type="image", data="AA==", mimeType="image/png")],
        id="image",
    ),
    pytest.param(
        [AudioContent(type="audio", data="AA==", mimeType="audio/wav")],
        id="audio",
    ),
    pytest.param(
        [ResourceLink(type="resource_link", name="record", uri="https://example.test/record")],
        id="resource-link",
    ),
    pytest.param(
        [
            EmbeddedResource(
                type="resource",
                resource=TextResourceContents(
                    uri="file:///tmp/record.txt",
                    mimeType="text/plain",
                    text="record",
                ),
            )
        ],
        id="embedded-resource",
    ),
    pytest.param(
        [
            TextContent(type="text", text="explanation"),
            ImageContent(type="image", data="AA==", mimeType="image/png"),
        ],
        id="mixed-content",
    ),
]


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
@pytest.mark.parametrize("content", CONTENT_ONLY_RESULTS)
async def test_execute_preserves_content_only_result(prefix, content):
    server = SimpleNamespace(call_tool=AsyncMock(return_value=content))
    registered = _register_test_meta_tools(server=server, prefix=prefix)

    result = await registered[f"{prefix}_execute"]["handler"](f"{prefix}_inner", {})

    assert result is content


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
@pytest.mark.parametrize("content", CONTENT_ONLY_RESULTS[:2])
async def test_batch_preserves_content_only_result(prefix, content):
    stored = {}

    async def start_async_tool(executor, arguments):
        stored["result"] = await executor(**arguments)
        return {"jobId": "job-1"}

    server = SimpleNamespace(call_tool=AsyncMock(return_value=content))
    registered = _register_test_meta_tools(
        server=server,
        prefix=prefix,
        start_async_tool=start_async_tool,
    )

    await registered[f"{prefix}_batch"]["handler"]([{"tool": f"{prefix}_inner", "arguments": {}}])

    assert stored["result"] is content


@pytest.mark.parametrize("execute_args", [{}, None])
@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_fastmcp_execute_and_batch_expose_domain_payload(prefix, execute_args):
    payload = {"success": True, "data": {"id": "abc"}}
    server = FastMCP(f"{prefix}-test")
    store = JobStore()

    @server.tool(name=f"{prefix}_inner", structured_output=True)
    async def structured_inner() -> StructuredInnerResult:
        return StructuredInnerResult(**payload)

    async def start_async_tool(executor, arguments):
        job_id = await store.start(executor(**arguments))
        return {"jobId": job_id}

    register_meta_tools(
        server=server,
        tool_decorator=server.tool,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=start_async_tool,
        get_job_status=store.status,
        register_tool=Mock(),
        support_bundle_handler=AsyncMock(return_value={"success": True, "data": {}}),
        prefix=prefix,
    )

    execute = await server.call_tool(
        f"{prefix}_execute",
        {"tool": f"{prefix}_inner", "arguments": execute_args},
    )
    assert json.loads(execute.content[0].text) == payload

    batch = await server.call_tool(
        f"{prefix}_batch",
        {"operations": [{"tool": f"{prefix}_inner", "arguments": {}}]},
    )
    job_id = json.loads(batch.content[0].text)["jobs"][0]["jobId"]

    for _ in range(10):
        if (await store.status(job_id))["status"] == "done":
            break
        await asyncio.sleep(0)

    status = await server.call_tool(f"{prefix}_batch_status", {"jobId": job_id})
    status_payload = json.loads(status.content[0].text)
    assert status_payload["status"] == "done"
    assert status_payload["result"] == payload


class TestRegisterLoadTools:
    """Tests for lazy direct-tool loading and list-changed notifications."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("tools", "load_return", "expected_loaded", "expected_errors", "notified"),
        [
            (["unifi_list_clients"], True, ["unifi_list_clients"], None, True),
            (["unifi_unknown"], True, [], [{"tool": "unifi_unknown", "error": "Unknown tool"}], False),
            (["unifi_list_clients"], False, [], [{"tool": "unifi_list_clients", "error": "Failed to load"}], False),
        ],
    )
    async def test_load_tools_behavior_and_notifications(
        self, tools, load_return, expected_loaded, expected_errors, notified
    ):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=load_return))

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        description = registered["unifi_load_tools"]["description"]
        assert "tools/list" in description
        assert "notifications/tools/list_changed" in description

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](tools, ctx)

        assert result["loaded"] == expected_loaded
        assert result["errors"] == expected_errors
        if tools == ["unifi_unknown"]:
            lazy_loader.load_tool.assert_not_awaited()
        else:
            lazy_loader.load_tool.assert_awaited_once_with("unifi_list_clients")
        if notified:
            ctx.notify_tools_changed.assert_awaited_once()
        else:
            ctx.notify_tools_changed.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_tool_index_forwards_exact_name_and_schemas(prefix):
    captured, decorator = _capture_tools()
    handler = AsyncMock(return_value={"tools": [], "count": 0, "categories": [], "filtered": True})
    registry = Mock()
    register_meta_tools(
        server=SimpleNamespace(),
        tool_decorator=decorator,
        tool_index_handler=handler,
        start_async_tool=AsyncMock(),
        get_job_status=AsyncMock(),
        register_tool=registry,
        support_bundle_handler=AsyncMock(),
        prefix=prefix,
    )
    name = f"{prefix}_list_devices"
    result = await captured[f"{prefix}_tool_index"]["handler"](name=name, include_schemas=True)
    handler.assert_awaited_once_with({"name": name, "include_schemas": True})
    assert result["count"] == 0
    registration = next(c for c in registry.call_args_list if c.kwargs["name"] == f"{prefix}_tool_index")
    assert registration.kwargs["input_schema"]["properties"]["name"]["type"] == "string"


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_execute_and_batch_reach_the_named_tools_policy_gate(prefix, monkeypatch):
    """The meta-tools are readOnlyHint=false, but they skip no server-side check."""
    monkeypatch.setenv("UNIFI_POLICY_TEST_CREATE", "false")
    server = FastMCP(f"{prefix}-test")
    store = JobStore()
    calls = []
    permissioned_tool = create_permissioned_tool(
        original_tool_decorator=server.tool,
        policy_gate_checker=PolicyGateChecker(server_prefix="test"),
        server_prefix="TEST",
        register_tool_fn=Mock(),
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda func, name: func,
        logger=logging.getLogger("test"),
    )

    @permissioned_tool(name=f"{prefix}_create_thing", permission_category="things", permission_action="create")
    async def create_thing(confirm: bool = False) -> dict:
        calls.append(confirm)
        return {"success": True, "data": {}}

    async def start_async_tool(executor, arguments):
        return {"jobId": await store.start(executor(**arguments))}

    register_meta_tools(
        server=server,
        tool_decorator=server.tool,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=start_async_tool,
        get_job_status=store.status,
        register_tool=Mock(),
        support_bundle_handler=AsyncMock(return_value={"success": True, "data": {}}),
        prefix=prefix,
    )

    execute = await server.call_tool(
        f"{prefix}_execute", {"tool": f"{prefix}_create_thing", "arguments": {"confirm": True}}
    )
    assert json.loads(execute.content[0].text)["success"] is False
    assert "UNIFI_POLICY_TEST_THINGS_CREATE" in execute.content[0].text

    batch = await server.call_tool(
        f"{prefix}_batch", {"operations": [{"tool": f"{prefix}_create_thing", "arguments": {"confirm": True}}]}
    )
    job_id = json.loads(batch.content[0].text)["jobs"][0]["jobId"]
    for _ in range(10):
        if (await store.status(job_id))["status"] == "done":
            break
        await asyncio.sleep(0)
    assert (await store.status(job_id))["result"]["success"] is False

    assert calls == []
