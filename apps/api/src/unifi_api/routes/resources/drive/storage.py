"""UniFi Drive storage pools, their usage, and disks.

- ``GET /sites/{site_id}/drive/storage-pools`` → ``drive_list_storage_pools``
- ``GET /sites/{site_id}/drive/storage-usage`` → ``drive_get_storage_usage``
- ``GET /sites/{site_id}/drive/disks`` → ``drive_list_disks``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, items, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/storage-pools",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/storage"],
    summary="List Drive storage pools",
    description=(
        "Storage pools with capacity, usage and status, and each pool's RAID groups: the RAID level in effect "
        "versus the configured one, disk-failure protection, and rebuild or expansion progress. "
        f"{SITE_NOTE}"
    ),
)
async def list_drive_storage_pools(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "list Drive storage pools"
    result = await read(request, controller, manager_attr="storage_manager", method="list_pools", operation=operation)
    return items(request, "drive_list_storage_pools", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/storage-usage",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/storage"],
    summary="Get Drive storage usage",
    description=(
        "Each storage pool's capacity, used and free space, and what the used space is used by: personal "
        "drives, shared drives, Microsoft 365 backups, snapshots and the rest (system and other data). pool_id "
        f"is the id the storage pool list reports. {SITE_NOTE}"
    ),
)
async def get_drive_storage_usage(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive storage usage"
    result = await read(request, controller, manager_attr="storage_manager", method="get_usage", operation=operation)
    return items(request, "drive_get_storage_usage", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/disks",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/storage"],
    summary="List Drive disks",
    description=(
        "Drive bays and SSD cache slots with the disk in each, its pool membership and SMART health. "
        f"Empty bays are left out unless include_empty is true. {SITE_NOTE}"
    ),
)
async def list_drive_disks(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    include_empty: bool = Query(False, description="Also list empty bays and slots"),
    include_cache: bool = Query(True, description="Include SSD cache slots"),
) -> dict:
    operation = "list Drive disks"
    result = await read(
        request,
        controller,
        manager_attr="storage_manager",
        method="list_disks",
        operation=operation,
        include_empty=include_empty,
        include_cache=include_cache,
    )
    return items(request, "drive_list_disks", result, operation=operation)
