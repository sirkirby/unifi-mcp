"""Tests for the manifest_helpers module."""

from __future__ import annotations

from types import SimpleNamespace

from unifi_core.manifest_helpers import get_tool_annotations


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
    def test_extracts_annotations_correctly(self):
        ann = _make_annotations(readOnlyHint=True, openWorldHint=False)
        server = _make_server({"my_tool": _make_tool(annotations=ann)})

        result = get_tool_annotations(server)
        assert result == {"my_tool": {"readOnlyHint": True, "openWorldHint": False}}

    def test_skips_tools_without_annotations(self):
        server = _make_server(
            {
                "tool_a": _make_tool(annotations=_make_annotations(readOnlyHint=True)),
                "tool_b": _make_tool(annotations=None),
            }
        )
        result = get_tool_annotations(server)
        assert "tool_a" in result
        assert "tool_b" not in result

    def test_no_tool_manager_returns_empty(self):
        server = _make_server(has_manager=False)
        result = get_tool_annotations(server)
        assert result == {}

    def test_tools_is_none_returns_empty(self):
        server = _make_server(tools=None)
        result = get_tool_annotations(server)
        assert result == {}

    def test_all_none_fields_excluded(self):
        """Annotations where all fields are None should not appear in the result."""
        ann = _make_annotations()  # all defaults are None
        server = _make_server({"my_tool": _make_tool(annotations=ann)})
        result = get_tool_annotations(server)
        assert result == {}

    def test_mixed_fields(self):
        ann = _make_annotations(
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=True,
        )
        server = _make_server({"dangerous_tool": _make_tool(annotations=ann)})
        result = get_tool_annotations(server)
        assert result == {
            "dangerous_tool": {
                "readOnlyHint": False,
                "destructiveHint": True,
                "idempotentHint": True,
            }
        }

    def test_exception_returns_empty(self):
        """Iteration failure should not crash, just return empty."""

        class BadTools:
            def items(self):
                raise RuntimeError("boom")

        server = SimpleNamespace(_tool_manager=SimpleNamespace(_tools=BadTools()))
        result = get_tool_annotations(server)
        assert result == {}

    def test_multiple_tools(self):
        server = _make_server(
            {
                "read_tool": _make_tool(annotations=_make_annotations(readOnlyHint=True)),
                "write_tool": _make_tool(annotations=_make_annotations(destructiveHint=True)),
            }
        )
        result = get_tool_annotations(server)
        assert len(result) == 2
        assert result["read_tool"] == {"readOnlyHint": True}
        assert result["write_tool"] == {"destructiveHint": True}
