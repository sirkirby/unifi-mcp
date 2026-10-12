"""Policy management for UniFi Access.

Provides methods to query and manage access policies and schedules
via the Access controller API.

All methods use the proxy session path since policy management is
not exposed by the py-unifi-access API client.

Proxy paths discovered via browser inspection:
- ``access_policies?expand[]=schedule`` -- policies with schedule data
- ``access_policies/{id}?expand[]=schedule`` -- single policy
- ``schedules?expand[]=week_schedule`` -- schedules with weekly detail
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from unifi_core.access.managers.connection_manager import AccessConnectionManager, reconnects_on_demand
from unifi_core.exceptions import UniFiConnectionError

logger = logging.getLogger(__name__)


@reconnects_on_demand
class PolicyManager:
    """Reads and mutates access policy data from the Access controller."""

    def __init__(self, connection_manager: AccessConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Read-only methods
    # ------------------------------------------------------------------

    async def list_policies(self) -> List[Dict[str, Any]]:
        """Return all access policies as summary dicts."""
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for list_policies")
        try:
            data = await self._cm.proxy_request("GET", "access_policies?expand[]=schedule")
            return self._cm.extract_data(data)
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to list policies: %s", e, exc_info=True)
            raise

    async def get_policy(self, policy_id: str) -> Dict[str, Any]:
        """Return detailed information for a single access policy.

        The single-policy endpoint uses the **singular** path
        ``access_policy/{id}`` (not ``access_policies/{id}``).
        """
        if not policy_id:
            raise ValueError("policy_id is required")
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for get_policy")
        try:
            data = await self._cm.proxy_request("GET", f"access_policy/{policy_id}")
            return self._cm.extract_data(data)
        except (UniFiConnectionError, ValueError):
            raise
        except Exception as e:
            logger.error("Failed to get policy %s: %s", policy_id, e, exc_info=True)
            raise

    async def list_schedules(self) -> List[Dict[str, Any]]:
        """Return all access schedules."""
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for list_schedules")
        try:
            data = await self._cm.proxy_request("GET", "schedules?expand[]=week_schedule")
            return self._cm.extract_data(data)
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to list schedules: %s", e, exc_info=True)
            raise

    # ------------------------------------------------------------------
    # Mutation methods (preview/confirm pattern)
    # ------------------------------------------------------------------

    async def update_policy(self, policy_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Preview a policy update. Returns preview data for confirmation.

        Parameters
        ----------
        policy_id:
            UUID of the policy to update.
        changes:
            Dict of fields to update (e.g., name, doors, schedule_id).
        """
        if not policy_id:
            raise ValueError("policy_id is required")
        if not changes:
            raise ValueError("changes dict must not be empty")

        current = await self.get_policy(policy_id)
        return {
            "policy_id": policy_id,
            "policy_name": current.get("name"),
            "current_state": {k: current.get(k) for k in changes},
            "proposed_changes": changes,
        }

    async def apply_update_policy(self, policy_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the policy update on the controller."""
        if not self._cm.has_proxy:
            raise self._cm.unavailable_error("No proxy session available for update_policy")
        try:
            await self._cm.proxy_request("PUT", f"access_policy/{policy_id}", json=changes)
            return {
                "policy_id": policy_id,
                "action": "update",
                "result": "success",
                "updated_fields": list(changes.keys()),
            }
        except UniFiConnectionError:
            raise
        except Exception as e:
            logger.error("Failed to update policy %s: %s", policy_id, e, exc_info=True)
            raise
