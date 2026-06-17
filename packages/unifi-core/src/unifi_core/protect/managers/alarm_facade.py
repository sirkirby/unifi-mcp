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

import re
from typing import Any

from uiprotect.exceptions import BadRequest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.merge import deep_merge
from unifi_core.protect.managers.alarm_manager import AlarmManager
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError, AlarmManagerService
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager
from unifi_core.protect.models._validators import require_non_empty_actions
from unifi_core.protect.models.alarm_rules import (
    alarm_rule_from_controller,
    alarm_rule_from_legacy,
    alarm_rule_to_legacy_body,
    alarm_rule_to_v2_body,
)

_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


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

    async def create_rule(self, fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Create a rule on the newest writable backend available."""
        self._require_non_empty_canonical_actions(fields)
        if await self._v2_write_available():
            body = alarm_rule_to_v2_body(fields)
            raw = await self._service.create_rule(body)
            return alarm_rule_from_controller(raw).model_dump(exclude_none=True), True

        body = alarm_rule_to_legacy_body(fields)
        raw = await self._legacy.create_rule(body)
        return alarm_rule_from_legacy(raw).model_dump(exclude_none=True), False

    async def update_rule(self, rule_id: str, fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Update a rule, routing by id family."""
        family = self._id_family(rule_id)
        if "actions" in fields:
            self._require_non_empty_canonical_actions(fields)

        if family == "v2":
            current_raw = await self._service.get_rule_raw(rule_id)
            current = alarm_rule_from_controller(current_raw).model_dump(exclude_none=True)
            merged = self._write_fields(deep_merge(current, fields))
            body = alarm_rule_to_v2_body(merged)
            raw = await self._service.update_rule(rule_id, body)
            return alarm_rule_from_controller(raw).model_dump(exclude_none=True), True

        current_raw = await self._legacy.get_rule(rule_id)
        current = alarm_rule_from_legacy(current_raw).model_dump(exclude_none=True)
        merged = self._write_fields(deep_merge(current, fields))
        body = deep_merge(current_raw, alarm_rule_to_legacy_body(merged))
        raw = await self._legacy.update_rule(rule_id, body)
        return alarm_rule_from_legacy(raw).model_dump(exclude_none=True), False

    async def delete_rule(self, rule_id: str) -> tuple[dict[str, Any], bool]:
        """Delete a rule, routing by id family."""
        family = self._id_family(rule_id)
        if family == "v2":
            return await self._service.delete_rule(rule_id), True
        return await self._legacy.delete_rule(rule_id), False

    async def _v2_write_available(self) -> bool:
        """v2 is the write target only when it actually serves rules here.

        An empty list means the endpoint exists but is not the active rule store
        on this console (e.g. Protect not migrated to ``/api/v2/alarms``), so —
        mirroring the read fallback in :meth:`list_rules` — writes go to legacy
        instead. A 4xx/permission error likewise routes writes to legacy.
        """
        try:
            rules = await self._service.list_rules_raw()
        except (AlarmManagerPermissionError, BadRequest):
            return False
        return bool(rules)

    @staticmethod
    def _id_family(rule_id: str) -> str:
        """Route by id: v2 UUIDs go to the Alarm Manager, everything else to the
        legacy automations API.

        Legacy automation ids are controller-assigned and may carry suffixes
        (e.g. ``_new``), so their shape is not validated here — only a v2 UUID
        routes to v2. The legacy list-filter is the real existence check and
        raises ``UniFiNotFoundError`` when no rule with the id exists.
        """
        if not isinstance(rule_id, str) or not rule_id.strip():
            raise ValueError("Alarm rule id must be a non-empty string")
        return "v2" if _UUID_RE.match(rule_id) else "legacy"

    @staticmethod
    def _require_non_empty_canonical_actions(fields: dict[str, Any]) -> None:
        require_non_empty_actions(fields.get("actions"))

    @staticmethod
    def _write_fields(fields: dict[str, Any]) -> dict[str, Any]:
        allowed = {"title", "enabled", "triggers", "actions", "scope"}
        return {key: value for key, value in fields.items() if key in allowed}
