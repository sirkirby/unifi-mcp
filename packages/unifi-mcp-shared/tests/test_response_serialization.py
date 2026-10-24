"""Tests for MCP tool-result normalization and response serialization."""

from __future__ import annotations

import json

import pytest
from mcp.types import CallToolResult, ImageContent, TextContent
from unifi_mcp_shared.response_serialization import (
    compact_content_text,
    normalize_call_tool_result,
    serialize_call_tool_result,
)


def _structured_tuple(structured):
    content = [TextContent(type="text", text='{"success": true}')]
    return content, structured


def _mixed_content():
    structured = {"success": True, "data": {"id": "abc", "name": "record"}}
    compatibility_text = TextContent(
        type="text",
        text='{"success":true,"data":{"id":"abc","name":"record"}}',
    )
    explanatory_text = TextContent(type="text", text="Controller returned the requested record.")
    image = ImageContent(type="image", data="AA==", mimeType="image/png")
    duplicate_compatibility_text = TextContent(
        type="text",
        text='{"success": true, "data": {"id": "abc", "name": "record"}}',
    )
    return (
        [compatibility_text, explanatory_text, image, duplicate_compatibility_text],
        structured,
        explanatory_text,
        image,
    )


def _json_text_blocks(content):
    parsed = []
    for block in content:
        if isinstance(block, TextContent):
            try:
                parsed.append(json.loads(block.text))
            except json.JSONDecodeError:
                pass
    return parsed


def _non_identical_json_content():
    records = [{"id": 1, "name": "record", "description": "large compatibility payload"}]
    structured = {"success": True, "data": records, "count": 1}
    compatibility_text = TextContent(type="text", text=json.dumps(records))
    explanatory_text = TextContent(type="text", text="Controller returned the requested record.")
    image = ImageContent(type="image", data="AA==", mimeType="image/png")
    return [compatibility_text, explanatory_text, image], structured, explanatory_text, image


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            ([TextContent(type="text", text='{"success": true}')], {"success": True, "data": {"id": "abc"}}),
            {"success": True, "data": {"id": "abc"}},
        ),
        (
            CallToolResult(
                content=[TextContent(type="text", text='{"success": true}')], structuredContent={"success": True}
            ),
            {"success": True},
        ),
        ([TextContent(type="text", text='{"success": true, "count": 2}')], {"success": True, "count": 2}),
        (([TextContent(type="text", text='{"old": true}')], {}), {}),
    ],
)
def test_normalize_extracts_structured_or_json_dict(raw, expected):
    assert normalize_call_tool_result(raw) == expected


@pytest.mark.parametrize(
    "content",
    [
        [TextContent(type="text", text="plain text")],
        [ImageContent(type="image", data="AA==", mimeType="image/png")],
    ],
)
def test_normalize_preserves_non_json_content(content):
    assert normalize_call_tool_result(content) is content


def test_adaptive_compacts_supported_revision():
    result = _structured_tuple({"success": True, "count": 250, "items": [{"id": 1}]})
    compact = serialize_call_tool_result(
        result,
        mode="adaptive",
        protocol_revision="2025-11-25",
        tool_name="unifi_list_records",
    )
    assert isinstance(compact, CallToolResult)
    assert compact.structured_content["count"] == 250
    assert compact.content
    assert "250" in compact.content[0].text
    assert "items" not in compact.content[0].text
    assert _json_text_blocks(compact.content) == []


@pytest.mark.parametrize(
    ("mode", "protocol_revision", "content_only"),
    [
        ("adaptive", "2025-03-26", False),
        ("adaptive", None, False),
        ("compat", "2026-07-28", False),
        ("compact", "2026-07-28", True),
    ],
)
def test_serialize_preserves_original_when_not_compacting(mode, protocol_revision, content_only):
    original = [TextContent(type="text", text="plain text")] if content_only else _structured_tuple({"success": True})
    assert (
        serialize_call_tool_result(
            original,
            mode=mode,
            protocol_revision=protocol_revision,
            tool_name="unifi_test",
        )
        is original
    )


def test_compact_override_works_without_revision():
    result = serialize_call_tool_result(
        _structured_tuple({"success": False, "error": "controller unavailable"}),
        mode="compact",
        protocol_revision=None,
        tool_name="unifi_test",
    )
    assert result.structured_content["success"] is False
    assert result.content
    assert "controller unavailable" in result.content[0].text


@pytest.mark.parametrize("as_direct_result", [True, False])
def test_compacting_preserves_mixed_content(as_direct_result):
    content, structured, explanatory_text, image = _mixed_content()
    raw = CallToolResult(content=content, structuredContent=structured) if as_direct_result else (content, structured)

    compact = serialize_call_tool_result(
        raw,
        mode="compact",
        protocol_revision=None,
        tool_name="unifi_test",
    )

    summary = compact_content_text(structured, tool_name="unifi_test")
    assert isinstance(compact, CallToolResult)
    assert compact.structured_content == structured
    assert len(compact.content) == 3
    assert isinstance(compact.content[0], TextContent)
    assert compact.content[0].text == summary
    assert sum(isinstance(block, TextContent) and block.text == summary for block in compact.content) == 1
    assert compact.content[1] is explanatory_text
    assert compact.content[2] is image


@pytest.mark.parametrize("as_direct_result", [True, False])
def test_compacting_removes_non_identical_json_collection(as_direct_result):
    content, structured, explanatory_text, image = _non_identical_json_content()
    raw = CallToolResult(content=content, structuredContent=structured) if as_direct_result else (content, structured)

    compact = serialize_call_tool_result(
        raw,
        mode="compact",
        protocol_revision=None,
        tool_name="unifi_list_records",
    )

    summary = compact_content_text(structured, tool_name="unifi_list_records")
    assert isinstance(compact, CallToolResult)
    assert compact.structured_content == structured
    assert len(compact.content) == 3
    assert isinstance(compact.content[0], TextContent)
    assert compact.content[0].text == summary
    assert _json_text_blocks(compact.content) == []
    assert compact.content[1] is explanatory_text
    assert compact.content[2] is image


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
    assert compact.is_error is True
    assert compact.structured_content == original.structured_content
    assert compact.content
    assert compact.content[0].text == compact_content_text(
        original.structured_content,
        tool_name="unifi_test",
    )
