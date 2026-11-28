"""UniFi Drive snapshot settings and snapshots. Read-only: nothing here takes, locks, restores or deletes one.

- ``GET /sites/{site_id}/drive/snapshot-overview`` → ``drive_get_snapshot_overview``
- ``GET /sites/{site_id}/drive/snapshots/shared/{shared_drive_name}`` → ``drive_list_snapshots``

Drive addresses a shared drive's snapshots by the drive's name, not its id, so
the list lives apart from ``shared-drives/{drive_id}``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, detail, items, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/snapshot-overview",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/snapshots"],
    summary="Get Drive snapshot overview",
    description=(
        "Every shared and personal drive's snapshot settings and state: snapshot limit and count, locked and "
        "pending-deletion counts, space held, last and next snapshot time, whether snapshots are paused and why, "
        "and the schedule. A drive whose snapshots were never set up is listed with configured false and a zero "
        f"limit. {SITE_NOTE}"
    ),
)
async def get_drive_snapshot_overview(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive snapshot overview"
    result = await read(
        request, controller, manager_attr="snapshot_manager", method="get_snapshot_overview", operation=operation
    )
    return detail(request, "drive_get_snapshot_overview", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/snapshots/shared/{shared_drive_name}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/snapshots"],
    summary="List a Drive shared drive's snapshots",
    description=(
        "One shared drive's snapshots, newest first (id, name, Drive's label, creation time, locked), by the "
        "shared drive's name, not its id: the name the shared drive list or the snapshot overview reports. A "
        f"name no shared drive has is a 404. {SITE_NOTE}"
    ),
)
async def list_drive_snapshots(
    request: Request,
    site_id: str,
    shared_drive_name: str,
    controller=Depends(resolve_controller),
) -> dict:
    operation = "list Drive snapshots"
    result = await read(
        request,
        controller,
        manager_attr="snapshot_manager",
        method="list_snapshots",
        operation=operation,
        args=(shared_drive_name,),
    )
    return items(request, "drive_list_snapshots", result, operation=operation)
