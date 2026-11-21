"""The package imports, and its generated files agree with each other."""

import json
from pathlib import Path

import unifi_innerspace_mcp
from unifi_innerspace_mcp.categories import TOOL_MODULE_MAP

_MANIFEST = Path(unifi_innerspace_mcp.__file__).parent / "tools_manifest.json"


def test_package_importable():
    assert unifi_innerspace_mcp.__doc__ is not None


def test_core_managers_importable_and_share_one_connection():
    from unifi_core.innerspace.managers.connection_manager import InnerSpaceConnectionManager
    from unifi_core.innerspace.managers.floor_plan_manager import InnerSpaceFloorPlanManager
    from unifi_core.innerspace.managers.inventory_manager import InnerSpaceInventoryManager
    from unifi_core.innerspace.managers.project_manager import InnerSpaceProjectManager
    from unifi_core.innerspace.managers.system_manager import InnerSpaceSystemManager

    cm = InnerSpaceConnectionManager("192.0.2.10", "user", "pass")
    for manager in (
        InnerSpaceProjectManager,
        InnerSpaceFloorPlanManager,
        InnerSpaceInventoryManager,
        InnerSpaceSystemManager,
    ):
        assert manager(cm) is not None


def test_tool_index_importable():
    from unifi_innerspace_mcp.tool_index import TOOL_REGISTRY, ToolMetadata, register_tool

    assert isinstance(TOOL_REGISTRY, dict)
    assert ToolMetadata is not None and register_tool is not None


def test_tool_module_map_matches_the_manifest():
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))

    assert manifest["count"] == len(manifest["tools"])
    assert manifest["module_map"] == TOOL_MODULE_MAP
    assert all(name.startswith("innerspace_") for name in TOOL_MODULE_MAP)
