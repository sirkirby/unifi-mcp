"""Relay-specific exclusions for support data that must stay direct-to-server."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, TypeVar

from unifi_mcp_shared.meta_tools import is_meta_tool

RELAY_EXCLUDED_TOOL_SUFFIXES: tuple[str, ...] = ("_get_support_bundle",)
RELAY_EXCLUDED_ERROR = "Support bundle tools are unavailable through the relay; call the direct product MCP server."
RELAY_NESTED_META_ERROR = "Relay execute and batch wrappers may target domain tools only."

_MAX_WRAPPER_DEPTH = 8

_Tool = TypeVar("_Tool")


def is_relay_excluded_tool(name: object) -> bool:
    """Return whether an exact tool name belongs to a relay-excluded family."""
    return isinstance(name, str) and name.endswith(RELAY_EXCLUDED_TOOL_SUFFIXES)


def filter_relay_tools(tools: Iterable[_Tool]) -> list[_Tool]:
    """Remove excluded tool objects or mappings from an advertised catalog."""
    return [tool for tool in tools if not is_relay_excluded_tool(_tool_name(tool))]


def filter_tool_index_result(result: Any) -> Any:
    """Filter an indirect tool-index response without mutating the source value."""
    if not isinstance(result, Mapping) or not isinstance(result.get("tools"), list):
        return result
    filtered = filter_relay_tools(result["tools"])
    return {**result, "tools": filtered, "count": len(filtered)}


def relay_call_rejection(tool_name: object, arguments: object) -> str | None:
    """Reject excluded tools and meta-tool composition through execute/batch."""
    return _relay_call_rejection(tool_name, arguments, depth=0, nested=False)


def _relay_call_rejection(tool_name: object, arguments: object, *, depth: int, nested: bool) -> str | None:
    if is_relay_excluded_tool(tool_name):
        return RELAY_EXCLUDED_ERROR
    if not isinstance(tool_name, str) or not isinstance(arguments, Mapping):
        return None

    # Meta-tools remain directly callable through the relay, but allowing one
    # execution wrapper to target another makes the effective operation opaque
    # to relay policy and response filtering. Keep wrappers domain-only.
    if nested and is_meta_tool(tool_name):
        return RELAY_NESTED_META_ERROR
    if depth >= _MAX_WRAPPER_DEPTH and tool_name.endswith(("_execute", "_batch")):
        return RELAY_NESTED_META_ERROR

    if tool_name.endswith("_execute"):
        inner_arguments = arguments.get("arguments", {})
        if not isinstance(inner_arguments, Mapping):
            inner_arguments = {}
        return _relay_call_rejection(arguments.get("tool"), inner_arguments, depth=depth + 1, nested=True)
    if tool_name.endswith("_batch"):
        operations = arguments.get("operations")
        if isinstance(operations, list):
            for operation in operations:
                if not isinstance(operation, Mapping):
                    continue
                inner_arguments = operation.get("arguments", {})
                if not isinstance(inner_arguments, Mapping):
                    inner_arguments = {}
                rejection = _relay_call_rejection(
                    operation.get("tool"),
                    inner_arguments,
                    depth=depth + 1,
                    nested=True,
                )
                if rejection is not None:
                    return rejection
    return None


def _tool_name(tool: Any) -> object:
    if isinstance(tool, Mapping):
        return tool.get("name")
    return getattr(tool, "name", None)
