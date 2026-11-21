"""InnerSpace projections: fields from the core models, redaction by policy, no image bytes."""

from __future__ import annotations

import dataclasses

import pytest
from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_api.graphql.types.innerspace.floor_plans import InnerSpacePlanAsset
from unifi_api.graphql.types.innerspace.project import InnerSpaceProject, InnerSpaceWallPage
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.models.project import Project, ProjectSummary, Wall, WallPage

TOOLS = {
    "innerspace_get_status": "detail",
    "innerspace_get_project": "detail",
    "innerspace_list_floor_plans": "list",
    "innerspace_list_walls": "detail",
    "innerspace_list_placed_devices": "detail",
    "innerspace_list_access_points": "list",
    "innerspace_list_switches": "list",
    "innerspace_list_inventory": "list",
    "innerspace_get_plan_asset": "detail",
}


def _summary(**changes) -> ProjectSummary:
    values = dict(
        project=Project(id="p1", title="T", unit="metric"),
        unit="metric",
        plans=[],
        wall_types=[],
        attenuation_object_types=[dict(id="ao", token="synthetic-value")],
    )
    values.update(changes)
    return ProjectSummary(**values)


def test_every_tool_is_registered_with_its_kind():
    registry = build_type_registry()
    registered = {name: registry.lookup_tool(name)[1] for name in TOOLS}
    assert registered == TOOLS


@pytest.mark.parametrize(("redact", "shown"), [(True, "***REDACTED***"), (False, "synthetic-value")])
def test_project_redacts_by_policy(redact, shown):
    projected = InnerSpaceProject.from_manager_output(_summary(), redact_sensitive=redact).to_dict()
    assert projected["attenuation_object_types"] == [{"id": "ao", "token": shown}]
    assert projected["project"]["title"] == "T"


def test_wall_page_carries_the_limit():
    page = WallPage(
        unit="metric", plan_id="p", walls=[Wall(id="w")], total=3, truncated=True, scale_missing=False, unreadable=0
    )
    projected = InnerSpaceWallPage.from_manager_output({**page.model_dump(), "limit": 1}).to_dict()
    assert (projected["limit"], projected["total"], projected["truncated"]) == (1, 3, True)
    assert [wall["id"] for wall in projected["walls"]] == ["w"]


def test_plan_asset_drops_image_bytes():
    asset = {
        "filename": "f.png",
        "content_type": "image/png",
        "width_px": 1.0,
        "height_px": 2.0,
        "scale_per_unit": None,
        "image_scale": None,
        "image_offset": None,
        "unit": "metric",
        "image_base64": "iVBORw0KGgo=",
    }
    projected = InnerSpacePlanAsset.from_manager_output(asset).to_dict()
    assert "image_base64" not in projected
    assert projected["filename"] == "f.png"
    assert all("base64" not in field.name for field in dataclasses.fields(InnerSpacePlanAsset))


def test_non_json_values_are_malformed():
    with pytest.raises(UniFiMalformedResponseError):
        InnerSpaceProject.from_manager_output(_summary(attenuation_object_types=[{"x": float("nan")}]))
