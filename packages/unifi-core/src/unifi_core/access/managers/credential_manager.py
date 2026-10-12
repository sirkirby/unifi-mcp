"""Credential management for UniFi Access.

Provides methods to query and manage access credentials (NFC cards, PINs,
mobile credentials) via the Access controller API.

All methods use the proxy session path since credential management is
not exposed by the py-unifi-access API client.

NOTE: Credential endpoints were not directly visible in browser network
traces.  The paths below are best-effort guesses.  Each method includes
graceful error handling that returns an empty result with a clear message
when the endpoint returns 404.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from unifi_core.access.managers.connection_manager import AccessConnectionManager, reconnects_on_demand
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError

logger = logging.getLogger(__name__)


@reconnects_on_demand
class CredentialManager:
    """Reads and mutates credential data from the Access controller."""

    def __init__(self, connection_manager: AccessConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    async def list_credentials(self) -> List[Dict[str, Any]]:
        """Return all credentials as summary dicts.

        Returns an empty list with a warning if the endpoint is not available
        (404), since the exact credential API path has not been confirmed.
        """
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for list_credentials")
        try:
            data = await self._cm.proxy_request("GET", "credentials")
            return self._cm.extract_data(data)
        except UniFiConnectionError as e:
            if "HTTP 404" in str(e):
                logger.warning(
                    "[credentials] Credential endpoint returned 404 — endpoint path may not be correct. "
                    "Returning empty list."
                )
                return []
            raise
        except Exception as e:
            logger.error("Failed to list credentials: %s", e, exc_info=True)
            raise

    async def get_credential(self, credential_id: str) -> Dict[str, Any]:
        """Return detailed information for a single credential.

        Returns an error dict if the endpoint is not available (404).
        """
        if not credential_id:
            raise ValueError("credential_id is required")
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for get_credential")
        try:
            data = await self._cm.proxy_request("GET", f"credentials/{credential_id}")
            return self._cm.extract_data(data)
        except UniFiConnectionError as e:
            if "HTTP 404" in str(e):
                logger.warning(
                    "[credentials] Credential endpoint returned 404 for %s — endpoint path may not be correct.",
                    credential_id,
                )
                raise UniFiNotFoundError(
                    "credential",
                    credential_id,
                    f"Credential not found or endpoint not available: {credential_id}. "
                    "The credential API path has not been confirmed via browser inspection.",
                ) from e
            raise
        except Exception as e:
            logger.error("Failed to get credential %s: %s", credential_id, e, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Mutation methods (preview/confirm pattern)
    # ------------------------------------------------------------------

    async def create_credential(self, credential_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Preview a credential creation. Returns preview data for confirmation.

        Parameters
        ----------
        credential_type:
            Type of credential (e.g., nfc, pin, mobile).
        data:
            Credential payload (user_id, token/pin/etc.).
        """
        if not credential_type:
            raise ValueError("credential_type is required")
        if not data:
            raise ValueError("credential data must not be empty")

        return {
            "credential_type": credential_type,
            "credential_data": data,
            "proposed_changes": {
                "action": "create",
                "type": credential_type,
                **data,
            },
        }

    async def apply_create_credential(self, credential_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the credential creation on the controller."""
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for create_credential")
        try:
            payload = {"type": credential_type, **data}
            result = await self._cm.proxy_request("POST", "credentials", json=payload)
            return {
                "action": "create",
                "credential_type": credential_type,
                "result": "success",
                "data": self._cm.extract_data(result),
            }
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to create credential: %s", e, exc_info=True)
            raise

    async def revoke_credential(self, credential_id: str) -> Dict[str, Any]:
        """Preview a credential revocation. Returns preview data for confirmation."""
        if not credential_id:
            raise ValueError("credential_id is required")

        current = await self.get_credential(credential_id)
        return {
            "credential_id": credential_id,
            "current_state": current,
            "proposed_changes": {
                "action": "revoke",
            },
        }

    async def apply_revoke_credential(self, credential_id: str) -> Dict[str, Any]:
        """Execute the credential revocation on the controller."""
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for revoke_credential")
        try:
            await self._cm.proxy_request("DELETE", f"credentials/{credential_id}")
            return {
                "credential_id": credential_id,
                "action": "revoke",
                "result": "success",
            }
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to revoke credential %s: %s", credential_id, e, exc_info=True)
            raise
