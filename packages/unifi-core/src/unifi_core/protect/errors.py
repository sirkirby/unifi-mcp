"""Fixed-text translation of uiprotect failures; NVR text never leaves Core.

uiprotect folds the HTTP status into its messages ("... - Status: 403 -
Reason: ...") and raises ``NotAuthorized`` for both 401 and 403, so the
status is read from the message, and only the status and the error class
travel on.
"""

from __future__ import annotations

import re

from uiprotect.exceptions import BadRequest, NotAuthorized, NvrError, UnifiProtectError

from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
)

_NVR_STATUS = re.compile(r"\bStatus: (\d{3})\b")


def nvr_status(error: BaseException) -> int | None:
    """The HTTP status a uiprotect error reports in its message, if any."""
    if not isinstance(error, UnifiProtectError):
        return None
    match = _NVR_STATUS.search(str(error))
    return int(match.group(1)) if match else None


def safe_protect_error(operation: str, error: BaseException) -> Exception:
    """A fixed-text error for a failed NVR read, keeping its class and HTTP status."""
    cause = error.__cause__
    if isinstance(error, TimeoutError) or isinstance(cause, TimeoutError):
        translated: Exception = TimeoutError(f"{operation} timed out")
        translated.status = None  # type: ignore[attr-defined]
        return translated
    if isinstance(error, NvrError) and isinstance(cause, ValueError):
        return UniFiMalformedResponseError(f"Unexpected response shape from {operation}")
    status = nvr_status(error)
    # NotAuthorized covers 401 and 403 (and subclasses PermissionError), so the status decides.
    if isinstance(error, NotAuthorized):
        cls: type[Exception] = UniFiPermissionError if status == 403 else UniFiAuthError
    elif status == 429:
        cls = UniFiRateLimitError
    elif isinstance(error, BadRequest):
        cls = UniFiOperationError
    elif isinstance(error, (NvrError, OSError)):
        cls = UniFiConnectionError
    else:
        cls = UniFiOperationError
    detail = f"{type(error).__name__}, HTTP {status}" if status is not None else type(error).__name__
    translated = cls(f"{operation} failed ({detail}).")
    translated.status = status  # type: ignore[attr-defined]
    return translated
