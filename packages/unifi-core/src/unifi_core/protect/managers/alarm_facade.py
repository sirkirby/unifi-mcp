"""Version-agnostic alarm-rule façade.

Presents a single capability — alarm rules and arm state — over the two UniFi
alarm APIs.
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
    alarm_rule_to_legacy_create_body,
    alarm_rule_to_v2_body,
)
from unifi_core.protect.models.alarms import profile_from_controller

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

    async def list_profiles(self) -> tuple[list[dict[str, Any]], bool]:
        """Return ``(profiles, complete)``.

        Prefer the v2 Alarm Manager profile API, but fall back to the legacy
        arm-profile API whenever v2 cannot serve profiles on this console — that
        is, when it returns an empty list or rejects the request. ``complete`` is
        True only when v2 actually served the profiles.

        Transient/server failures (5xx, timeouts -> ``NvrError``) are NOT masked:
        they propagate so a real v2 outage is never silently hidden behind legacy.
        """
        permission_error: AlarmManagerPermissionError | None = None
        try:
            profiles = await self._service.list_profiles()
        except AlarmManagerPermissionError as exc:
            permission_error = exc
            profiles = None
        except BadRequest:
            profiles = None
        if profiles:
            shaped = []
            for profile in profiles:
                if not isinstance(profile, dict):
                    continue
                item = profile_from_controller(
                    {**profile, "id_family": "alarm_manager_v2", "arm_compatible": False}
                ).model_dump(exclude_none=True)
                shaped.append(item)
            return shaped, True
        raw = await self._legacy.list_arm_profiles()
        if raw:
            return [
                profile_from_controller({**profile, "id_family": "legacy_arm", "arm_compatible": True}).model_dump(
                    exclude_none=True
                )
                for profile in raw
                if isinstance(profile, dict)
            ], False
        if permission_error is not None:
            raise permission_error
        return [], False

    async def get_arm_state(self) -> dict[str, Any]:
        """Read Global profile states, or preserve the legacy local status.

        Any non-disarmed profile makes the aggregate armed. Prefer a breached
        profile, then an unknown state, arming, and armed; ties use profile ID
        so controller ordering cannot change the selected profile. All raw
        states and transition timestamps remain available in ``profiles``.
        """
        profiles, complete = await self.list_profiles()
        if not complete:
            return await self._legacy.get_arm_state()
        if not profiles or any(not (p.get("state") or "").strip() for p in profiles):
            raise ValueError(
                "Cannot determine Global alarm status: a v2 profile state is missing. Retry the status read."
            )

        active = [p for p in profiles if AlarmManager._is_armed_status(p["state"])]
        precedence = {"breached": 0, "arming": 2, "armed": 3}
        selected = min(
            active,
            key=lambda p: (precedence.get(p["state"].lower(), 1), p.get("id") or ""),
            default=None,
        )
        status = selected["state"] if selected else "disarmed"
        transition = selected.get("state_set_at") if selected else None
        return {
            "armed": bool(active),
            "status": status,
            "active_profile_id": selected.get("id") if selected else None,
            "active_profile_name": selected.get("name") if selected else None,
            "armed_at": transition if status.lower() == "armed" else None,
            "will_be_armed_at": None,
            "breach_detected_at": transition if status.lower() == "breached" else None,
            "breach_event_count": None,
            "profiles": profiles,
        }

    # ------------------------------------------------------------------
    # Arm / disarm
    # ------------------------------------------------------------------

    async def preview_arm(self, profile_id: str | None = None) -> dict[str, Any]:
        """Return current + proposed state for an arm preview, v2-first."""
        profiles, complete = await self.list_profiles()
        if not complete:
            return await self._legacy.preview_arm(profile_id)
        target = self._resolve_v2_profile(profiles, profile_id)
        active = self._active_v2_profiles(profiles)
        return {
            "target_profile_id": target["id"],
            "target_profile_name": target.get("name"),
            "current_state": {
                "armed": bool(active),
                "active_profile_id": active[0]["id"] if active else None,
                "status": target.get("state"),
            },
            "proposed_changes": {"armed": True, "active_profile_id": target["id"]},
        }

    async def arm(self, profile_id: str | None = None) -> dict[str, Any]:
        """Arm a profile, verifying the controller actually changed state.

        On a Global-mode console the legacy ``arm/enable`` endpoint returns 204
        without arming anything, so the v2 action is used whenever v2 serves the
        profiles. The profile is re-read afterwards and the call only reports
        success when the controller shows it ``arming`` or ``armed``.
        """
        profiles, complete = await self.list_profiles()
        if not complete:
            return await self._legacy.arm(profile_id)

        target = self._resolve_v2_profile(profiles, profile_id)
        if AlarmManager._is_armed_status(target.get("state")):
            return {
                "armed": True,
                "profile_id": target["id"],
                "profile_name": target.get("name"),
                "state": target.get("state"),
                "state_set_at": target.get("state_set_at"),
                "already_armed": True,
            }

        await self._service.arm_profile(target["id"])
        after = await self._v2_profile_after_action(target["id"])
        if not AlarmManager._is_armed_status(after.get("state")):
            raise ValueError(
                f"The controller accepted the arm request for profile {target.get('name') or target['id']!r} "
                f"but it is still {after.get('state')!r}. Check for open sensors or arm it from the Protect app."
            )
        return {
            "armed": True,
            "profile_id": target["id"],
            "profile_name": target.get("name"),
            "state": after.get("state"),
            "state_set_at": after.get("state_set_at"),
            "activation_delay_s": after.get("activation_delay"),
        }

    async def preview_disarm(self, profile_id: str | None = None) -> dict[str, Any]:
        """Return current state for a disarm preview, v2-first."""
        profiles, complete = await self.list_profiles()
        if not complete:
            return await self._legacy.preview_disarm()
        targets = self._disarm_targets(profiles, profile_id)
        first = targets[0] if targets else None
        return {
            "active_profile_id": first["id"] if first else None,
            "active_profile_name": first.get("name") if first else None,
            "current_state": {
                "armed": bool(targets),
                "status": first.get("state") if first else "disarmed",
                "profiles": [{"id": p["id"], "name": p.get("name"), "state": p.get("state")} for p in targets],
            },
            "proposed_changes": {"armed": False},
        }

    async def disarm(self, profile_id: str | None = None) -> dict[str, Any]:
        """Disarm one profile, or every active profile when ``profile_id`` is omitted.

        Each disarm is verified by re-reading the profile from the controller.
        """
        profiles, complete = await self.list_profiles()
        if not complete:
            return await self._legacy.disarm()

        targets = self._disarm_targets(profiles, profile_id)
        if not targets:
            return {"armed": False, "already_disarmed": True}

        disarmed = []
        for target in targets:
            await self._service.disarm_profile(target["id"])
            after = await self._v2_profile_after_action(target["id"])
            if AlarmManager._is_armed_status(after.get("state")):
                raise ValueError(
                    f"The controller accepted the disarm request for profile "
                    f"{target.get('name') or target['id']!r} but it is still {after.get('state')!r}."
                )
            disarmed.append(
                {
                    "profile_id": target["id"],
                    "profile_name": target.get("name"),
                    "state": after.get("state"),
                    "state_set_at": after.get("state_set_at"),
                }
            )
        return {"armed": False, "profiles": disarmed}

    @staticmethod
    def _active_v2_profiles(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [p for p in profiles if AlarmManager._is_armed_status(p.get("state"))]

    @staticmethod
    def _resolve_v2_profile(profiles: list[dict[str, Any]], profile_id: str | None) -> dict[str, Any]:
        """Match ``profile_id`` against v2 ids or names; require it when ambiguous."""
        if not profiles:
            raise ValueError("No arm profiles found. Configure Alarm Manager in the Protect UI first.")
        if profile_id:
            wanted = profile_id.strip()
            for p in profiles:
                if p.get("id") == wanted:
                    return p
            by_name = [p for p in profiles if (p.get("name") or "").strip().lower() == wanted.lower()]
            if len(by_name) == 1:
                return by_name[0]
            raise UniFiNotFoundError("alarm profile", profile_id)
        if len(profiles) == 1:
            return profiles[0]
        choices = ", ".join(f"{p.get('name') or '?'} ({p.get('id')})" for p in profiles)
        raise ValueError(f"profile_id is required because this console has several arm profiles: {choices}")

    def _disarm_targets(self, profiles: list[dict[str, Any]], profile_id: str | None) -> list[dict[str, Any]]:
        if profile_id:
            target = self._resolve_v2_profile(profiles, profile_id)
            return [target] if AlarmManager._is_armed_status(target.get("state")) else []
        return self._active_v2_profiles(profiles)

    async def _v2_profile_after_action(self, profile_id: str) -> dict[str, Any]:
        raw = await self._service.list_profiles()
        for p in raw:
            if isinstance(p, dict) and p.get("id") == profile_id:
                return {**p, "name": p.get("name") or p.get("title")}
        raise UniFiNotFoundError("alarm profile", profile_id)

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

        body = alarm_rule_to_legacy_create_body(fields)
        raw = await self._legacy.create_rule(body)
        return alarm_rule_from_legacy(raw).model_dump(exclude_none=True), False

    async def update_rule(self, rule_id: str, fields: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Update a rule, routing by id family."""
        if not fields:
            raise ValueError("No fields provided. Specify at least one field to update.")
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
