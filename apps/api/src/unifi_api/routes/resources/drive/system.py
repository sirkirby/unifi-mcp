"""GET /v1/sites/{site_id}/drive/system — identity, firmware and health of the NAS console."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, detail, read

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/system",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/system"],
    summary="Get Drive system info",
    description=(
        "The NAS console's name, model, MAC, UniFi OS firmware and any available update, device state, uptime, "
        f"CPU load and temperature, and memory. {SITE_NOTE}"
    ),
)
async def get_drive_system_info(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive system info"
    result = await read(
        request, controller, manager_attr="system_manager", method="get_system_info", operation=operation
    )
    return detail(request, "drive_get_system_info", result, operation=operation)
