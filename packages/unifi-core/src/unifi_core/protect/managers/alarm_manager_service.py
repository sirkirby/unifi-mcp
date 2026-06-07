"""Manager for UniFi OS Alarm Manager (``/api/v2/alarms/``).

Reads the modern UniFi-OS alarm surface via ``uiprotect``'s ``api_request`` with
an ``api_path`` override (lib-native; no bespoke client). This is the AI-capable
Alarm Manager, distinct from the legacy Protect automations in ``alarm_manager``.

A Protect-scoped account receives 403 Forbidden, surfaced as
:class:`AlarmManagerPermissionError` with actionable guidance. An adequate
(e.g. SuperAdmin) credential is necessary but not sufficient: on a console where
Protect has not migrated to the Alarm Manager, this endpoint returns ``200 []``
even when legacy automations exist, so an empty result here does not mean
"no rules." :class:`~unifi_core.protect.managers.alarm_facade.AlarmRulesFacade`
falls back to the legacy automations API on both 403 and empty/4xx for this reason.
"""

import logging
from typing import Any, Dict, List

from uiprotect.exceptions import NotAuthorized

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.alarm_rules import alarm_rule_from_controller

logger = logging.getLogger(__name__)

_API_PATH = "/api/v2/alarms/"
_PERMISSION_HINT = (
    "UniFi OS Alarm Manager is forbidden for the configured account. This API "
    "requires a SuperAdmin credential. Grant the account SuperAdmin on the console "
    "hosting Protect, or configure a dedicated SuperAdmin service account."
)


class AlarmManagerPermissionError(PermissionError):
    """Raised when the configured account lacks SuperAdmin access to /api/v2/alarms/."""


class AlarmManagerService:
    """Reads UniFi OS Alarm Manager rules, profiles, and activity."""

    def __init__(self, connection_manager: ProtectConnectionManager):
        self._cm = connection_manager

    async def _api_get(self, url: str) -> Any:
        try:
            return await self._cm.client.api_request(url, method="get", api_path=_API_PATH)
        except NotAuthorized as exc:
            logger.warning("Alarm Manager access forbidden for %s: %s", url, exc)
            raise AlarmManagerPermissionError(_PERMISSION_HINT) from exc

    async def _api_request(self, url: str, *, method: str, json: Dict[str, Any] | None = None) -> Any:
        try:
            kwargs: Dict[str, Any] = {"method": method, "api_path": _API_PATH}
            if json is not None:
                kwargs["json"] = json
            return await self._cm.client.api_request(url, **kwargs)
        except NotAuthorized as exc:
            logger.warning("Alarm Manager access forbidden for %s: %s", url, exc)
            raise AlarmManagerPermissionError(_PERMISSION_HINT) from exc

    async def list_rules(self) -> List[Dict[str, Any]]:
        """Return normalized alarm rules (incl. AI-powered alarms)."""
        data = await self.list_rules_raw()
        if not isinstance(data, list):
            logger.warning("Unexpected /api/v2/alarms/protect shape: %r", type(data))
            return []
        return [
            alarm_rule_from_controller(rule).model_dump(exclude_none=True) for rule in data if isinstance(rule, dict)
        ]

    async def list_rules_raw(self) -> List[Dict[str, Any]]:
        """Return raw ``/api/v2/alarms/protect`` rule payloads."""
        data = await self._api_get("protect")
        return data if isinstance(data, list) else []

    async def get_rule(self, rule_id: str) -> Dict[str, Any]:
        """Return one normalized alarm rule by id."""
        raw = await self.get_rule_raw(rule_id)
        return alarm_rule_from_controller(raw).model_dump(exclude_none=True)

    async def get_rule_raw(self, rule_id: str) -> Dict[str, Any]:
        """Return one raw v2 alarm rule by id."""
        if not rule_id:
            raise ValueError("rule_id is required")
        for rule in await self.list_rules_raw():
            if rule.get("id") == rule_id:
                return rule
        raise UniFiNotFoundError("alarm rule", rule_id)

    async def list_profiles(self) -> List[Dict[str, Any]]:
        """Return UniFi OS alarm arm profiles (raw; empty when none configured)."""
        data = await self._api_get("profiles")
        return data if isinstance(data, list) else []

    async def create_rule(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Create an alarm rule via ``POST /api/v2/alarms/protect``."""
        data = await self._api_request("protect", method="post", json=body)
        return data if isinstance(data, dict) else {}

    async def update_rule(self, rule_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Update an alarm rule via ``PATCH /api/v2/alarms/protect/{uuid}``."""
        if not rule_id:
            raise ValueError("rule_id is required")
        data = await self._api_request(f"protect/{rule_id}", method="patch", json=body)
        return data if isinstance(data, dict) else {}

    async def delete_rule(self, rule_id: str) -> Dict[str, Any]:
        """Delete an alarm rule via raw DELETE; v2 returns 204 with no body."""
        if not rule_id:
            raise ValueError("rule_id is required")
        try:
            await self._cm.client.api_request_raw(f"protect/{rule_id}", method="delete", api_path=_API_PATH)
        except NotAuthorized as exc:
            logger.warning("Alarm Manager access forbidden for protect/%s: %s", rule_id, exc)
            raise AlarmManagerPermissionError(_PERMISSION_HINT) from exc
        return {"deleted": True, "rule_id": rule_id}
