"""Typed IPS signature suppressions and detection exclusions: the read, and the create and delete rules.

Network 11.0 keeps both in the ``ips_suppression`` settings section:
``alerts`` holds suppressed signatures and ``whitelist`` the detection exclusions.
An alert of ``type`` ``all`` suppresses its signature for all traffic; one of
``type`` ``track`` suppresses it only for its ``tracking`` targets, each an
``ip`` address or a ``subnet`` in one direction (``src``, ``dest`` or ``both``).
The controller refuses an unknown category, an address given as ``subnet`` or a
CIDR given as ``ip``, and accepts a second alert for a signature it already
holds, so a create merges into the signature's alert rather than adding one.
"""

from __future__ import annotations

import ipaddress
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from unifi_core.exceptions import UniFiNotFoundError

_DIRECTION_SCOPES = {"src": "source", "dest": "destination", "both": "both"}
_SCOPE_DIRECTIONS = {scope: direction for direction, scope in _DIRECTION_SCOPES.items()}


class IpsExclusion(BaseModel):
    """An address excluded from all IPS detection."""

    scope: str | None = Field(default=None, description="source, destination, or both; null if unknown")
    direction: str | None = Field(default=None, description="Raw controller direction")
    mode: str | None = Field(default=None, description="Raw controller target kind, such as ip or subnet")
    target: str | None = Field(default=None, description="Excluded address, subnet, or network")


class IpsSuppression(BaseModel):
    """One suppressed signature for one target, or for all traffic."""

    signature_id: int = Field(description="Signature ID")
    gid: int | None = Field(default=None, description="Signature generator ID")
    signature: str | None = Field(default=None, description="Signature name")
    category: str | None = Field(default=None, description="Signature category")
    suppression_type: str | None = Field(default=None, description="Raw controller type, such as all or track")
    scope: str | None = Field(default=None, description="global, source, destination, or both; null if unknown")
    direction: str | None = Field(default=None, description="Raw controller direction")
    mode: str | None = Field(default=None, description="Raw controller target kind, such as ip or subnet")
    target: str | None = Field(default=None, description="Suppressed address, subnet, or network")


