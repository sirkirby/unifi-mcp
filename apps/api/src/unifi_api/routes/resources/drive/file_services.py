"""UniFi Drive file services, SMB advanced and rsync settings, and NFS client connections.

- ``GET /sites/{site_id}/drive/file-services`` → ``drive_get_file_services``
- ``GET /sites/{site_id}/drive/smb-advanced-settings`` → ``drive_get_smb_advanced_settings``
- ``GET /sites/{site_id}/drive/rsync-settings`` → ``drive_get_rsync_settings``
- ``GET /sites/{site_id}/drive/nfs-connections`` → ``drive_list_nfs_connections``

Changing them goes through the preview-first actions, never these routes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, detail, items, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/file-services",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/file-services"],
    summary="Get Drive file services",
    description=(
        "Whether SMB, NFS and Time Machine are enabled on the NAS, and the network interfaces clients connect "
        f"to. {SITE_NOTE}"
    ),
)
async def get_drive_file_services(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive file services"
    result = await read(
        request, controller, manager_attr="file_service_manager", method="get_file_services", operation=operation
    )
    return detail(request, "drive_get_file_services", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/smb-advanced-settings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/file-services"],
    summary="Get Drive SMB advanced settings",
    description=(
        "Whether SMB Trash for personal drives is on (files removed over SMB go to Trash instead of being "
        f"deleted) and whether every personal drive could move to it. {SITE_NOTE}"
    ),
)
async def get_drive_smb_advanced_settings(
    request: Request, site_id: str, controller=Depends(resolve_controller)
) -> dict:
    operation = "get Drive SMB advanced settings"
    result = await read(
        request,
        controller,
        manager_attr="file_service_manager",
        method="get_smb_advanced_settings",
        operation=operation,
    )
    return detail(request, "drive_get_smb_advanced_settings", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/rsync-settings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/file-services"],
    summary="Get Drive rsync settings",
    description=(
        "Whether the rsync service is on, whether a dedicated rsync account is set and its username (never its "
        f"password), and whether SSH, which rsync needs, is on. {SITE_NOTE}"
    ),
)
async def get_drive_rsync_settings(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive rsync settings"
    result = await read(
        request, controller, manager_attr="file_service_manager", method="get_rsync_settings", operation=operation
    )
    return detail(request, "drive_get_rsync_settings", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/nfs-connections",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/file-services"],
    summary="List Drive NFS connections",
    description=(
        "NFS clients allowed to mount shared drives, with the shared drives each may mount and the export path "
        f"to mount. {SITE_NOTE}"
    ),
)
async def list_drive_nfs_connections(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "list Drive NFS connections"
    result = await read(
        request, controller, manager_attr="file_service_manager", method="list_nfs_connections", operation=operation
    )
    return items(request, "drive_list_nfs_connections", result, operation=operation)
