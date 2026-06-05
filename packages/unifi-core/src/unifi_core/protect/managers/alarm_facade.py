"""Version-agnostic alarm-rule façade.

Presents a single capability — alarm rules — over the two UniFi alarm APIs.
Prefers the UniFi-OS Alarm Manager (``/api/v2/alarms``) when it actually serves
rules, and falls back to the legacy automations API when v2 is empty or
unavailable on this console (e.g. Protect not yet migrated to v2, or the request
is rejected). Either way the result is the one canonical AlarmRule shape. Callers
never see which backend served the request; the tool/GraphQL layer surfaces the
``complete`` flag via standard MCP ``_meta`` when the legacy backend is used.
Transient/server errors (5xx) are not masked — they propagate.
"""

from __future__ import annotations

from typing import Any

from uiprotect.exceptions import BadRequest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_manager import AlarmManager
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError, AlarmManagerService
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.alarm_rules import alarm_rule_from_legacy


class AlarmRulesFacade:
    """Selects the best available alarm backend and returns canonical rules."""

    def __init__(self, service_manager: AlarmManagerService, legacy_manager: AlarmManager):
        self._service = service_manager
        self._legacy = legacy_manager

    @classmethod
    def from_connection(cls, connection_manager: ProtectConnectionManager) -> "AlarmRulesFacade":
        return cls(AlarmManagerService(connection_manager), AlarmManager(connection_manager))

    async def list_rules(self) -> tuple[list[dict[str, Any]], bool]:
        """Return ``(rules, complete)``.

        Prefer the v2 Alarm Manager, but fall back to the legacy automations API
        whenever v2 cannot serve the rules on this console — that is, when it
        returns an empty list (endpoint present but unpopulated, e.g. Protect not
        yet migrated to ``/api/v2/alarms``) or rejects the request (any 4xx,
        incl. permission and global-alarm-manager mode). ``complete`` is True
        only when v2 actually served the rules.

        Transient/server failures (5xx, timeouts -> ``NvrError``) are NOT masked:
        they propagate so a real v2 outage is never silently hidden behind legacy.
        """
        try:
            rules = await self._service.list_rules()
        except (AlarmManagerPermissionError, BadRequest):
            rules = None
        if rules:
            return rules, True
        raw = await self._legacy.list_rules()
        return [alarm_rule_from_legacy(rule).model_dump(exclude_none=True) for rule in raw], False

    async def get_rule(self, rule_id: str) -> tuple[dict[str, Any], bool]:
        """Return ``(rule, complete)`` for one rule by id.

        Fall back to the legacy automations API when v2 does not have the rule
        (empty / not-yet-migrated -> not found) or rejects the request (any 4xx,
        incl. permission). Transient/server failures (``NvrError``) propagate
        rather than being masked by legacy.
        """
        try:
            return await self._service.get_rule(rule_id), True
        except (AlarmManagerPermissionError, BadRequest, UniFiNotFoundError):
            raw = await self._legacy.get_rule(rule_id)
            return alarm_rule_from_legacy(raw).model_dump(exclude_none=True), False
