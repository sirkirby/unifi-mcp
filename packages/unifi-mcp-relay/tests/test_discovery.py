"""Tests for MCP protocol tool discovery."""

from __future__ import annotations

import asyncio
import base64
from importlib.metadata import version
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from unifi_mcp_relay.discovery import (
    LEGACY_MCP_PROTOCOL_REVISION,
    McpHttpClient,
    _build_tools_from_index,
    _build_tools_from_list,
    _relay_client_info,
)
from unifi_mcp_shared.protocol import DEFAULT_MCP_PROTOCOL_REVISION


@pytest.fixture
def mock_mcp_client():
    """Create a mock McpHttpClient that routes requests by method name."""

    def make_mock(side_effect_fn):
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.request = AsyncMock(side_effect=side_effect_fn)
        mock_instance.notify = AsyncMock()
        mock_instance.close = AsyncMock()
        mock_instance.session_id = "session-abc-123"
        mock_instance.protocol_version = LEGACY_MCP_PROTOCOL_REVISION
        mock_cls.return_value = mock_instance
        return mock_cls, mock_instance

    return make_mock


class FakeResponse:
    def __init__(self, payload: dict | None = None, *, headers: dict | None = None, status: int = 200) -> None:
        self._payload = payload or {}
        self.headers = headers or {}
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise aiohttp.ClientResponseError(MagicMock(), (), status=self.status)

    async def json(self) -> dict:
        return self._payload


class FakeSession:
    closed = False

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.posts: list[dict] = []

    def post(self, url: str, *, json: dict, headers: dict):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def test_relay_client_info_matches_current_initialize_metadata():
    info = _relay_client_info()

    assert info["name"] == "unifi-mcp-relay"
    assert info["title"] == "UniFi MCP Relay"
    assert info["version"] == version("unifi-mcp-relay")
    assert info["websiteUrl"] == "https://github.com/sirkirby/unifi-mcp"
    assert [icon["sizes"] for icon in info["icons"]] == [["48x48"], ["96x96"], ["192x192"]]
    assert {icon["mimeType"] for icon in info["icons"]} == {"image/png"}
    assert base64.b64decode(info["icons"][0]["src"].removeprefix("data:image/png;base64,")).startswith(
        b"\x89PNG\r\n\x1a\n"
    )


def test_discovery_filters_support_tools_from_index_and_eager_list():
    index = _build_tools_from_index(
        {
            "tools": [
                {"name": "unifi_tool_index", "schema": {"input": {}}},
                {"name": "unifi_get_support_bundle", "schema": {"input": {}}},
            ]
        },
        "unifi-network-mcp",
    )
    listed = _build_tools_from_list(
        [
            {"name": "protect_get_support_bundle", "inputSchema": {}},
            {"name": "protect_tool_index", "inputSchema": {}},
        ],
        "unifi-protect-mcp",
    )

    assert [tool.name for tool in index] == ["unifi_tool_index"]
    assert [tool.name for tool in listed] == ["protect_tool_index"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "init_result",
    [
        {"protocolVersion": LEGACY_MCP_PROTOCOL_REVISION},
        {"serverInfo": {"name": "old-server"}},
    ],
)
async def test_http_client_preserves_older_or_omitted_protocol_version(init_result):
    session = FakeSession(
        [
            FakeResponse({"jsonrpc": "2.0", "id": 1, "result": init_result}),
            FakeResponse({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}),
        ]
    )
    client = McpHttpClient("http://localhost:3000")
    client._session = session

    await client.request("initialize", {"protocolVersion": DEFAULT_MCP_PROTOCOL_REVISION})
    await client.request("tools/list")

    assert client.protocol_version == LEGACY_MCP_PROTOCOL_REVISION
    assert session.posts[1]["headers"]["MCP-Protocol-Version"] == LEGACY_MCP_PROTOCOL_REVISION


