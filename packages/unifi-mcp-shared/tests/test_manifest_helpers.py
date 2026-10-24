"""Tests for the manifest_helpers module."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from unifi_mcp_shared.manifest_helpers import get_tool_annotations


def _make_server(tools: dict | None = None, *, has_manager: bool = True) -> SimpleNamespace:
    """Build a fake FastMCP server with optional _tool_manager._tools."""
    if not has_manager:
        return SimpleNamespace()
    if tools is None:
        return SimpleNamespace(_tool_manager=SimpleNamespace(_tools=None))
    return SimpleNamespace(_tool_manager=SimpleNamespace(_tools=tools))


def _make_tool(annotations=None) -> SimpleNamespace:
    """Build a fake FastMCP Tool object."""
    return SimpleNamespace(annotations=annotations)


def _make_annotations(**kwargs) -> SimpleNamespace:
    """Build a fake ToolAnnotations pydantic model with getattr support."""
    defaults = {
        "title": None,
        "readOnlyHint": None,
        "destructiveHint": None,
        "idempotentHint": None,
        "openWorldHint": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestGetToolAnnotations:
    @pytest.mark.parametrize(
        ("server", "expected"),
        [
            (
                _make_server(
                    {"my_tool": _make_tool(annotations=_make_annotations(readOnlyHint=True, openWorldHint=False))}
                ),
                {"my_tool": {"readOnlyHint": True, "openWorldHint": False}},
            ),
            (
                _make_server(
                    {
                        "tool_a": _make_tool(annotations=_make_annotations(readOnlyHint=True)),
                        "tool_b": _make_tool(annotations=None),
                    }
                ),
                {"tool_a": {"readOnlyHint": True}},
            ),
            (_make_server(has_manager=False), {}),
            (_make_server(tools=None), {}),
            (_make_server({"my_tool": _make_tool(annotations=_make_annotations())}), {}),
            (
                _make_server(
                    {
                        "dangerous_tool": _make_tool(
                            annotations=_make_annotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True)
                        )
                    }
                ),
                {"dangerous_tool": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True}},
            ),
            (
                _make_server(
                    {
                        "read_tool": _make_tool(annotations=_make_annotations(readOnlyHint=True)),
                        "write_tool": _make_tool(annotations=_make_annotations(destructiveHint=True)),
                    }
                ),
                {"read_tool": {"readOnlyHint": True}, "write_tool": {"destructiveHint": True}},
            ),
        ],
    )
    def test_get_tool_annotations(self, server, expected):
        assert get_tool_annotations(server) == expected

    def test_exception_returns_empty(self):
        """Iteration failure should not crash, just return empty."""

        class BadTools:
            def items(self):
                raise RuntimeError("boom")

        server = SimpleNamespace(_tool_manager=SimpleNamespace(_tools=BadTools()))
        assert get_tool_annotations(server) == {}
