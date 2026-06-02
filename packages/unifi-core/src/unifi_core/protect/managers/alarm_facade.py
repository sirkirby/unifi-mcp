"""Version-agnostic alarm-rule façade.

Presents a single capability — alarm rules — over the two UniFi alarm APIs.
Prefers the UniFi-OS Alarm Manager (complete, incl. AI-powered alarms) when the
credential allows it, and transparently falls back to the legacy automations API
otherwise. Either way the result is the one canonical AlarmRuleV2 shape. Callers
never see which backend served the request; the tool/GraphQL layer surfaces the
``complete`` flag via standard MCP ``_meta`` when the limited backend is used.
"""

from __future__ import annotations

from typing import Any

from unifi_core.protect.managers.alarm_manager import AlarmManager
from unifi_core.protect.managers.alarm_v2_manager import AlarmV2Manager, AlarmV2PermissionError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models.alarm_v2 import alarm_rule_from_legacy


class AlarmRulesFacade:
    """Selects the best available alarm backend and returns canonical rules."""

    def __init__(self, v2_manager: AlarmV2Manager, legacy_manager: AlarmManager):
        self._v2 = v2_manager
        self._legacy = legacy_manager

    @classmethod
    def from_connection(cls, connection_manager: ProtectConnectionManager) -> "AlarmRulesFacade":
        return cls(AlarmV2Manager(connection_manager), AlarmManager(connection_manager))

    async def list_rules(self) -> tuple[list[dict[str, Any]], bool]:
        """Return ``(rules, complete)``. ``complete`` is False on the legacy fallback."""
        try:
            return await self._v2.list_rules(), True
        except AlarmV2PermissionError:
            raw = await self._legacy.list_rules()
            rules = [alarm_rule_from_legacy(rule).model_dump(exclude_none=True) for rule in raw]
            return rules, False

    async def get_rule(self, rule_id: str) -> tuple[dict[str, Any], bool]:
        """Return ``(rule, complete)`` for one rule by id."""
        try:
            return await self._v2.get_rule(rule_id), True
        except AlarmV2PermissionError:
            raw = await self._legacy.get_rule(rule_id)
            return alarm_rule_from_legacy(raw).model_dump(exclude_none=True), False
