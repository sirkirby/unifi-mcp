"""Manager for UniFi OS Alarm Manager v2 (``/api/v2/alarms/``).

Reads the modern UniFi-OS alarm surface via ``uiprotect``'s ``api_request`` with
an ``api_path`` override (lib-native; no bespoke client). This is the AI-capable
Alarm Manager, distinct from the legacy Protect automations in ``alarm_manager``.

**Requires a SuperAdmin credential.** A Protect-scoped account receives 403
Forbidden, which is surfaced as :class:`AlarmV2PermissionError` carrying
actionable guidance so callers (and agents) can self-diagnose.
"""

import logging
from typing import Any, Dict, List

from uiprotect.exceptions import NotAuthorized

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.alarm_v2 import alarm_rule_v2_from_controller

logger = logging.getLogger(__name__)

_API_PATH = "/api/v2/alarms/"
_PERMISSION_HINT = (
    "UniFi OS Alarm Manager (v2) is forbidden for the configured account. This API "
    "requires a SuperAdmin credential. Grant the account SuperAdmin on the console "
    "hosting Protect, or configure a dedicated SuperAdmin service account."
)


class AlarmV2PermissionError(PermissionError):
    """Raised when the configured account lacks SuperAdmin access to /api/v2/alarms/."""


class AlarmV2Manager:
    """Reads UniFi OS Alarm Manager v2 rules, profiles, and activity."""

    def __init__(self, connection_manager: ProtectConnectionManager):
        self._cm = connection_manager

    async def _api_get(self, url: str) -> Any:
        try:
            return await self._cm.client.api_request(url, method="get", api_path=_API_PATH)
        except NotAuthorized as exc:
            logger.warning("Alarm Manager v2 access forbidden for %s: %s", url, exc)
            raise AlarmV2PermissionError(_PERMISSION_HINT) from exc

    async def list_rules(self) -> List[Dict[str, Any]]:
        """Return normalized v2 alarm rules (incl. AI-powered alarms)."""
        data = await self._api_get("protect")
        if not isinstance(data, list):
            logger.warning("Unexpected /api/v2/alarms/protect shape: %r", type(data))
            return []
        return [
            alarm_rule_v2_from_controller(rule).model_dump(exclude_none=True) for rule in data if isinstance(rule, dict)
        ]

    async def get_rule(self, rule_id: str) -> Dict[str, Any]:
        """Return one normalized v2 alarm rule by id."""
        if not rule_id:
            raise ValueError("rule_id is required")
        for rule in await self.list_rules():
            if rule.get("id") == rule_id:
                return rule
        raise UniFiNotFoundError("alarm rule (v2)", rule_id)

    async def list_profiles(self) -> List[Dict[str, Any]]:
        """Return UniFi OS alarm arm profiles (raw; empty when none configured)."""
        data = await self._api_get("profiles")
        return data if isinstance(data, list) else []
