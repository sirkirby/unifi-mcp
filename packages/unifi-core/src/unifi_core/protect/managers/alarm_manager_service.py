"""Manager for UniFi OS Alarm Manager (``/api/v2/alarms/``).

Reads the modern UniFi-OS alarm surface via ``uiprotect``'s ``api_request`` with
an ``api_path`` override (lib-native; no bespoke client). This is the AI-capable
Alarm Manager, distinct from the legacy Protect automations in ``alarm_manager``.

Arm/disarm goes through ``profiles/{uuid}/actions/{arm,disarm}`` -- the only
control surface that works once a console runs the Alarm Manager in Global mode
(adopting USL sensors, fobs, relays or an Alarm Hub forces that mode).

A Protect-scoped account receives 403 Forbidden, surfaced as
:class:`AlarmManagerPermissionError` with actionable guidance. An adequate
(e.g. SuperAdmin) credential is necessary but not sufficient: on a console where
Protect has not migrated to the Alarm Manager, this endpoint returns ``200 []``
even when legacy automations exist, so an empty result here does not mean
"no rules." :class:`~unifi_core.protect.managers.alarm_facade.AlarmRulesFacade`
falls back to the legacy automations API on both 403 and empty/4xx for this reason.
"""

import ipaddress
import logging
import re
from typing import Any, Dict, List

from uiprotect.exceptions import BadRequest, NotAuthorized, PublicOnlyModeError

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


_URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_WORD_RE = re.compile(r"[^\s,;()<>\"']+")


def _is_ip_literal(word: str) -> bool:
    """True for an IPv4/IPv6 literal, with or without brackets, port, zone or trailing punctuation."""
    candidate = word.strip(".!?")
    bracketed = re.match(r"\[([^\]]+)\]", candidate)
    if bracketed:
        candidate = bracketed.group(1)
    candidate = candidate.split("%", 1)[0]
    options = {candidate, candidate.rstrip(":")}
    if candidate.count(":") == 1:
        options.add(candidate.split(":", 1)[0])
    for option in options:
        try:
            ipaddress.ip_address(option)
        except ValueError:
            continue
        return True
    return False


def _refusal_reason(error: BadRequest, host: str | None) -> str:
    """The controller's reason from a uiprotect request error, or fixed text when it names an address.

    uiprotect formats "Request failed: <url> - Status: <n> - Reason: <reason>", so the reason starts
    after the first delimiter and the request URL never reaches the caller. A reason that itself holds
    a URL, an IP literal or the configured console host is replaced, so no console address leaks.
    """
    _, sep, reason = str(error).partition(" - Reason: ")
    reason = reason.strip() if sep else ""
    if (
        not reason
        or _URL_RE.search(reason)
        or (host and host.lower() in reason.lower())
        or any(_is_ip_literal(word) for word in _WORD_RE.findall(reason))
    ):
        return "request rejected"
    return reason


class AlarmManagerService:
    """Reads UniFi OS Alarm Manager rules and profiles, and arms/disarms profiles."""

    def __init__(self, connection_manager: ProtectConnectionManager):
        self._cm = connection_manager

    def _console_host(self) -> str | None:
        host = getattr(self._cm, "host", None)
        return host if isinstance(host, str) and host.strip() else None

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

    async def arm_profile(self, profile_id: str) -> Dict[str, Any]:
        """Arm one profile via ``POST /api/v2/alarms/profiles/{uuid}/actions/arm``.

        This is the call the Protect web app makes when the Alarm Manager runs in
        Global mode (``nvr.featureFlags.useExternalAlarmManager``), where the
        legacy ``arm/enable`` endpoint is a silent no-op. The controller answers
        with the profile; its ``state`` is ``arming`` while the activation delay
        runs and ``armed`` once it elapses.
        """
        return await self._profile_action(profile_id, "arm")

    async def disarm_profile(self, profile_id: str) -> Dict[str, Any]:
        """Disarm one profile via ``POST /api/v2/alarms/profiles/{uuid}/actions/disarm``."""
        return await self._profile_action(profile_id, "disarm")

    async def _profile_action(self, profile_id: str, action: str) -> Dict[str, Any]:
        if not profile_id:
            raise ValueError("profile_id is required")
        try:
            data = await self._api_request(f"profiles/{profile_id}/actions/{action}", method="post")
        except PublicOnlyModeError:
            # Raised locally before any request; its fixed text explains the private session it needs.
            raise
        except BadRequest as exc:
            raise ValueError(
                f"The controller refused to {action} alarm profile {profile_id}: "
                f"{_refusal_reason(exc, self._console_host())}"
            ) from None
        return data if isinstance(data, dict) else {}

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
