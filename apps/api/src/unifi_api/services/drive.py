"""UniFi Drive reads for the REST and GraphQL surfaces, and their fixed-text errors.

Drive is a console product (:mod:`unifi_api.services.console_product`): both
read surfaces reach the same core manager method with the same arguments
through its shared read, and map a failure the same way. The action
endpoint keeps its generic contract and audits the exception class instead; its
route answers a Drive write stopped before it was sent, or sent without an
answer, with ``mutation_applied`` false or null, as the Drive MCP server does.

Core Drive errors are built from fixed text, the request path, the HTTP status
and a length-capped upstream message with the NAS address removed, so their
text is returned. Invalid arguments and a missing resource get fixed text of
their own: the rejected value is never echoed. Anything unexpected is logged by
class and answered with fixed text.

This module names Drive's errors and holds the shaping only Drive's reads need.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from unifi_api.services.console_product import ConsoleProduct, ConsoleProductAPIError, map_error

PRODUCT = "drive"
ID_FAMILY = "These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools."


class DriveAPIError(ConsoleProductAPIError):
    """A mapped Drive read failure: HTTP status, stable kind and fixed message."""

    product = PRODUCT


DRIVE = ConsoleProduct(error=DriveAPIError, label="UniFi Drive", log_name="Drive")


def map_drive_error(exc: BaseException, operation: str) -> BaseException:
    """Map a Drive failure to a status and fixed text, as for every console product."""
    return map_error(DRIVE, exc, operation)


def disk_stats_view(stats: Any, *, include_samples: bool = False) -> dict[str, Any]:
    """Disk stats as every surface answers them: each disk's per-bucket samples only when asked for.

    The samples run to about 12 KB per disk per day at 15-minute buckets, so the
    summary is the default, as the Drive MCP tool returns it.
    """
    data = stats.model_dump()
    if not include_samples:
        for disk in data["disks"]:
            disk.pop("samples", None)
    return data


def log_query(operation: str, **filters: Any) -> Any:
    """The core log query from a read surface's filters; an invalid filter maps like any other read failure.

    Unset filters are left out, so the query's own defaults apply.
    """
    from unifi_core.drive.models.logs import DriveLogQuery

    try:
        return DriveLogQuery(**{key: value for key, value in filters.items() if value is not None})
    except ValidationError as exc:
        raise map_drive_error(exc, operation) from None