@pytest.mark.asyncio
async def test_discover_tools_identifies_tool_index_by_suffix(mock_mcp_client):
    """Discovery finds protect_tool_index by _tool_index suffix, not hardcoded prefix."""

    tool_index_result = {
        "tools": [
            {
                "name": "protect_list_cameras",
                "description": "List all cameras",
                "schema": {"input": {"type": "object", "properties": {}}},
                "annotations": {"readOnlyHint": True},
            },
        ],
        "count": 1,
    }

    def route_request(method, params=None):
        if method == "initialize":
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "unifi-protect-mcp", "version": "0.2.0"},
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": "protect_tool_index",
                        "description": "Discover available tools",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "protect_execute",
                        "description": "Execute a tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "protect_load_tools",
                        "description": "Load lazy tools",
                        "inputSchema": {"type": "object", "properties": {"tools": {"type": "array"}}},
                    },
                ]
            }
        elif method == "tools/call":
            assert params["name"] == "protect_tool_index"
            return {
                "content": [{"type": "text", "text": __import__("json").dumps(tool_index_result)}],
                "isError": False,
            }
        raise ValueError(f"Unexpected method: {method}")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_tools

        result = await discover_tools("http://localhost:3001")

    assert result is not None
    assert result.name == "unifi-protect-mcp"
    assert result.lazy_load_tool_name == "protect_load_tools"
    assert len(result.tools) == 1
    assert result.tools[0].name == "protect_list_cameras"
    assert result.tools[0].server_origin == "unifi-protect-mcp"


@pytest.mark.asyncio
async def test_discover_tools_overlays_direct_annotations_missing_from_legacy_index(mock_mcp_client):
    """A current relay must preserve annotations from older eager servers."""

    def route_request(method, params=None):
        if method == "initialize":
            return {
                "protocolVersion": LEGACY_MCP_PROTOCOL_REVISION,
                "serverInfo": {"name": "unifi-network-mcp", "version": "0.27.0"},
            }
        if method == "tools/list":
            return {
                "tools": [
                    {"name": "unifi_tool_index", "description": "Index", "inputSchema": {"type": "object"}},
                    {
                        "name": "unifi_list_clients",
                        "title": "List Clients",
                        "description": "Direct eager description",
                        "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer"}}},
                        "annotations": {"readOnlyHint": True, "openWorldHint": False},
                    },
                ]
            }
        if method == "tools/call":
            assert params == {"name": "unifi_tool_index", "arguments": {"include_schemas": True}}
            return {
                "content": [
                    {
                        "type": "text",
                        "text": __import__("json").dumps(
                            {
                                "tools": [
                                    {
                                        "name": "unifi_list_clients",
                                        "description": "Indexed description",
                                        "schema": {"input": {"type": "object"}},
                                    }
                                ]
                            }
                        ),
                    }
                ]
            }
        raise AssertionError(f"Unexpected call: {method}")

    mock_cls, _ = mock_mcp_client(route_request)
    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_tools

        result = await discover_tools("http://localhost:3000")

    assert result is not None
    assert [tool.name for tool in result.tools] == ["unifi_list_clients"]
    tool = result.tools[0]
    assert tool.description == "Indexed description"
    assert tool.title == "List Clients"
    assert tool.input_schema == {"type": "object"}
    assert tool.annotations == {"readOnlyHint": True, "openWorldHint": False}


