"""Shared exception hierarchy for UniFi MCP servers."""

import re


class UniFiError(Exception):
    """Base exception for all UniFi errors."""


class UniFiAuthError(UniFiError):
    """Authentication failed."""


class UniFiConnectionError(UniFiError):
    """Connection to controller failed."""


class UniFiRateLimitError(UniFiError):
    """Rate limit exceeded."""


class UniFiPermissionError(UniFiError):
    """Insufficient permissions for operation."""


class UniFiNotFoundError(UniFiError):
    """Resource not found on the controller.

    Raised by manager methods when an existence check (typically a fetch by id)
    finds no matching resource. Tool functions catch this and surface a
    standard ``{"success": False, "error": ...}`` MCP response.
    """

    def __init__(self, resource_type: str, identifier: str, message: str | None = None) -> None:
        self.resource_type = resource_type
        self.identifier = identifier
        super().__init__(message or f"{resource_type} '{identifier}' not found")


class UniFiValidationError(UniFiError):
    """Resource exists but the requested mutation is invalid (e.g., conflicting fields)."""


class UniFiOperationError(UniFiError):
    """Manager method completed but the operation reported failure (e.g., controller rejected)."""


_HTTP_STATUS_IN_MESSAGE = re.compile(r"\breceived (\d{3})\b")


def http_status(error: BaseException) -> int | None:
    """Best-effort HTTP status behind a controller error, or ``None``.

    aiounifi folds the status into the message (``"Call <url> received 404 Not
    Found"``) for the statuses it maps, and raises the decoded V2 error body
    (``{"errorCode": 405, ...}``) for the rest; neither carries a status
    attribute.
    """
    for arg in error.args:
        if isinstance(arg, dict) and isinstance(arg.get("errorCode"), int):
            return arg["errorCode"]
    match = _HTTP_STATUS_IN_MESSAGE.search(str(error))
    return int(match.group(1)) if match else None
