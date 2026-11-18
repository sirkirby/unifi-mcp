"""GET /v1/sites/{site_id}/innerspace/status — whether InnerSpace is installed and running."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.innerspace._common import detail, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/innerspace/status",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["innerspace/status"],
    summary="Get InnerSpace status",
    description=(
        "Whether the InnerSpace application is installed and running on the UniFi OS console, with its version. "
        "The path site_id is ignored. Read-only, through the console session."
    ),
)
async def get_innerspace_status(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get InnerSpace status"
    result = await read(request, controller, manager_attr="system_manager", method="get_status", operation=operation)
    return detail(request, "innerspace_get_status", result, operation=operation)
