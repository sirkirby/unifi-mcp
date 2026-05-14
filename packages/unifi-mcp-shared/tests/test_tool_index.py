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

    def test_permission_fields_default_none(self):
        meta = ToolMetadata(name="test", description="A test tool")
        assert meta.permission_category is None
        assert meta.permission_action is None

    def test_permission_fields_stored(self):
        meta = ToolMetadata(
            name="test",
            description="A test tool",
            permission_category="networks",
            permission_action="update",
        )
        assert meta.permission_category == "networks"
        assert meta.permission_action == "update"

    def test_to_dict_excludes_none_permission_fields(self):
        meta = ToolMetadata(name="test", description="A test tool")
        d = meta.to_dict()
        assert "permission_category" not in d
        assert "permission_action" not in d

    def test_to_dict_includes_permission_fields(self):
        meta = ToolMetadata(
            name="test",
            description="A test tool",
            permission_category="networks",
            permission_action="update",
        )
        d = meta.to_dict()
        assert d["permission_category"] == "networks"
        assert d["permission_action"] == "update"


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

    def test_register_with_permission_metadata(self):
        register_tool(
            name="my_tool",
            description="test",
            permission_category="networks",
            permission_action="update",
        )
        meta = TOOL_REGISTRY["my_tool"]
        assert meta.permission_category == "networks"
        assert meta.permission_action == "update"

    def test_register_without_permission_metadata(self):
        register_tool(name="my_tool", description="test")
        meta = TOOL_REGISTRY["my_tool"]
        assert meta.permission_category is None
        assert meta.permission_action is None


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
        manifest = {"tools": [{"name": "from_manifest", "description": "A tool"}], "count": 1}
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
        index = get_tool_index(registration_mode="eager", include_schemas=True)
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
        index = get_tool_index(registration_mode="eager", include_schemas=True)
        tool = index["tools"][0]
        assert tool["annotations"] == {"readOnlyHint": True, "openWorldHint": False}

    def test_tool_index_annotations_absent_when_not_set(self):
        """get_tool_index should omit annotations key when not provided (consistent with manifest)."""
        register_tool(name="my_tool", description="test")
        index = get_tool_index(registration_mode="eager", include_schemas=True)
        tool = index["tools"][0]
        assert "annotations" not in tool

    def test_tool_index_annotations_from_manifest(self, tmp_path):
        """get_tool_index should pass through annotations from the manifest."""
        manifest = {
            "tools": [{"name": "from_manifest", "description": "test", "annotations": {"readOnlyHint": True}}],
            "count": 1,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path, include_schemas=True)
        assert index["tools"][0]["annotations"] == {"readOnlyHint": True}

    def test_returns_all_tools_regardless_of_permissions(self):
        """Tool index returns all tools — filtering is no longer done here."""
        register_tool(name="read_tool", description="Read only")
        register_tool(
            name="denied_tool",
            description="Would be denied",
            permission_category="networks",
            permission_action="update",
        )
        index = get_tool_index(registration_mode="eager")
        assert index["count"] == 2
        names = {t["name"] for t in index["tools"]}
        assert "read_tool" in names
        assert "denied_tool" in names

    # --- Default compact response (names + descriptions, no schemas) ---

    def test_default_returns_name_and_description_only(self):
        """Default response should include name and description but not schemas."""
        register_tool(
            name="my_tool",
            description="Does something useful",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        index = get_tool_index(registration_mode="eager")
        tool = index["tools"][0]
        assert tool["name"] == "my_tool"
        assert tool["description"] == "Does something useful"
        assert "schema" not in tool

    def test_include_schemas_returns_full_tools(self):
        """include_schemas=True should return full tool objects with schemas."""
        register_tool(
            name="my_tool",
            description="Does something",
            input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        index = get_tool_index(registration_mode="eager", include_schemas=True)
        tool = index["tools"][0]
        assert "schema" in tool
        assert "input" in tool["schema"]

    # --- Category filtering ---

    def test_category_filter_with_manifest(self, tmp_path):
        """Category filter should use module_map to match tools."""
        manifest = {
            "tools": [
                {"name": "unifi_list_clients", "description": "List clients"},
                {"name": "unifi_list_devices", "description": "List devices"},
                {"name": "unifi_block_client", "description": "Block a client"},
            ],
            "module_map": {
                "unifi_list_clients": "app.tools.clients",
                "unifi_list_devices": "app.tools.devices",
                "unifi_block_client": "app.tools.clients",
            },
            "count": 3,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path, category="clients")
        assert index["count"] == 2
        names = {t["name"] for t in index["tools"]}
        assert names == {"unifi_list_clients", "unifi_block_client"}
        assert index["filtered"] is True

    def test_category_filter_case_insensitive(self, tmp_path):
        """Category filter should be case-insensitive."""
        manifest = {
            "tools": [{"name": "unifi_list_clients", "description": "List"}],
            "module_map": {"unifi_list_clients": "app.tools.clients"},
            "count": 1,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path, category="Clients")
        assert index["count"] == 1

    # --- Search filtering ---

    def test_search_matches_name(self):
        register_tool(name="unifi_list_clients", description="List all clients")
        register_tool(name="unifi_list_devices", description="List all devices")
        index = get_tool_index(registration_mode="eager", search="client")
        assert index["count"] == 1
        assert index["tools"][0]["name"] == "unifi_list_clients"
        assert index["filtered"] is True

    def test_search_matches_description(self):
        register_tool(name="unifi_get_stats", description="Get firewall statistics")
        register_tool(name="unifi_list_devices", description="List all devices")
        index = get_tool_index(registration_mode="eager", search="firewall")
        assert index["count"] == 1
        assert index["tools"][0]["name"] == "unifi_get_stats"

    def test_search_case_insensitive(self):
        register_tool(name="unifi_list_clients", description="List clients")
        index = get_tool_index(registration_mode="eager", search="LIST")
        assert index["count"] == 1

    # --- Categories metadata ---

    def test_categories_always_present(self):
        """Response should always include the categories list."""
        index = get_tool_index(registration_mode="eager")
        assert "categories" in index
        assert isinstance(index["categories"], list)

    def test_categories_derived_from_module_map(self, tmp_path):
        manifest = {
            "tools": [
                {"name": "t1", "description": ""},
                {"name": "t2", "description": ""},
            ],
            "module_map": {"t1": "app.tools.clients", "t2": "app.tools.firewall"},
            "count": 2,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path)
        assert "clients" in index["categories"]
        assert "firewall" in index["categories"]

    def test_categories_present_even_when_filtered(self, tmp_path):
        """Categories should list ALL categories, not just the filtered ones."""
        manifest = {
            "tools": [
                {"name": "t1", "description": ""},
                {"name": "t2", "description": ""},
            ],
            "module_map": {"t1": "app.tools.clients", "t2": "app.tools.firewall"},
            "count": 2,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(registration_mode="lazy", manifest_path=manifest_path, category="clients")
        assert index["count"] == 1
        # Both categories should still be listed
        assert "clients" in index["categories"]
        assert "firewall" in index["categories"]

    # --- Filtered flag ---

    def test_no_filtered_flag_without_filters(self):
        register_tool(name="tool_a", description="A")
        index = get_tool_index(registration_mode="eager")
        assert "filtered" not in index

    def test_filtered_flag_with_search(self):
        register_tool(name="tool_a", description="A")
        index = get_tool_index(registration_mode="eager", search="tool")
        assert index["filtered"] is True

    # --- Combined filters ---

    def test_category_and_search_combined(self, tmp_path):
        manifest = {
            "tools": [
                {"name": "unifi_list_clients", "description": "List clients"},
                {"name": "unifi_block_client", "description": "Block a client"},
                {"name": "unifi_list_devices", "description": "List devices"},
            ],
            "module_map": {
                "unifi_list_clients": "app.tools.clients",
                "unifi_block_client": "app.tools.clients",
                "unifi_list_devices": "app.tools.devices",
            },
            "count": 3,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(
            registration_mode="lazy",
            manifest_path=manifest_path,
            category="clients",
            search="block",
        )
        assert index["count"] == 1
        assert index["tools"][0]["name"] == "unifi_block_client"

    def test_category_with_include_schemas(self, tmp_path):
        manifest = {
            "tools": [
                {"name": "t1", "description": "D1", "schema": {"input": {"type": "object"}}},
                {"name": "t2", "description": "D2", "schema": {"input": {"type": "object"}}},
            ],
            "module_map": {"t1": "app.tools.clients", "t2": "app.tools.firewall"},
            "count": 2,
        }
        manifest_path = tmp_path / "tools_manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        index = get_tool_index(
            registration_mode="lazy",
            manifest_path=manifest_path,
            category="clients",
            include_schemas=True,
        )
        assert index["count"] == 1
        assert "schema" in index["tools"][0]


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
