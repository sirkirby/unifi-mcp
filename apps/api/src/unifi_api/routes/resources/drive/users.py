"""UniFi Drive users and user groups. Read-only: nothing here invites, changes or removes anyone.

- ``GET /sites/{site_id}/drive/users`` → ``drive_list_users``
- ``GET /sites/{site_id}/drive/groups`` → ``drive_list_groups``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, items, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/users",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/users"],
    summary="List Drive users",
    description=(
        "The NAS's users with username, full name, email, status, access level (owner, admin or user), console "
        f"roles, personal drive and Active Directory flags, and last login. {SITE_NOTE}"
    ),
)
async def list_drive_users(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "list Drive users"
    result = await read(request, controller, manager_attr="user_manager", method="list_users", operation=operation)
    return items(request, "drive_list_users", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/groups",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/users"],
    summary="List Drive user groups",
    description=f"The UniFi OS user groups that shared drive access can be granted to, with id and name. {SITE_NOTE}",
)
async def list_drive_groups(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "list Drive user groups"
    result = await read(request, controller, manager_attr="user_manager", method="list_groups", operation=operation)
    return items(request, "drive_list_groups", result, operation=operation)
