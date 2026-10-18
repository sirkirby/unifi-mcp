"""Connection failures that keep their category and HTTP status but carry only fixed text.

A connection manager that fails to initialize records one of these instead of
the original exception, whose message can quote controller responses. Every
class is a ``ConnectionError`` and a ``UniFiConnectionError``, so existing
handlers keep working, and the
authentication, permission and timeout variants also classify as such
(``unifi_core.support_bundle.classify_error``), so evidence reports
``auth_failed``, ``permission_denied`` or ``timeout`` rather than
``unavailable``.
"""

from __future__ import annotations

from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError, UniFiPermissionError, http_status
from unifi_core.support_bundle import ErrorCategory, classify_error


class ControllerConnectionFailed(UniFiConnectionError, ConnectionError):
    """Connecting to the controller failed; ``status`` is the HTTP status, when known."""

    #: Normalized failure category, safe to log.
    category = "connection"
    status: int | None = None


class ControllerAuthFailed(ControllerConnectionFailed, UniFiAuthError):
    """The controller rejected the credentials."""

    category = "authentication"


class ControllerPermissionDenied(ControllerConnectionFailed, UniFiPermissionError):
    """The credentials lack permission for what the connection needs."""

    category = "permission"


class ControllerConnectTimeout(ControllerConnectionFailed, TimeoutError):
    """Connecting to the controller timed out."""

    category = "timeout"


def _valid(status: object) -> int | None:
    return status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else None


def connection_failure(
    message: str,
    error: BaseException,
    *,
    status: int | None = None,
    category: ErrorCategory | None = None,
) -> ControllerConnectionFailed:
    """A fixed-text failure carrying ``error``'s category and status, never its message.

    ``status`` and ``category`` override what is read from ``error`` when the
    caller knows them more precisely (uiprotect folds the status into the
    message; aiounifi reports an unanswerable MFA challenge as a plain
    ``RequestError``).
    """
    try:
        classified_category, classified, _ = classify_error(error)
    except Exception:
        classified_category, classified = ErrorCategory.UNKNOWN, None
    category = category or classified_category
    status = _valid(status) or _valid(classified)
    if status is None:
        try:
            status = _valid(http_status(error))
        except Exception:
            status = None
    if status == 401 or (category is ErrorCategory.AUTHENTICATION and status != 403):
        cls: type[ControllerConnectionFailed] = ControllerAuthFailed
    elif status == 403 or category is ErrorCategory.PERMISSION:
        cls = ControllerPermissionDenied
    elif category is ErrorCategory.TIMEOUT:
        cls = ControllerConnectTimeout
    else:
        cls = ControllerConnectionFailed
    failure = cls(message)
    failure.status = status
    return failure
