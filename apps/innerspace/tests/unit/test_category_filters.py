"""One startup per category registers only that category's tools, and each tool's category is its module's."""

from __future__ import annotations

import pytest

from tests.unit.harness import fresh_registrations  # noqa: F401
from tests.unit.test_server_startup import DOMAIN_TOOLS, META_TOOLS, start_in_mode
from unifi_innerspace_mcp import main
from unifi_innerspace_mcp.categories import INNERSPACE_CATEGORY_MAP, TOOL_MODULE_MAP
from unifi_innerspace_mcp.tool_index import TOOL_REGISTRY

BY_CATEGORY = {
    "status": {"innerspace_get_status"},
    "project": {"innerspace_get_project", "innerspace_list_walls", "innerspace_set_project_unit"},
    "floor_plans": {
        "innerspace_list_floor_plans",
        "innerspace_get_plan_asset",
        "innerspace_rename_floor_plan",
        "innerspace_set_floor_attenuation",
        "innerspace_reorder_floor_plans",
        "innerspace_set_plan_scale",
    },
    "devices": {
        "innerspace_list_placed_devices",
        "innerspace_list_access_points",
        "innerspace_list_switches",
        "innerspace_list_inventory",
    },
    "walls": {"innerspace_create_walls", "innerspace_update_walls", "innerspace_remove_walls"},
    "wall_types": {"innerspace_create_wall_type", "innerspace_update_wall_type"},
    "attenuation": {
        "innerspace_create_attenuation_objects",
        "innerspace_update_attenuation_objects",
        "innerspace_remove_attenuation_objects",
        "innerspace_create_attenuation_object_type",
        "innerspace_update_attenuation_object_type",
    },
}


def test_the_categories_partition_the_tools():
    assert set(BY_CATEGORY) == set(INNERSPACE_CATEGORY_MAP)
    assert set().union(*BY_CATEGORY.values()) == DOMAIN_TOOLS
    assert sum(len(tools) for tools in BY_CATEGORY.values()) == len(DOMAIN_TOOLS)


@pytest.mark.parametrize("category", sorted(BY_CATEGORY))
async def test_a_category_filter_registers_only_that_categorys_tools(monkeypatch, fresh_registrations, category):  # noqa: F811
    monkeypatch.setitem(main.config.server, "enabled_categories", INNERSPACE_CATEGORY_MAP[category])

    listed = await start_in_mode(monkeypatch, "eager")

    assert set(listed) == META_TOOLS | BY_CATEGORY[category]
    for name in BY_CATEGORY[category]:
        assert TOOL_REGISTRY[name].permission_category == category, name
        assert TOOL_MODULE_MAP[name].rsplit(".", 1)[1] == INNERSPACE_CATEGORY_MAP[category], name
