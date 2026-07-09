"""Tests for shared meta-tool registration helpers."""

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.fastmcp import FastMCP
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
from unifi_mcp_shared.meta_tools import register_load_tools, register_meta_tools


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
    return SimpleNamespace(session=SimpleNamespace(send_tool_list_changed=AsyncMock()))


def _register_test_meta_tools(*, server, prefix, start_async_tool=None, get_job_status=None):
    registered, tool_decorator = _capture_tools()
    register_meta_tools(
        server=server,
        tool_decorator=tool_decorator,
        tool_index_handler=AsyncMock(return_value={}),
        start_async_tool=start_async_tool or AsyncMock(),
        get_job_status=get_job_status or AsyncMock(),
        register_tool=Mock(),
        prefix=prefix,
    )
    return registered


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


@pytest.mark.parametrize("prefix", ["unifi", "protect", "access"])
async def test_fastmcp_execute_and_batch_expose_domain_payload(prefix):
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
        prefix=prefix,
    )

    execute = await server.call_tool(
        f"{prefix}_execute",
        {"tool": f"{prefix}_inner", "arguments": {}},
    )
    assert len(execute) == 1
    assert json.loads(execute[0].text) == payload

    batch = await server.call_tool(
        f"{prefix}_batch",
        {"operations": [{"tool": f"{prefix}_inner", "arguments": {}}]},
    )
    job_id = json.loads(batch[0].text)["jobs"][0]["jobId"]

    for _ in range(10):
        if (await store.status(job_id))["status"] == "done":
            break
        await asyncio.sleep(0)

    status = await server.call_tool(f"{prefix}_batch_status", {"jobId": job_id})
    status_payload = json.loads(status[0].text)
    assert status_payload["status"] == "done"
    assert status_payload["result"] == payload


class TestRegisterLoadTools:
    """Tests for lazy direct-tool loading and list-changed notifications."""

    @pytest.mark.asyncio
    async def test_loaded_tools_send_list_changed_notification(self):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=True))
        register_tool = Mock()

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=register_tool,
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](["unifi_list_clients"], ctx)

        assert result["loaded"] == ["unifi_list_clients"]
        assert result["errors"] is None
        lazy_loader.load_tool.assert_awaited_once_with("unifi_list_clients")
        ctx.session.send_tool_list_changed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_tools_do_not_send_list_changed_notification(self):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=True))

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](["unifi_unknown"], ctx)

        assert result["loaded"] == []
        assert result["errors"] == [{"tool": "unifi_unknown", "error": "Unknown tool"}]
        lazy_loader.load_tool.assert_not_awaited()
        ctx.session.send_tool_list_changed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_failed_load_does_not_send_list_changed_notification(self):
        registered, tool_decorator = _capture_tools()
        lazy_loader = SimpleNamespace(load_tool=AsyncMock(return_value=False))

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=lazy_loader,
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        ctx = _context()
        result = await registered["unifi_load_tools"]["handler"](["unifi_list_clients"], ctx)

        assert result["loaded"] == []
        assert result["errors"] == [{"tool": "unifi_list_clients", "error": "Failed to load"}]
        ctx.session.send_tool_list_changed.assert_not_awaited()

    def test_load_tools_description_uses_standard_notification_name(self):
        registered, tool_decorator = _capture_tools()

        register_load_tools(
            server=Mock(),
            tool_decorator=tool_decorator,
            lazy_loader=SimpleNamespace(load_tool=AsyncMock(return_value=True)),
            register_tool=Mock(),
            tool_module_map={"unifi_list_clients": "unifi_network_mcp.tools.clients"},
        )

        description = registered["unifi_load_tools"]["description"]
        assert "tools/list" in description
        assert "notifications/tools/list_changed" in description
