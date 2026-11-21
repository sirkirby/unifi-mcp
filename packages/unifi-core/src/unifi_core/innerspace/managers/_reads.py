"""Shared reads for the InnerSpace managers: list endpoints, plan geometry and the project unit."""

from __future__ import annotations

from typing import Any

from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.innerspace.managers.connection_manager import (
    INTEGRATION_PREFIX,
    INTERNAL_PROJECT_PATH,
    InnerSpaceConnectionManager,
)
from unifi_core.innerspace.models._coerce import as_dict
from unifi_core.innerspace.models.floor_plans import PlanGeometry, plan_geometry_from_api
from unifi_core.innerspace.models.project import plan_maps_from_api
from unifi_core.innerspace.units import Unit, parse_unit


def site_params(site_id: str | None) -> dict[str, str] | None:
    return None if site_id is None else {"siteId": site_id}


async def read_list(
    cm: InnerSpaceConnectionManager,
    name: str,
    *,
    operation: str,
    params: dict[str, str] | None = None,
    key: str | None = None,
) -> list[dict[str, Any]]:
    """The rows under ``key`` (default ``name``) of ``GET {prefix}/{name}``.

    Anything but a list of objects is malformed, never empty or filtered.
    """
    key = key or name
    raw = await cm.request("GET", f"{INTEGRATION_PREFIX}/{name}", operation=operation, params=params)
    rows = as_dict(raw).get(key)
    if not isinstance(rows, list):
        raise UniFiMalformedResponseError(f"{operation}: the console returned no {key} list")
    if not all(isinstance(row, dict) for row in rows):
        raise UniFiMalformedResponseError(f"{operation}: the console returned a {key} row that is not an object")
    return rows


async def read_floor_plan_rows(
    cm: InnerSpaceConnectionManager, *, operation: str, site_id: str | None = None
) -> list[dict[str, Any]]:
    return await read_list(cm, "floor_plans", operation=operation, params=site_params(site_id))


def geometry_by_plan(rows: list[dict[str, Any]]) -> dict[str, PlanGeometry]:
    return {row["id"]: plan_geometry_from_api(row) for row in rows if isinstance(row.get("id"), str)}


async def read_project(cm: InnerSpaceConnectionManager, *, operation: str) -> Any:
    """The documented project read, in 3D mode (walls are the same in 2D and 3D)."""
    return await cm.request("GET", f"{INTEGRATION_PREFIX}/project", operation=operation, params={"mode": "3D"})


async def read_plan_maps(cm: InnerSpaceConnectionManager, *, operation: str) -> dict[str, dict[str, Any]]:
    """Each plan's map shape from the project read: image address, scale and offset."""
    return plan_maps_from_api(await read_project(cm, operation=operation))


async def read_project_unit(cm: InnerSpaceConnectionManager, *, operation: str) -> Unit:
    """The project's unit from the console's internal project read; unknown or missing is malformed."""
    raw = await cm.request("GET", INTERNAL_PROJECT_PATH, operation=operation)
    return parse_unit(as_dict(as_dict(as_dict(raw).get("data")).get("project")).get("unit"))
