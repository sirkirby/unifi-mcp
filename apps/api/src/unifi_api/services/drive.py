"""UniFi Drive reads for the REST and GraphQL surfaces, and their fixed-text errors.

Both read surfaces call :func:`read_drive`, so they reach the same core manager
method with the same arguments and map a failure the same way. The action
endpoint keeps its generic contract and audits the exception class instead; its
route answers a Drive write stopped before it was sent, or sent without an
answer, with ``mutation_applied`` false or null, as the Drive MCP server does.

Core Drive errors are built from fixed text, the request path, the HTTP status
and a length-capped upstream message with the NAS address removed, so their
text is returned. Invalid arguments and a missing resource get fixed text of
their own: the rejected value is never echoed. Anything unexpected is logged by
class and answered with fixed text.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from unifi_core.exceptions import (
    UniFiError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.operation_gate import ControllerBusyError

from unifi_api.services.managers import ControllerInitializationFailed
from unifi_api.services.operation_gate import RequestAlreadyFinished

_log = logging.getLogger("unifi-api.drive")

PRODUCT = "drive"
ID_FAMILY = "These IDs are scoped to the UniFi Drive tool family — do not pass them to other products' tools."


class DriveAPIError(Exception):
    """A mapped Drive read failure: HTTP status, stable kind and fixed message."""

    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message

    @property
    def graphql_code(self) -> str:
        return {
            "invalid_drive_request": "BAD_REQUEST",
            "drive_not_found": "NOT_FOUND",
            "drive_forbidden": "UPSTREAM_FORBIDDEN",
            "drive_rate_limited": "RATE_LIMITED",
            "drive_upstream_error": "UPSTREAM_ERROR",
        }.get(self.kind, "INTERNAL")


def _failed(operation: str, exc: BaseException) -> str:
    """``Failed to <operation>: <fixed text>``, naming one failed action.

    As for InnerSpace, text that already starts with the operation names it
    once. The factory's own failure text is a whole ``Failed to <step>: <reason>``
    sentence (a stored controller without a login), so only its reason follows,
    or fixed text when it gives none.
    """
    text = str(exc)
    if text.startswith(f"{operation}:"):
        return f"Failed to {text}"
    if isinstance(exc, ControllerInitializationFailed) and text.startswith("Failed to "):
        _step, _separator, reason = text.partition(": ")
        text = reason or "the controller connection did not initialize."
    return f"Failed to {operation}: {text}"


def map_drive_error(exc: BaseException, operation: str) -> BaseException:
    """Map a failure to a status and fixed text. ``operation`` is a fixed label, never caller input.

    A refusal at the operation gate, and a read started after its request
    ended, are returned unchanged, so they get the answer they get for the
    other products.
    """
    if isinstance(exc, (DriveAPIError, ControllerBusyError, RequestAlreadyFinished)):
        return exc
    if not isinstance(exc, (ValidationError, UniFiError, ConnectionError)):
        _log.error("Drive %s failed (%s)", operation, type(exc).__name__)
        return DriveAPIError(500, "drive_internal_error", f"Failed to {operation}: unexpected error.")
    _log.warning("Drive %s failed (%s)", operation, type(exc).__name__)
    if isinstance(exc, (ValidationError, UniFiValidationError)):
        return DriveAPIError(422, "invalid_drive_request", f"Failed to {operation}: invalid arguments.")
    if isinstance(exc, UniFiNotFoundError):
        return DriveAPIError(404, "drive_not_found", f"Failed to {operation}: not found.")
    if isinstance(exc, UniFiPermissionError):
        return DriveAPIError(403, "drive_forbidden", _failed(operation, exc))
    if isinstance(exc, UniFiRateLimitError):
        return DriveAPIError(429, "drive_rate_limited", _failed(operation, exc))
    if isinstance(exc, UniFiError):
        # Connection, rejected login, Drive not installed, other HTTP or malformed: fixed core text.
        return DriveAPIError(502, "drive_upstream_error", _failed(operation, exc))
    if isinstance(exc, ControllerInitializationFailed):
        # The factory's text is fixed and names no address or credential.
        return DriveAPIError(502, "drive_upstream_error", _failed(operation, exc))
    return DriveAPIError(502, "drive_upstream_error", f"Failed to {operation}: could not connect to UniFi Drive.")


async def read_drive(
    *,
    sessionmaker: Any,
    factory: Any,
    controller_id: str,
    manager_attr: str,
    method: str,
    operation: str,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
) -> Any:
    """Call one Drive manager method; every failure becomes a :class:`DriveAPIError`."""
    try:
        async with sessionmaker() as session:
            manager = await factory.get_domain_manager(session, controller_id, PRODUCT, manager_attr)
        return await getattr(manager, method)(*args, **(kwargs or {}))
    except Exception as exc:
        raise map_drive_error(exc, operation) from None


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