class IpsSuppressions(BaseModel):
    """Every signature suppression and detection exclusion on the site."""

    suppressions: list[IpsSuppression]
    exclusions: list[IpsExclusion]


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _records(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Invalid IPS suppression record")
    return value


def _target(record: dict[str, Any]) -> dict[str, str | None]:
    direction = _text(record.get("direction"))
    target = record.get("value")
    if not isinstance(target, str) or not target:
        raise ValueError("Invalid IPS suppression target")
    return {
        "scope": _DIRECTION_SCOPES.get(direction),
        "direction": direction,
        "mode": _text(record.get("mode")),
        "target": target,
    }


def ips_suppressions_from_controller(record: Any) -> IpsSuppressions:
    """Flatten to one entry per target; fail rather than drop an entry that cannot be read."""
    if not isinstance(record, dict):
        raise ValueError("Invalid IPS suppression record")
    suppressions = []
    for alert in _records(record.get("alerts")):
        if type(alert.get("id")) is not int:
            raise ValueError("Invalid IPS suppression signature ID")
        kind = _text(alert.get("type"))
        signature = {
            "signature_id": alert["id"],
            "gid": alert["gid"] if type(alert.get("gid")) is int else None,
            "signature": _text(alert.get("signature")),
            "category": _text(alert.get("category")),
            "suppression_type": kind,
        }
        if kind == "all":
            targets = [{"scope": "global"}]
        else:
            # An alert without targets is still listed, with an unknown scope.
            targets = [_target(item) for item in _records(alert.get("tracking", []))] or [{}]
        suppressions.extend(IpsSuppression(**signature, **target) for target in targets)
    exclusions = [IpsExclusion(**_target(item)) for item in _records(record.get("whitelist"))]
    return IpsSuppressions(suppressions=suppressions, exclusions=exclusions)


class IpsSuppressionConflict(ValueError):
    """A create or delete that does not fit the signature's current suppression. The text is fixed."""


_TARGET_DESCRIPTION = "IPv4 or IPv6 address, or a CIDR subnet such as 192.0.2.0/24"


def _normalized_target(target: str) -> tuple[str, str]:
    """``(mode, value)`` for a target: an address is ``ip``, a CIDR is ``subnet``."""
    text = target.strip()
    try:
        if "/" in text:
            return "subnet", str(ipaddress.ip_network(text, strict=True))
        return "ip", str(ipaddress.ip_address(text))
    except ValueError:
        raise ValueError("target must be an IP address or a CIDR subnet with no host bits set") from None


class IpsSuppressionCreate(BaseModel):
    """Suppress one signature for all traffic, or for one target in one direction."""

    model_config = ConfigDict(extra="forbid")

    signature_id: StrictInt = Field(gt=0, description="Signature ID, as an IPS event reports it")
    gid: StrictInt = Field(default=1, gt=0, description="Signature generator ID; 1 for most signatures")
    scope: Literal["global", "source", "destination", "both"] = Field(
        description="global suppresses the signature for all traffic; the others only for target in that direction"
    )
    target: str | None = Field(default=None, description=f"{_TARGET_DESCRIPTION}; required unless scope is global")
    signature: str | None = Field(
        default=None, max_length=256, description="Signature name to store with a new suppression"
    )
    category: str | None = Field(
        default=None,
        max_length=128,
        description="IPS category code to store with a new suppression, such as emerging-webapps; "
        "the controller refuses an unknown code",
    )

    @model_validator(mode="after")
    def _target_matches_scope(self) -> IpsSuppressionCreate:
        if self.scope == "global":
            if self.target is not None:
                raise ValueError("a global suppression takes no target")
        elif self.target is None:
            raise ValueError("target is required unless scope is global")
        else:
            _normalized_target(self.target)
        return self

    def tracking_entry(self) -> dict[str, str] | None:
        if self.target is None:
            return None
        mode, value = _normalized_target(self.target)
        return {"mode": mode, "value": value, "direction": _SCOPE_DIRECTIONS[self.scope]}


class IpsSuppressionDelete(BaseModel):
    """Remove a signature's suppression, or one of its targets."""

    model_config = ConfigDict(extra="forbid")

    signature_id: StrictInt = Field(gt=0, description="Signature ID of the suppression")
    gid: StrictInt = Field(default=1, gt=0, description="Signature generator ID; 1 for most signatures")
    target: str | None = Field(
        default=None,
        description=f"{_TARGET_DESCRIPTION} to stop suppressing; omit to remove the signature's whole suppression",
    )
    scope: Literal["source", "destination", "both"] | None = Field(
        default=None, description="With target: only the entry in this direction; omit for any direction"
    )

    @model_validator(mode="after")
    def _scope_needs_target(self) -> IpsSuppressionDelete:
        if self.target is None:
            if self.scope is not None:
                raise ValueError("scope applies only with a target")
        else:
            _normalized_target(self.target)
        return self


def _is_signature(alert: dict[str, Any], signature_id: int, gid: int) -> bool:
    return alert.get("id") == signature_id and (alert.get("gid") if type(alert.get("gid")) is int else 1) == gid


def apply_suppression_create(record: dict[str, Any], request: IpsSuppressionCreate) -> dict[str, Any]:
    """The section with the suppression added; equal to ``record`` when it is already in place.

    Every alert of the signature counts, since the controller can hold duplicates: one ``all`` alert
    among them suppresses it for all traffic.
    """
    updated = deepcopy(record)
    alerts = _records(updated.get("alerts"))
    matching = [alert for alert in alerts if _is_signature(alert, request.signature_id, request.gid)]
    entry = request.tracking_entry()
    if not matching:
        alert: dict[str, Any] = {"id": request.signature_id, "gid": request.gid}
        if request.signature is not None:
            alert["signature"] = request.signature
        if request.category is not None:
            alert["category"] = request.category
        alert["type"] = "all" if entry is None else "track"
        alert["tracking"] = [] if entry is None else [entry]
        alerts.append(alert)
        return updated
    if entry is None:
        # Global: the signature's targets stay stored, as the controller keeps them, but no longer narrow it.
        for alert in matching:
            alert["type"] = "all"
        return updated
    if any(alert.get("type") == "all" for alert in matching):
        raise IpsSuppressionConflict(
            "the signature is already suppressed for all traffic; remove that suppression to suppress it per target"
        )
    if any(entry in _records(alert.get("tracking", [])) for alert in matching):
        return updated
    _records(matching[0].setdefault("tracking", [])).append(entry)
    return updated


def apply_suppression_delete(record: dict[str, Any], request: IpsSuppressionDelete) -> dict[str, Any]:
    """The section with the suppression or target removed. A signature or target it does not hold is not found."""
    updated = deepcopy(record)
    alerts = _records(updated.get("alerts"))
    matching = [alert for alert in alerts if _is_signature(alert, request.signature_id, request.gid)]
    if not matching:
        raise UniFiNotFoundError("IPS suppression", f"{request.gid}:{request.signature_id}")
    if request.target is None:
        updated["alerts"] = [alert for alert in alerts if alert not in matching]
        return updated
    if any(alert.get("type") == "all" for alert in matching):
        raise IpsSuppressionConflict(
            "the signature is suppressed for all traffic, not per target; omit target to remove the suppression"
        )
    mode, value = _normalized_target(request.target)
    direction = _SCOPE_DIRECTIONS[request.scope] if request.scope is not None else None

    def removed(item: dict[str, Any]) -> bool:
        return (
            item.get("mode") == mode
            and item.get("value") == value
            and (direction is None or item.get("direction") == direction)
        )

    found = False
    for alert in matching:
        tracking = _records(alert.get("tracking", []))
        kept = [item for item in tracking if not removed(item)]
        found = found or len(kept) != len(tracking)
        alert["tracking"] = kept
    if not found:
        raise UniFiNotFoundError("IPS suppression target", f"{request.gid}:{request.signature_id} {value}")
    # A targeted suppression with no targets left suppresses nothing; remove it rather than keep an empty alert.
    updated["alerts"] = [alert for alert in alerts if not (alert in matching and not alert.get("tracking"))]
    return updated


def signature_suppressions(suppressions: IpsSuppressions, signature_id: int, gid: int) -> list[dict[str, Any]]:
    """One signature's public entries, for previews and verification."""
    return [
        entry.model_dump()
        for entry in suppressions.suppressions
        if entry.signature_id == signature_id and (entry.gid if entry.gid is not None else 1) == gid
    ]
