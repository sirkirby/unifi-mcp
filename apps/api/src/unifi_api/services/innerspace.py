"""InnerSpace reads for the REST and GraphQL surfaces, and their fixed-text errors.

Both surfaces call :func:`read_innerspace`, so they reach the same core manager
method with the same arguments and map a failure the same way. The action
endpoint keeps its generic contract and audits the exception class instead.

Core InnerSpace errors are built from fixed text (see the InnerSpace session
isolation rules), so their text is returned. Invalid arguments and a missing
resource get fixed text of their own: the rejected value is never echoed.
Anything unexpected is logged by class and answered with fixed text.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, ValidationError
from unifi_core.exceptions import (
    UniFiError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.innerspace.managers.connection_manager import InnerSpaceHttpError
from unifi_core.innerspace.models.reads import InnerSpaceListInput
from unifi_core.operation_gate import BUSY_RETRY_AFTER_SECONDS, ControllerBusyError

from unifi_api.services.managers import ControllerInitializationFailed
from unifi_api.services.operation_gate import RequestAlreadyFinished

_log = logging.getLogger("unifi-api.innerspace")

PRODUCT = "innerspace"
DEFAULT_LIMIT: int = InnerSpaceListInput.model_fields["limit"].default
ID_FAMILY = "These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools."


class InnerSpaceAPIError(Exception):
    """A mapped InnerSpace failure: HTTP status, stable kind and fixed message."""

    def __init__(self, status: int, kind: str, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message
        self.retry_after = retry_after

    @property
    def graphql_code(self) -> str:
        return {
            "invalid_innerspace_request": "BAD_REQUEST",
            "innerspace_not_found": "NOT_FOUND",
            "innerspace_forbidden": "UPSTREAM_FORBIDDEN",
            "innerspace_rate_limited": "RATE_LIMITED",
            "innerspace_upstream_error": "UPSTREAM_ERROR",
            "innerspace_unavailable": "UPSTREAM_ERROR",
        }.get(self.kind, "INTERNAL")


def _failed(operation: str, exc: BaseException) -> str:
    """``Failed to <operation>: <fixed text>``, naming the operation once when the text already starts with it."""
    text = str(exc)
    return f"Failed to {text}" if text.startswith(f"{operation}:") else f"Failed to {operation}: {text}"


def map_innerspace_error(exc: BaseException, operation: str) -> BaseException:
    """Map a failure to a status and fixed text. ``operation`` is a fixed label, never caller input.

    A refusal at the operation gate, and a read started after its request
    ended, are returned unchanged, so they get the answer they get for the
    other products.
    """
    if isinstance(exc, (InnerSpaceAPIError, ControllerBusyError, RequestAlreadyFinished)):
        return exc
    if not isinstance(exc, (ValidationError, UniFiError, ControllerInitializationFailed)):
        _log.error("InnerSpace %s failed (%s)", operation, type(exc).__name__)
        return InnerSpaceAPIError(500, "innerspace_internal_error", f"Failed to {operation}: unexpected error.")
    _log.warning("InnerSpace %s failed (%s)", operation, type(exc).__name__)
    if isinstance(exc, (ValidationError, UniFiValidationError)):
        return InnerSpaceAPIError(422, "invalid_innerspace_request", f"Failed to {operation}: invalid arguments.")
    if isinstance(exc, UniFiNotFoundError):
        return InnerSpaceAPIError(404, "innerspace_not_found", f"Failed to {operation}: not found.")
    if isinstance(exc, UniFiPermissionError):
        return InnerSpaceAPIError(403, "innerspace_forbidden", _failed(operation, exc))
    if isinstance(exc, UniFiRateLimitError):
        return InnerSpaceAPIError(429, "innerspace_rate_limited", _failed(operation, exc))
    if isinstance(exc, InnerSpaceHttpError) and exc.status == 503:
        # The InnerSpace application is restarting or busy: retryable, like a Network 503.
        return InnerSpaceAPIError(
            503, "innerspace_unavailable", _failed(operation, exc), retry_after=BUSY_RETRY_AFTER_SECONDS
        )
    # Connection, not installed or not running, HTTP, malformed, refused login.
    return InnerSpaceAPIError(502, "innerspace_upstream_error", _failed(operation, exc))


def page_with_limit(page: Any, limit: int) -> dict[str, Any]:
    """A wall or placed-device page as a dict, with the limit it was cut at."""
    data = page.model_dump() if isinstance(page, BaseModel) else dict(page)
    return {**data, "limit": limit}


async def read_innerspace(
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
    """Call one InnerSpace manager method; every failure becomes an :class:`InnerSpaceAPIError`."""
    try:
        async with sessionmaker() as session:
            manager = await factory.get_domain_manager(session, controller_id, PRODUCT, manager_attr)
        return await getattr(manager, method)(*args, **(kwargs or {}))
    except Exception as exc:
        raise map_innerspace_error(exc, operation) from None
