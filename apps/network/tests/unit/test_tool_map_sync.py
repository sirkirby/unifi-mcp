"""Test that TOOL_MODULE_MAP stays in sync with tools_manifest.json.

This test ensures that the lazy loader's dynamic tool discovery finds all
tools that are listed in the manifest, preventing the case where tools go
missing from the map.
"""

import json
from pathlib import Path

import pytest


class TestToolMapSync:
    """Tests for tool map and manifest synchronization."""

    @pytest.fixture
    def manifest_tools(self) -> set[str]:
        """Load tool names from the manifest."""
        manifest_path = Path("apps/network/src/unifi_network_mcp/tools_manifest.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        return {t["name"] for t in manifest["tools"]}

    @pytest.fixture
    def tool_module_map(self) -> dict[str, str]:
        """Load the TOOL_MODULE_MAP."""
        from unifi_network_mcp.categories import TOOL_MODULE_MAP

        return TOOL_MODULE_MAP

    @pytest.fixture
    def meta_tools(self, manifest_tools: set[str]) -> set[str]:
        """Meta-tools that are registered separately, not via TOOL_MODULE_MAP."""
        from unifi_mcp_shared.meta_tools import is_meta_tool

        return {name for name in manifest_tools if is_meta_tool(name)}

    def test_all_manifest_tools_in_map(
        self, manifest_tools: set[str], tool_module_map: dict[str, str], meta_tools: set[str]
    ):
        """Verify all manifest tools (except meta-tools) are in TOOL_MODULE_MAP.

        This prevents the lazy loader from failing to find tools that are
        listed in the manifest but missing from the map.
        """
        # Remove meta-tools from comparison (they're registered separately)
        regular_tools = manifest_tools - meta_tools
        map_tools = set(tool_module_map.keys())

        missing = regular_tools - map_tools

        assert not missing, (
            f"Tools in manifest but missing from TOOL_MODULE_MAP: {sorted(missing)}\n"
            f"The dynamic tool discovery in lazy_tool_loader.py may have failed to find these tools.\n"
            f"Check that the tool files have proper name='unifi_xxx' decorators."
        )

    def test_no_extra_tools_in_map(
        self, manifest_tools: set[str], tool_module_map: dict[str, str], meta_tools: set[str]
    ):
        """Verify TOOL_MODULE_MAP doesn't have tools not in the manifest.

        This catches stale entries that reference tools that no longer exist.
        """
        regular_tools = manifest_tools - meta_tools
        map_tools = set(tool_module_map.keys())

        extra = map_tools - regular_tools

        assert not extra, (
            f"Tools in TOOL_MODULE_MAP but not in manifest: {sorted(extra)}\n"
            f"These may be stale entries or tools that were removed.\n"
            f"Run 'make manifest' to regenerate the manifest."
        )

    def test_tool_count_matches(self, manifest_tools: set[str], tool_module_map: dict[str, str], meta_tools: set[str]):
        """Verify the tool counts match between manifest and map."""
        regular_tools = manifest_tools - meta_tools
        map_tools = set(tool_module_map.keys())

        assert len(regular_tools) == len(map_tools), (
            f"Tool count mismatch: manifest has {len(regular_tools)} tools, map has {len(map_tools)} tools"
        )

    def test_dynamic_discovery_works(self):
        """Verify the dynamic tool discovery function works correctly."""
        from unifi_network_mcp.categories import _build_tool_module_map

        tool_map = _build_tool_module_map()

        # Should find a reasonable number of tools
        assert len(tool_map) >= 50, f"Dynamic discovery only found {len(tool_map)} tools, expected 50+"

        # Should find some known tools
        known_tools = [
            "unifi_list_clients",
            "unifi_list_devices",
            "unifi_get_top_clients",
            "unifi_list_firewall_policies",
        ]

        for tool in known_tools:
            assert tool in tool_map, f"Known tool '{tool}' not found by dynamic discovery"

    def test_module_paths_are_valid(self, tool_module_map: dict[str, str]):
        """Verify all module paths in the map are valid Python module paths."""
        for tool_name, module_path in tool_module_map.items():
            # Module path should start with src.tools.
            assert module_path.startswith("unifi_network_mcp.tools."), (
                f"Tool '{tool_name}' has invalid module path: {module_path}\nExpected path starting with 'unifi_network_mcp.tools.'"
            )

            # Module path should be a valid Python identifier pattern
            parts = module_path.split(".")
            for part in parts:
                assert part.isidentifier(), (
                    f"Tool '{tool_name}' has invalid module path: {module_path}\n"
                    f"Part '{part}' is not a valid Python identifier"
                )
