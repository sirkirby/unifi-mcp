"""Fixed-text errors for the cloud account boundary; never render upstream exceptions."""

import logging

from pydantic import ValidationError
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.sitemanager.managers.connection_manager import SiteManagerHttpError, SiteManagerNotConfiguredError

from unifi_api.services.sitemanager_connections import (
    SiteManagerConfigurationError,
    SiteManagerConnectionConflict,
    SiteManagerConnectionNotFound,
)

_log = logging.getLogger("unifi-api.sitemanager")


class SiteManagerAPIError(Exception):
    def __init__(self, status: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.message = message

    @property
    def graphql_code(self):
        return {
            "sitemanager_not_configured": "NOT_CONFIGURED",
            "sitemanager_configuration_error": "NOT_CONFIGURED",
            "sitemanager_auth_failed": "UPSTREAM_AUTH_FAILED",
            "sitemanager_permission_denied": "UPSTREAM_FORBIDDEN",
            "sitemanager_resource_not_found": "NOT_FOUND",
            "sitemanager_tool_not_found": "NOT_FOUND",
            "invalid_sitemanager_request": "BAD_REQUEST",
            "sitemanager_target_mismatch": "BAD_REQUEST",
            "sitemanager_rate_limited": "RATE_LIMITED",
            "sitemanager_upstream_error": "UPSTREAM_ERROR",
        }.get(self.kind, "INTERNAL")


def map_error(exc: Exception, operation: str, *, management: bool = False) -> SiteManagerAPIError:
    """Operation is a fixed adapter label, never a caller-supplied value."""
    if isinstance(exc, SiteManagerAPIError):
        return exc
    if isinstance(exc, SiteManagerConnectionConflict):
        status, kind, guidance = (
            409,
            "sitemanager_already_configured",
            "Update or delete the existing cloud connection.",
        )
    elif isinstance(exc, (SiteManagerConnectionNotFound, SiteManagerNotConfiguredError)):
        status = 404 if management else 503
        kind, guidance = "sitemanager_not_configured", "Ask an administrator to configure the API cloud connection."
    elif isinstance(exc, SiteManagerConfigurationError):
        status, kind = 503, "sitemanager_configuration_error"
        guidance = "Ask an administrator to check database encryption and replace the stored cloud key."
    elif isinstance(exc, UniFiAuthError):
        status, kind, guidance = 502, "sitemanager_auth_failed", "Rotate the stored Site Manager cloud key."
    elif isinstance(exc, UniFiPermissionError):
        status, kind = 502, "sitemanager_permission_denied"
        guidance = "Check the cloud account and resource permissions."
    elif isinstance(exc, UniFiNotFoundError) or (isinstance(exc, SiteManagerHttpError) and exc.status == 404):
        status, kind, guidance = 404, "sitemanager_resource_not_found", "Check that the cloud resource still exists."
    elif isinstance(exc, (UniFiValidationError, ValidationError)):
        status = 422 if isinstance(exc, ValidationError) else 400
        kind, guidance = "invalid_sitemanager_request", "Check the Site Manager request fields and types."
    elif isinstance(exc, UniFiRateLimitError):
        status, kind, guidance = 429, "sitemanager_rate_limited", "Wait before retrying the Site Manager request."
    elif isinstance(exc, (UniFiConnectionError, UniFiMalformedResponseError, UniFiOperationError)):
        status, kind, guidance = (
            502,
            "sitemanager_upstream_error",
            "Check network connectivity and Site Manager API access.",
        )
        if (
            isinstance(exc, SiteManagerHttpError)
            and exc.status == 502
            and operation == "query isp metrics from Site Manager"
        ):
            guidance += " Check access to the requested sites."
    else:
        status, kind, guidance = 500, "sitemanager_internal_error", "Ask an administrator to check the API service."
        _log.error("Site Manager %s failed (%s)", operation, type(exc).__name__)
    return SiteManagerAPIError(status, kind, f"Failed to {operation}: {guidance}")
