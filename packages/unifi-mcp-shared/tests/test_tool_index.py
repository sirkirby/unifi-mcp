"""Tests for the shared tool_index module."""

import json

import pytest

from unifi_mcp_shared.tool_index import (
    TOOL_REGISTRY,
    ToolMetadata,
    get_tool_index,
    register_tool,
)


@pytest.fixture(autouse=True)
def clean_registry():
    """Clear the global registry before each test."""
    TOOL_REGISTRY.clear()
    yield
    TOOL_REGISTRY.clear()


class TestToolMetadata:
    """Tests for ToolMetadata dataclass."""

    def test_to_dict_excludes_none(self):
        meta = ToolMetadata(name="test", description="A test tool")
        d = meta.to_dict()
        assert "output_schema" not in d
        assert d["name"] == "test"

    def test_to_dict_includes_all_set_fields(self):
        meta = ToolMetadata(
            name="test",
            description="desc",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            auth_method="either",
        )
        d = meta.to_dict()
        assert d["output_schema"] == {"type": "object"}
        assert d["auth_method"] == "either"


class TestRegisterTool:
    """Tests for register_tool."""

    def test_registers_tool(self):
        register_tool(name="my_tool", description="Does something")
        assert "my_tool" in TOOL_REGISTRY
        assert TOOL_REGISTRY["my_tool"].description == "Does something"

    def test_default_input_schema(self):
        register_tool(name="my_tool", description="test")
        assert TOOL_REGISTRY["my_tool"].input_schema == {"type": "object", "properties": {}}

    def test_custom_input_schema(self):
        schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
        register_tool(name="my_tool", description="test", input_schema=schema)
        assert TOOL_REGISTRY["my_tool"].input_schema == schema

    def test_overwrites_existing(self):
        register_tool(name="my_tool", description="v1")
        register_tool(name="my_tool", description="v2")
        assert TOOL_REGISTRY["my_tool"].description == "v2"


class TestGetToolIndex:
    """Tests for get_tool_index."""

    def test_returns_registered_tools(self):
        register_tool(name="tool_a", description="Tool A")
        register_tool(name="tool_b", description="Tool B")
        index = get_tool_index(registration_mode="eager")
        assert index["count"] == 2
        names = {t["name"] for t in index["tools"]}
        assert names == {"tool_a", "tool_b"}

    def test_empty_registry(self):
        index = get_tool_index(registration_mode="eager")
        assert index["count"] == 0
        assert index["tools"] == []

    def test_lazy_mode_with_manifest(self, tmp_path):
        manifest = {"tools": [{"name": "from_manifest"}], "count": 1}
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path)
        assert index["count"] == 1
        assert index["tools"][0]["name"] == "from_manifest"

    def test_lazy_mode_missing_manifest_falls_back(self, tmp_path):
        register_tool(name="runtime_tool", description="From runtime")
        index = get_tool_index(
            registration_mode="lazy",
            manifest_path=tmp_path / "nonexistent.json",
        )
        assert index["count"] == 1
        assert index["tools"][0]["name"] == "runtime_tool"

    def test_tool_schema_structure(self):
        register_tool(
            name="my_tool",
            description="test",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
            output_schema={"type": "object"},
        )
        index = get_tool_index(registration_mode="eager")
        tool = index["tools"][0]
        assert "input" in tool["schema"]
        assert "output" in tool["schema"]

    def test_tool_index_includes_annotations_from_runtime(self):
        """get_tool_index should include annotations from registered ToolMetadata."""
        register_tool(
            name="my_tool",
            description="test",
            annotations={"readOnlyHint": True, "openWorldHint": False},
        )
        index = get_tool_index(registration_mode="eager")
        tool = index["tools"][0]
        assert tool["annotations"] == {"readOnlyHint": True, "openWorldHint": False}

    def test_tool_index_annotations_none_when_not_set(self):
        """get_tool_index annotations should be None when not provided."""
        register_tool(name="my_tool", description="test")
        index = get_tool_index(registration_mode="eager")
        tool = index["tools"][0]
        assert tool["annotations"] is None

    def test_tool_index_annotations_from_manifest(self, tmp_path):
        """get_tool_index should pass through annotations from the manifest."""
        manifest = {
            "tools": [{"name": "from_manifest", "annotations": {"readOnlyHint": True}}],
            "count": 1,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path)
        assert index["tools"][0]["annotations"] == {"readOnlyHint": True}


class TestToolMetadataAnnotations:
    """Tests for annotations field in ToolMetadata."""

    def test_tool_metadata_includes_annotations(self):
        """ToolMetadata should accept and store annotations dict."""
        meta = ToolMetadata(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
            annotations={"readOnlyHint": True, "openWorldHint": False},
        )
        assert meta.annotations == {"readOnlyHint": True, "openWorldHint": False}

    def test_tool_metadata_annotations_default_none(self):
        """ToolMetadata annotations should default to None for backwards compatibility."""
        meta = ToolMetadata(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object"},
        )
        assert meta.annotations is None