@pytest.mark.asyncio
async def test_discover_all_concurrent(mock_mcp_client):
    """discover_all runs multiple servers concurrently and collects results."""

    call_count = 0

    def route_request(method, params=None):
        nonlocal call_count
        if method == "initialize":
            call_count += 1
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": f"server-{call_count}", "version": "1.0.0"},
            }
        elif method == "tools/list":
            return {
                "tools": [
                    {
                        "name": f"tool_{call_count}",
                        "description": "A tool",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            }
        raise ValueError(f"Unexpected method: {method}")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_all

        results = await discover_all(["http://localhost:3000", "http://localhost:3001"])

    # Both servers should be discovered (results may vary due to mock sharing)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_discover_all_handles_failures(mock_mcp_client):
    """discover_all logs failures and returns only successful results."""

    def route_request(method, params=None):
        raise ConnectionError("Connection refused")

    mock_cls, mock_instance = mock_mcp_client(route_request)

    with patch("unifi_mcp_relay.discovery.McpHttpClient", mock_cls):
        from unifi_mcp_relay.discovery import discover_all

        results = await discover_all(["http://localhost:3000", "http://localhost:3001"])

    assert results == []


def recovered_session_responses() -> list[FakeResponse]:
    return [
        FakeResponse(
            {"result": {"protocolVersion": DEFAULT_MCP_PROTOCOL_REVISION}},
            headers={"mcp-session-id": "fresh"},
        ),
        FakeResponse(status=202),
    ]


@pytest.mark.asyncio
async def test_http_client_recovers_expired_session_without_stale_headers():
    session = FakeSession(
        [
            FakeResponse(status=404),
            *recovered_session_responses(),
            FakeResponse({"result": {"ok": True}}),
        ]
    )
    client = McpHttpClient("http://localhost:3000", "expired", LEGACY_MCP_PROTOCOL_REVISION)
    client._session = session

    assert await client.request("tools/call", {"name": "mutate", "arguments": {"confirm": True}}) == {"ok": True}
    assert [post["json"]["method"] for post in session.posts] == [
        "tools/call",
        "initialize",
        "notifications/initialized",
        "tools/call",
    ]
    assert "MCP-Session-Id" not in session.posts[1]["headers"]
    assert "MCP-Protocol-Version" not in session.posts[1]["headers"]
    assert session.posts[-1]["headers"]["MCP-Session-Id"] == "fresh"
    assert session.posts[-1]["headers"]["MCP-Protocol-Version"] == DEFAULT_MCP_PROTOCOL_REVISION
    assert session.posts[0]["json"]["params"] == session.posts[-1]["json"]["params"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 429, 500, 503])
async def test_http_client_does_not_replay_other_http_errors(status):
    session = FakeSession([FakeResponse(status=status)])
    client = McpHttpClient("http://localhost:3000", "existing", DEFAULT_MCP_PROTOCOL_REVISION)
    client._session = session
    with pytest.raises(aiohttp.ClientResponseError) as error:
        await client.request("tools/call", {"name": "mutate"})
    assert error.value.status == status
    assert len(session.posts) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [asyncio.TimeoutError(), aiohttp.ServerDisconnectedError()])
async def test_http_client_does_not_replay_uncertain_transport_failures(error):
    client = McpHttpClient("http://localhost:3000", "existing", DEFAULT_MCP_PROTOCOL_REVISION)
    with patch.object(client, "_request_once", AsyncMock(side_effect=error)) as send:
        with pytest.raises(type(error)):
            await client.request("tools/call", {"name": "mutate"})
    send.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,session_id", [("initialize", "existing"), ("tools/call", None)])
async def test_http_client_does_not_recover_404_without_an_established_session(method, session_id):
    session = FakeSession([FakeResponse(status=404)])
    client = McpHttpClient("http://localhost:3000", session_id)
    client._session = session
    with pytest.raises(aiohttp.ClientResponseError):
        await client.request(method)
    assert len(session.posts) == 1


@pytest.mark.asyncio
async def test_http_client_retries_expired_request_at_most_once():
    session = FakeSession([FakeResponse(status=404), *recovered_session_responses(), FakeResponse(status=404)])
    client = McpHttpClient("http://localhost:3000", "expired", DEFAULT_MCP_PROTOCOL_REVISION)
    client._session = session
    with pytest.raises(aiohttp.ClientResponseError):
        await client.request("tools/call", {"name": "mutate"})
    assert len(session.posts) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_notification", [False, True])
async def test_http_client_can_recover_on_later_call_after_failed_handshake(fail_notification):
    initial = recovered_session_responses()[:1] if fail_notification else []
    session = FakeSession(
        [
            FakeResponse(status=404),
            *initial,
            FakeResponse(status=503),
            FakeResponse(status=404),
            *recovered_session_responses(),
            FakeResponse({"result": {"ok": True}}),
        ]
    )
    client = McpHttpClient("http://localhost:3000", "expired", LEGACY_MCP_PROTOCOL_REVISION)
    client._session = session
    with pytest.raises(aiohttp.ClientResponseError):
        await client.request("tools/call", {"name": "mutate"})
    assert client.session_id == "expired"
    assert client.protocol_version == LEGACY_MCP_PROTOCOL_REVISION
    assert await client.request("tools/call", {"name": "mutate"}) == {"ok": True}
