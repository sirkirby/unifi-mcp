"""The nine InnerSpace read projections: tool type and REST resource for each."""

from unifi_api.graphql.types.innerspace.devices import (
    InnerSpaceAccessPoint,
    InnerSpaceInventoryDevice,
    InnerSpaceSwitch,
)
from unifi_api.graphql.types.innerspace.floor_plans import InnerSpaceFloorPlan, InnerSpacePlanAsset
from unifi_api.graphql.types.innerspace.project import (
    InnerSpacePlacedDevicePage,
    InnerSpaceProject,
    InnerSpaceWallPage,
)
from unifi_api.graphql.types.innerspace.system import InnerSpaceStatus

# tool -> (resource path under /v1/sites/{site_id}/, projection, kind)
REGISTRATIONS = {
    "innerspace_get_status": ("innerspace/status", InnerSpaceStatus, "detail"),
    "innerspace_get_project": ("innerspace/project", InnerSpaceProject, "detail"),
    "innerspace_list_floor_plans": ("innerspace/floor-plans", InnerSpaceFloorPlan, "list"),
    "innerspace_list_walls": ("innerspace/floor-plans/{plan_id}/walls", InnerSpaceWallPage, "detail"),
    "innerspace_list_placed_devices": (
        "innerspace/floor-plans/{plan_id}/devices",
        InnerSpacePlacedDevicePage,
        "detail",
    ),
    "innerspace_get_plan_asset": ("innerspace/floor-plans/{plan_id}/asset", InnerSpacePlanAsset, "detail"),
    "innerspace_list_access_points": ("innerspace/access-points", InnerSpaceAccessPoint, "list"),
    "innerspace_list_switches": ("innerspace/switches", InnerSpaceSwitch, "list"),
    "innerspace_list_inventory": ("innerspace/inventory", InnerSpaceInventoryDevice, "list"),
}


def register_types(registry):
    for name, (resource, projection, kind) in REGISTRATIONS.items():
        registry.register_tool_type(name, projection, kind)
        registry.register_type("innerspace", resource, projection)
