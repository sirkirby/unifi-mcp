"""UniFi Drive throughput, fan profile and per-disk activity.

- ``GET /sites/{site_id}/drive/network-throughput`` → ``drive_get_network_throughput``
- ``GET /sites/{site_id}/drive/fan-profile`` → ``drive_get_fan_profile``
- ``GET /sites/{site_id}/drive/disk-stats`` → ``drive_get_disk_stats``
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from unifi_core.drive.managers.performance_manager import MAX_DISK_STATS_HOURS

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import resolve_controller
from unifi_api.routes.resources.drive._common import SITE_NOTE, detail, read
from unifi_api.services.drive import disk_stats_view

router = APIRouter()


@router.get(
    "/sites/{site_id}/drive/network-throughput",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/performance"],
    summary="Get Drive network throughput",
    description=f"The NAS's network throughput right now: data received and sent, in KB/s. {SITE_NOTE}",
)
async def get_drive_network_throughput(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive network throughput"
    result = await read(
        request, controller, manager_attr="performance_manager", method="get_network_throughput", operation=operation
    )
    return detail(request, "drive_get_network_throughput", result, operation=operation)


@router.get(
    "/sites/{site_id}/drive/fan-profile",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/performance"],
    summary="Get Drive fan profile",
    description=(
        "The NAS's fan mode and the modes it offers, with the names the Drive web app shows (Cooling, Balanced, "
        f"Quiet). {SITE_NOTE}"
    ),
)
async def get_drive_fan_profile(request: Request, site_id: str, controller=Depends(resolve_controller)) -> dict:
    operation = "get Drive fan profile"
    result = await read(
        request, controller, manager_attr="performance_manager", method="get_fan_profile", operation=operation
    )
    return detail(request, "drive_get_fan_profile", result, operation=operation)


# The hours bounds are stated in the schema only: the core manager validates them, so a bad value
# gets Drive's fixed-text 422 rather than the generic request-validation answer.
@router.get(
    "/sites/{site_id}/drive/disk-stats",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["drive/performance"],
    summary="Get Drive disk stats",
    description=(
        "Each disk's temperature, read and write throughput (KB/s) and bad sector count over the last hours, "
        "summarized per disk. Buckets are 15 minutes under 7 days, 1 hour under 30 days, 6 hours beyond. "
        f"Per-bucket samples only with include_samples; they are large over long windows. {SITE_NOTE}"
    ),
)
async def get_drive_disk_stats(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    hours: int = Query(
        24,
        description=f"How far back to read, in hours, 1 to {MAX_DISK_STATS_HOURS} (90 days)",
        json_schema_extra={"minimum": 1, "maximum": MAX_DISK_STATS_HOURS},
    ),
    include_samples: bool = Query(
        False,
        description=(
            "Also return every bucket's values for each disk: about 12 KB per disk per day at 15-minute buckets, "
            "up to about 1 MB for a full NAS over a week or more"
        ),
    ),
) -> dict:
    operation = "get Drive disk stats"
    result = await read(
        request,
        controller,
        manager_attr="performance_manager",
        method="get_disk_stats",
        operation=operation,
        hours=hours,
    )
    return detail(
        request, "drive_get_disk_stats", disk_stats_view(result, include_samples=include_samples), operation=operation
    )
