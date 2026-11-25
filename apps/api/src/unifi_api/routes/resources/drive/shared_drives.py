"""UniFi Drive shared drives.

- ``GET /sites/{site_id}/drive/shared-drives`` → ``drive_list_shared_drives``
- ``GET /sites/{site_id}/drive/shared-drives/{drive_id}`` → ``drive_get_shared_drive``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, detail, items, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/shared-drives",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/shared-drives"],
    summary="List Drive shared drives",
    description=(
        "Shared drives with their storage pool, usage, quota, status, encryption, snapshot and remote-backup "
        f"flags. {SITE_NOTE}"
    ),
)
async def list_drive_shared_drives(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "list Drive shared drives"
    result = await read(
        request, controller, manager_attr="shared_drive_manager", method="list_shared_drives", operation=operation
    )
    return items(request, "drive_list_shared_drives", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/shared-drives/{drive_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/shared-drives"],
    summary="Get a Drive shared drive",
    description=(
        f"One shared drive by id. Drive omits the protection flags and member count that the list includes. {SITE_NOTE}"
    ),
)
async def get_drive_shared_drive(
    request: Request,
    site_id: str,
    drive_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    operation = "get Drive shared drive"
    result = await read(
        request,
        controller,
        manager_attr="shared_drive_manager",
        method="get_shared_drive",
        operation=operation,
        args=(drive_id,),
    )
    return detail(request, "drive_get_shared_drive", result, operation=operation)
