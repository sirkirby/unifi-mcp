"""Normalize and serialize MCP tool results at the transport boundary."""

from __future__ import annotations

import json
from typing import Any

from mcp.types import CallToolResult, TextContent

from unifi_mcp_shared.protocol import structured_content_supported
from unifi_mcp_shared.response_policy import MCPContentMode

_MAX_COMPACT_TEXT_CHARS = 2_000


def _json_text_content(result: Any) -> Any:
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], TextContent):
        try:
            return json.loads(result[0].text)
        except json.JSONDecodeError:
            return result
    return result


def normalize_call_tool_result(result: Any) -> Any:
    """Unwrap canonical MCP result envelopes without changing domain data."""
    if isinstance(result, CallToolResult):
        if result.structuredContent is not None:
            return result.structuredContent
        return _json_text_content(result.content)
    if isinstance(result, tuple) and len(result) == 2:
        content, structured = result
        if structured is not None:
            return structured
        return _json_text_content(content)
    return _json_text_content(result)


def compact_content_text(structured: Any, *, tool_name: str) -> str:
    """Build a bounded compatibility summary for a structured tool result."""
    parts: list[str] = []
    if isinstance(structured, dict):
        if structured.get("success") is False:
            parts.append(f"{tool_name} failed: {structured.get('error') or 'unknown error'}")
        elif structured.get("requires_confirmation") is True:
            parts.append(f"{tool_name} requires confirmation.")
        else:
            parts.append(f"{tool_name} completed successfully.")
        message = structured.get("message")
        if isinstance(message, str) and message.strip():
            parts.append(message.strip())
        for key in ("count", "returned_count", "total_count"):
            value = structured.get(key)
            if isinstance(value, int):
                parts.append(f"{key}={value}.")
    else:
        parts.append(f"{tool_name} completed successfully.")
    parts.append("Full result is available in structuredContent.")
    return " ".join(parts)[:_MAX_COMPACT_TEXT_CHARS]


def _compact_content(content: list[Any], structured: Any, *, tool_name: str) -> list[Any]:
    summary = TextContent(
        type="text",
        text=compact_content_text(structured, tool_name=tool_name),
    )
    compacted: list[Any] = []
    summary_added = False

    for block in content:
        is_json = False
        if isinstance(block, TextContent):
            try:
                json.loads(block.text)
                is_json = True
            except json.JSONDecodeError:
                pass

        if is_json:
            if not summary_added:
                compacted.append(summary)
                summary_added = True
            continue
        compacted.append(block)

    if not summary_added:
        compacted.insert(0, summary)
    return compacted


def serialize_call_tool_result(
    result: Any,
    *,
    mode: MCPContentMode,
    protocol_revision: str | None,
    tool_name: str,
) -> Any:
    """Compact compatible structured results according to MCP response policy."""
    should_compact = mode == "compact" or (mode == "adaptive" and structured_content_supported(protocol_revision))
    if not should_compact:
        return result

    if isinstance(result, CallToolResult):
        structured = result.structuredContent
        if structured is None:
            return result
        return result.model_copy(update={"content": _compact_content(result.content, structured, tool_name=tool_name)})

    if isinstance(result, tuple) and len(result) == 2 and result[1] is not None:
        content, structured = result
        return CallToolResult(
            content=_compact_content(content, structured, tool_name=tool_name),
            structuredContent=structured,
        )
    return result
