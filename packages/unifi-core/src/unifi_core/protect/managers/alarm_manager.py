"""Alarm Manager control for UniFi Protect.

Wraps the private ``/proxy/protect/api/arm/*`` and
``/proxy/protect/api/automations`` endpoints used by the UniFi Protect
Alarm Manager (Protect 6.1+) to arm/disarm the system and to manage
the underlying alarm rules (automations).

The ``uiprotect`` library does not expose either set natively, so this
manager calls them directly via ``ProtectApiClient.api_request``.

Endpoints (verified against Protect 7.0)
-----------------------------------------
Arm/disarm:
  - ``GET  arm/profiles``    -- list all arm profile definitions
  - ``PATCH arm``            -- select active profile, body ``{"armProfileId": "..."}``
  - ``POST arm/enable``      -- arm the system (empty body)
  - ``POST arm/disable``     -- disarm the system (empty body)

Rules (automations):
  - ``GET    automations``         -- list all alarm rules
  - ``GET    automations/{id}``    -- 404s on this controller; there is no
                                      per-rule GET, so ``get_rule`` fetches the
                                      list and filters by id
  - ``POST   automations``         -- create a new rule (body = full payload)
  - ``PATCH  automations/{id}``    -- update a rule (body = full payload;
                                      Protect rejects partial bodies, so callers
                                      should read-modify-write)
  - ``DELETE automations/{id}``    -- delete a rule

Current armed state lives in ``nvr.armMode`` (single state per system,
not per-profile):

.. code-block:: json

    {
      "status": "disabled",           // or "active"/"armed" when on
      "armProfileId": "<id>",         // currently selected profile
      "armedAt": 1775400000000,
      "willBeArmedAt": null,
      "breachDetectedAt": 1775310901100,
      "breachEventCount": 0,
      "breachTriggerEventId": null,
      "breachEventId": "..."
    }
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.connection_manager import ProtectConnectionManager

logger = logging.getLogger(__name__)

# Values of ``nvr.armMode.status`` that mean "not armed".
_DISARMED_STATUSES = {"disabled", "disarmed", "off", "inactive"}


class AlarmManager:
    """Domain logic for the UniFi Protect Alarm Manager."""

    def __init__(self, connection_manager: ProtectConnectionManager) -> None:
        self._cm = connection_manager

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_arm_profiles(self) -> List[Dict[str, Any]]:
        """Return all configured arm profile definitions.

        ``GET arm/profiles`` returns a flat array of profile objects.
        """
        data = await self._cm.client.api_request("arm/profiles", method="get")
        if not isinstance(data, list):
            logger.warning("Unexpected arm/profiles shape: %r", type(data))
            return []

        return [self._format_profile(p) for p in data if isinstance(p, dict)]

    async def get_arm_state(self) -> Dict[str, Any]:
        """Return the current Alarm Manager state.

        Merges ``nvr.armMode`` (status + active profile id) with
        ``arm/profiles`` (profile names/metadata) into a single dict.
        """
        nvr_data, profiles = await self._fetch_state()

        arm_mode = (nvr_data or {}).get("armMode") or {}
        status = arm_mode.get("status")
        active_profile_id = arm_mode.get("armProfileId")

        # Look up the active profile's name if we have it
        active_profile = next(
            (p for p in profiles if p["id"] == active_profile_id),
            None,
        )

        return {
            "armed": self._is_armed_status(status),
            "status": status,
            "active_profile_id": active_profile_id,
            "active_profile_name": active_profile["name"] if active_profile else None,
            "armed_at": _ms_to_iso(arm_mode.get("armedAt")),
            "will_be_armed_at": _ms_to_iso(arm_mode.get("willBeArmedAt")),
            "breach_detected_at": _ms_to_iso(arm_mode.get("breachDetectedAt")),
            "breach_event_count": arm_mode.get("breachEventCount", 0),
            "profiles": profiles,
        }

    async def _fetch_state(self) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Fetch nvr + arm/profiles in one pair of calls."""
        nvr_data = await self._cm.client.api_request("nvr", method="get")
        profiles_raw = await self._cm.client.api_request("arm/profiles", method="get")

        profiles: List[Dict[str, Any]] = []
        if isinstance(profiles_raw, list):
            profiles = [self._format_profile(p) for p in profiles_raw if isinstance(p, dict)]

        if not isinstance(nvr_data, dict):
            nvr_data = {}

        return nvr_data, profiles

    @staticmethod
    def _format_profile(p: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": p.get("id"),
            "name": p.get("name"),
            "record_everything": p.get("recordEverything", False),
            "activation_delay_ms": p.get("activationDelay"),
            "schedule_count": len(p.get("schedules") or []),
            "automation_count": len(p.get("automations") or []),
        }

    @staticmethod
    def _is_armed_status(status: Optional[str]) -> bool:
        if not status:
            return False
        return str(status).lower() not in _DISARMED_STATUSES

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _resolve_profile_id(self, profile_id: Optional[str]) -> str:
        """Return ``profile_id`` or fall back to the currently selected one.

        Fall-back order when ``profile_id`` is ``None``:
          1. ``nvr.armMode.armProfileId`` (the currently selected profile)
          2. The first profile returned by ``arm/profiles``
        """
        if profile_id:
            return profile_id

        nvr_data, profiles = await self._fetch_state()
        current = (nvr_data.get("armMode") or {}).get("armProfileId")
        if current:
            return str(current)

        if profiles:
            first_id = profiles[0].get("id")
            if first_id:
                return str(first_id)

        raise ValueError(
            "No arm profiles found. Configure Alarm Manager in the Protect UI first, or pass profile_id explicitly."
        )

    async def _select_profile(self, profile_id: str) -> None:
        """PATCH ``arm`` to set which profile is active."""
        await self._cm.client.api_request(
            "arm",
            method="patch",
            json={"armProfileId": profile_id},
        )

    # ------------------------------------------------------------------
    # Preview (for confirm=false tool responses)
    # ------------------------------------------------------------------

    async def preview_arm(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Return current + proposed state for the arm action preview."""
        nvr_data, profiles = await self._fetch_state()
        arm_mode = nvr_data.get("armMode") or {}
        current_profile_id = arm_mode.get("armProfileId")
        currently_armed = self._is_armed_status(arm_mode.get("status"))

        target_id = profile_id or current_profile_id
        if not target_id and profiles:
            target_id = profiles[0].get("id")
        if not target_id:
            raise ValueError(
                "No arm profiles found. Configure Alarm Manager in the Protect UI first, or pass profile_id explicitly."
            )
        target_id = str(target_id)
        target_name = next((p["name"] for p in profiles if p["id"] == target_id), None)

        return {
            "target_profile_id": target_id,
            "target_profile_name": target_name,
            "current_state": {
                "armed": currently_armed,
                "active_profile_id": current_profile_id,
                "status": arm_mode.get("status"),
            },
            "proposed_changes": {
                "armed": True,
                "active_profile_id": target_id,
            },
        }

    async def preview_disarm(self) -> Dict[str, Any]:
        """Return current state for the disarm action preview."""
        state = await self.get_arm_state()
        return {
            "active_profile_id": state["active_profile_id"],
            "active_profile_name": state["active_profile_name"],
            "current_state": {
                "armed": state["armed"],
                "status": state["status"],
            },
            "proposed_changes": {"armed": False},
        }

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def arm(self, profile_id: Optional[str] = None) -> Dict[str, Any]:
        """Arm the Alarm Manager.

        1. Selects ``profile_id`` via ``PATCH arm`` (or uses current selection).
        2. Activates via ``POST arm/enable``.

        If ``profile_id`` is ``None``, the currently selected profile (from
        ``nvr.armMode.armProfileId``) is used and no PATCH is issued.

        Idempotent: if already armed with the same profile, returns without
        making the POST call (the API returns 400 on duplicate arm).
        """
        nvr_data, profiles = await self._fetch_state()
        arm_mode = nvr_data.get("armMode") or {}
        current_status = arm_mode.get("status")
        current_profile_id = arm_mode.get("armProfileId")
        currently_armed = self._is_armed_status(current_status)

        pid = profile_id or current_profile_id
        if not pid:
            # No currently-selected profile and none passed; pick first available.
            if profiles:
                pid = profiles[0].get("id")
            if not pid:
                raise ValueError(
                    "No arm profiles found. Configure Alarm Manager in the "
                    "Protect UI first, or pass profile_id explicitly."
                )
        pid = str(pid)

        name = next((p["name"] for p in profiles if p["id"] == pid), None)

        # Short-circuit if already armed with the same profile.
        if currently_armed and pid == current_profile_id:
            logger.info("Already armed with profile %s (%s) — no-op", pid, name)
            return {
                "armed": True,
                "profile_id": pid,
                "profile_name": name,
                "already_armed": True,
            }

        # Switching profiles while armed is not supported: the POST arm/enable
        # endpoint returns 400 when the system is already armed. Require the
        # caller to disarm first so the flow is always disabled -> patch -> enable.
        if currently_armed and profile_id and profile_id != current_profile_id:
            raise ValueError(
                f"Cannot switch arm profile while system is armed "
                f"(currently armed with profile {current_profile_id!r}). "
                f"Disarm first, then arm with the new profile."
            )

        # Select the profile (PATCH) when the caller explicitly passed one that
        # differs from the current selection.
        if profile_id and profile_id != current_profile_id:
            await self._select_profile(pid)

        logger.info("Arming Protect Alarm Manager profile %s (%s)", pid, name)
        await self._cm.client.api_request("arm/enable", method="post")

        return {
            "armed": True,
            "profile_id": pid,
            "profile_name": name,
        }

    async def disarm(self) -> Dict[str, Any]:
        """Disarm the Alarm Manager.

        ``POST arm/disable`` is a single system-wide disarm — no profile id
        is required (and none is accepted by the endpoint).

        Idempotent: if already disarmed, returns without making the POST call
        (the API returns 400 "Attempted to disarm the alarm when it is not
        armed" otherwise).
        """
        state = await self.get_arm_state()
        if not state["armed"]:
            logger.info("Already disarmed — no-op")
            return {"armed": False, "already_disarmed": True}

        logger.info("Disarming Protect Alarm Manager")
        await self._cm.client.api_request("arm/disable", method="post")

        return {"armed": False}

    # ------------------------------------------------------------------
    # Rule (automation) CRUD
    # ------------------------------------------------------------------

    async def list_rules(self) -> List[Dict[str, Any]]:
        """Return every alarm rule defined under Alarm Manager.

        ``GET automations`` returns a flat array of rule payloads. Each entry
        is passed through largely as-is; the tool/model layer is responsible
        for coercing into :class:`AlarmRule`.
        """
        data = await self._cm.client.api_request("automations", method="get")
        if not isinstance(data, list):
            logger.warning("Unexpected automations shape: %r", type(data))
            return []
        return [r for r in data if isinstance(r, dict)]

    async def get_rule(self, rule_id: str) -> Dict[str, Any]:
        """Fetch a single alarm rule by id.

        The controller exposes no per-rule GET endpoint — ``GET
        automations/{id}`` returns 404 — so the full payload is only available
        from the list endpoint. We fetch ``GET automations`` and filter by id.

        Raises ``ValueError`` on empty id, ``UniFiNotFoundError`` if no rule
        with that id exists.
        """
        rule_id = _require_rule_id(rule_id)
        for rule in await self.list_rules():
            if rule.get("id") == rule_id:
                return rule
        raise UniFiNotFoundError("alarm rule", rule_id)

    async def update_rule(self, rule_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Update an alarm rule via PATCH.

        Protect's ``PATCH automations/{id}`` expects the FULL rule body
        (verified via JeffSteinbok/hass-uiprotectalarms implementation).
        Callers must perform a read-modify-write: call :meth:`get_rule`
        first, mutate the returned dict, then pass it back here.
        """
        rule_id = _require_rule_id(rule_id)
        _require_dict_body(body, "body")
        data = await self._cm.client.api_request(f"automations/{rule_id}", method="patch", json=body)
        if not isinstance(data, dict):
            # PATCH usually echoes the updated rule; if the controller returns
            # something else, surface it but coerce to a safe shape so callers
            # don't crash.
            logger.warning(
                "PATCH automations/%s returned non-dict %r; coercing to {} ",
                rule_id,
                type(data),
            )
            return {}
        return data

    async def create_rule(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new alarm rule via POST.

        Body must be a full rule payload matching the Protect ``automations``
        schema (sources / conditions / actions / cooldown / etc.). The server
        assigns the rule ``id`` and returns the created rule.
        """
        _require_dict_body(body, "body")
        data = await self._cm.client.api_request("automations", method="post", json=body)
        if not isinstance(data, dict):
            logger.warning(
                "POST automations returned non-dict %r; coercing to {}",
                type(data),
            )
            return {}
        return data

    async def delete_rule(self, rule_id: str) -> Dict[str, Any]:
        """Delete an alarm rule by id.

        The controller returns an empty body on a successful delete, so we use
        ``api_request_raw`` (which does not attempt to decode JSON) to avoid a
        spurious "Could not decode JSON" error on an otherwise-successful call.
        """
        rule_id = _require_rule_id(rule_id)
        await self._cm.client.api_request_raw(f"automations/{rule_id}", method="delete")
        return {"deleted": True, "rule_id": rule_id}

    # ------------------------------------------------------------------
    # Rule preview helpers (for confirm=false tool responses)
    # ------------------------------------------------------------------

    async def preview_update_rule(self, rule_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """Return current vs. proposed rule state for an update preview."""
        rule_id = _require_rule_id(rule_id)
        _require_dict_body(body, "body")
        current = await self.get_rule(rule_id)
        return {
            "rule_id": rule_id,
            "current": current,
            "proposed": body,
        }

    async def preview_delete_rule(self, rule_id: str) -> Dict[str, Any]:
        """Return current rule + delete intent for a delete preview."""
        rule_id = _require_rule_id(rule_id)
        current = await self.get_rule(rule_id)
        return {
            "rule_id": rule_id,
            "current_name": current.get("name"),
            "proposed_changes": {"deleted": True},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms_to_iso(value: Any) -> Optional[str]:
    """Convert a millisecond unix timestamp to an ISO-8601 UTC string."""
    if value is None:
        return None
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _require_rule_id(rule_id: Any) -> str:
    """Validate ``rule_id`` is a non-empty string and return it stripped.

    Returning the stripped value lets callers rebind ``rule_id`` so a padded id
    like ``" rule-001 "`` matches the controller's id during list filtering
    instead of silently missing.
    """
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ValueError("rule_id must be a non-empty string")
    return rule_id.strip()


def _require_dict_body(body: Any, name: str) -> None:
    """Validate that ``body`` is a dict (Protect rule payloads are objects)."""
    if not isinstance(body, dict):
        raise TypeError(f"{name} must be a dict, got {type(body).__name__}")
