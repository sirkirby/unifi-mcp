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
        return DriveAPIError(403, "drive_forbidden", f"Failed to {operation}: {exc}")
    if isinstance(exc, UniFiRateLimitError):
        return DriveAPIError(429, "drive_rate_limited", f"Failed to {operation}: {exc}")
    if isinstance(exc, UniFiError):
        # Connection, rejected login, Drive not installed, other HTTP or malformed: fixed core text.
        return DriveAPIError(502, "drive_upstream_error", f"Failed to {operation}: {exc}")
    # A connection manager that did not initialize; the factory's text names no address.
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
