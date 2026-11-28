"""Reads and fixed-text errors shared by the session-only console products.

InnerSpace and UniFi Drive are reached through a console login rather than the
stored API token, and they answer failures the same way. Each product describes
itself once as a :class:`ConsoleProduct`. Its REST routes, GraphQL fields and
error answers are then built from the shared :func:`read` and :func:`map_error`.

Core errors for these products are built from fixed text, so their text is
returned. Invalid arguments and a missing resource get fixed text of their own:
the rejected value is never echoed. Anything unexpected is logged by class and
answered with fixed text.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import ValidationError
from unifi_core.exceptions import (
    UniFiError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.operation_gate import BUSY_RETRY_AFTER_SECONDS, ControllerBusyError

from unifi_api.services.managers import ControllerInitializationFailed
from unifi_api.services.operation_gate import RequestAlreadyFinished


class ConsoleProductAPIError(Exception):
    """A mapped console product failure: HTTP status, stable kind and fixed message.

    Each product subclasses it with its own ``product`` key, which prefixes
    every kind it answers with.
    """

    product: ClassVar[str]

    def __init__(self, status: int, kind: str, message: str, *, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message
        self.retry_after = retry_after

    @property
    def graphql_code(self) -> str:
        product = self.product
        return {
            f"invalid_{product}_request": "BAD_REQUEST",
            f"{product}_not_found": "NOT_FOUND",
            f"{product}_forbidden": "UPSTREAM_FORBIDDEN",
            f"{product}_rate_limited": "RATE_LIMITED",
            f"{product}_upstream_error": "UPSTREAM_ERROR",
            f"{product}_unavailable": "UPSTREAM_ERROR",
        }.get(self.kind, "INTERNAL")


@dataclass(frozen=True)
class ConsoleProduct:
    """One console product: its error class, the names its messages use, and any product-only answer.

    ``unavailable`` says whether a failure means the product's application is
    restarting or busy. That failure is answered 503 with ``Retry-After``.
    """

    error: type[ConsoleProductAPIError]
    label: str
    log_name: str
    unavailable: Callable[[BaseException], bool] | None = None

    @property
    def key(self) -> str:
        return self.error.product


def _failed(operation: str, exc: BaseException) -> str:
    """``Failed to <operation>: <fixed text>``, naming one failed action.

    Text that already starts with the operation names it once. The factory's
    own failure text is a whole ``Failed to <step>: <reason>`` sentence (a
    stored controller without a login, say), so only its reason follows, or
    fixed text when it gives none.
    """
    text = str(exc)
    if text.startswith(f"{operation}:"):
        return f"Failed to {text}"
    if isinstance(exc, ControllerInitializationFailed) and text.startswith("Failed to "):
        _step, _separator, reason = text.partition(": ")
        text = reason or "the controller connection did not initialize."
    return f"Failed to {operation}: {text}"


def map_error(product: ConsoleProduct, exc: BaseException, operation: str) -> BaseException:
    """Map a failure to a status and fixed text. ``operation`` is a fixed label, never caller input.

    A refusal at the operation gate, and a read started after its request
    ended, are returned unchanged, so they get the answer they get for the
    other products.
    """
    if isinstance(exc, (ConsoleProductAPIError, ControllerBusyError, RequestAlreadyFinished)):
        return exc
    error, key = product.error, product.key
    log = logging.getLogger(f"unifi-api.{key}")
    if not isinstance(exc, (ValidationError, UniFiError, ConnectionError)):
        log.error("%s %s failed (%s)", product.log_name, operation, type(exc).__name__)
        return error(500, f"{key}_internal_error", f"Failed to {operation}: unexpected error.")
    log.warning("%s %s failed (%s)", product.log_name, operation, type(exc).__name__)
    if isinstance(exc, (ValidationError, UniFiValidationError)):
        return error(422, f"invalid_{key}_request", f"Failed to {operation}: invalid arguments.")
    if isinstance(exc, UniFiNotFoundError):
        return error(404, f"{key}_not_found", f"Failed to {operation}: not found.")
    if isinstance(exc, UniFiPermissionError):
        return error(403, f"{key}_forbidden", _failed(operation, exc))
    if isinstance(exc, UniFiRateLimitError):
        return error(429, f"{key}_rate_limited", _failed(operation, exc))
    if product.unavailable is not None and product.unavailable(exc):
        return error(503, f"{key}_unavailable", _failed(operation, exc), retry_after=BUSY_RETRY_AFTER_SECONDS)
    if isinstance(exc, (UniFiError, ControllerInitializationFailed)):
        # Connection, refused login, product not installed or not running, other HTTP or malformed:
        # fixed core text. The factory's text is fixed too and names no address or credential.
        return error(502, f"{key}_upstream_error", _failed(operation, exc))
    return error(502, f"{key}_upstream_error", f"Failed to {operation}: could not connect to {product.label}.")


async def read(
    product: ConsoleProduct,
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
    """Call one manager method of the product; every failure becomes the product's error."""
    try:
        async with sessionmaker() as session:
            manager = await factory.get_domain_manager(session, controller_id, product.key, manager_attr)
        return await getattr(manager, method)(*args, **(kwargs or {}))
    except Exception as exc:
        raise map_error(product, exc, operation) from None
