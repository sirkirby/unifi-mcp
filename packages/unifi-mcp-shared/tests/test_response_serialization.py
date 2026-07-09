"""Tests for MCP tool-result normalization and response serialization."""

from __future__ import annotations

from mcp.types import CallToolResult, ImageContent, TextContent
from unifi_mcp_shared.response_serialization import (
    compact_content_text,
    normalize_call_tool_result,
    serialize_call_tool_result,
)


def _structured_tuple(structured):
    content = [TextContent(type="text", text='{"success": true}')]
    return content, structured


def test_normalize_prefers_structured_tuple():
    content = [TextContent(type="text", text='{"success": true}')]
    structured = {"success": True, "data": {"id": "abc"}}
    assert normalize_call_tool_result((content, structured)) == structured


def test_normalize_prefers_direct_call_tool_structured_content():
    result = CallToolResult(
        content=[TextContent(type="text", text='{"success": true}')],
        structuredContent={"success": True},
    )
    assert normalize_call_tool_result(result) == {"success": True}


def test_normalize_parses_single_json_text_block():
    content = [TextContent(type="text", text='{"success": true, "count": 2}')]
    assert normalize_call_tool_result(content) == {"success": True, "count": 2}


def test_normalize_preserves_plain_text_content():
    content = [TextContent(type="text", text="plain text")]
    assert normalize_call_tool_result(content) is content


def test_normalize_preserves_image_content():
    content = [ImageContent(type="image", data="AA==", mimeType="image/png")]
    assert normalize_call_tool_result(content) is content


def test_normalize_prefers_empty_structured_object_over_content():
    content = [TextContent(type="text", text='{"old": true}')]
    assert normalize_call_tool_result((content, {})) == {}


def test_adaptive_compacts_supported_revision():
    result = _structured_tuple({"success": True, "count": 250, "items": [{"id": 1}]})
    compact = serialize_call_tool_result(
        result,
        mode="adaptive",
        protocol_revision="2025-11-25",
        tool_name="unifi_list_records",
    )
    assert isinstance(compact, CallToolResult)
    assert compact.structuredContent["count"] == 250
    assert compact.content
    assert "250" in compact.content[0].text
    assert "items" not in compact.content[0].text


def test_adaptive_preserves_legacy_revision():
    result = _structured_tuple({"success": True})
    assert (
        serialize_call_tool_result(
            result,
            mode="adaptive",
            protocol_revision="2025-03-26",
            tool_name="unifi_test",
        )
        is result
    )


def test_adaptive_preserves_unknown_context():
    result = _structured_tuple({"success": True})
    assert (
        serialize_call_tool_result(
            result,
            mode="adaptive",
            protocol_revision=None,
            tool_name="unifi_test",
        )
        is result
    )


def test_compact_override_works_without_revision():
    result = serialize_call_tool_result(
        _structured_tuple({"success": False, "error": "controller unavailable"}),
        mode="compact",
        protocol_revision=None,
        tool_name="unifi_test",
    )
    assert result.structuredContent["success"] is False
    assert result.content
    assert "controller unavailable" in result.content[0].text


def test_compat_override_preserves_supported_revision():
    original = _structured_tuple({"success": True})
    assert (
        serialize_call_tool_result(
            original,
            mode="compat",
            protocol_revision="2026-07-28",
            tool_name="unifi_test",
        )
        is original
    )


def test_content_only_result_is_never_rewritten():
    content = [TextContent(type="text", text="plain text")]
    assert (
        serialize_call_tool_result(
            content,
            mode="compact",
            protocol_revision="2026-07-28",
            tool_name="unifi_test",
        )
        is content
    )


def test_compacting_direct_result_preserves_meta_and_error_status():
    original = CallToolResult(
        content=[TextContent(type="text", text='{"success": false}')],
        structuredContent={"success": False, "error": "controller unavailable"},
        isError=True,
        _meta={"request_id": "req-123"},
    )

    compact = serialize_call_tool_result(
        original,
        mode="compact",
        protocol_revision=None,
        tool_name="unifi_test",
    )

    assert compact is not original
    assert compact.meta == {"request_id": "req-123"}
    assert compact.isError is True
    assert compact.structuredContent == original.structuredContent
    assert compact.content
    assert compact.content[0].text == compact_content_text(
        original.structuredContent,
        tool_name="unifi_test",
    )
