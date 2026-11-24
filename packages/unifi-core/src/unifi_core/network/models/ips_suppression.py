"""Typed read of IPS signature suppressions and detection exclusions.

Network 11.0 keeps both in the ``ips_suppression`` settings section:
``alerts`` holds suppressed signatures and ``whitelist`` the detection exclusions.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

_DIRECTION_SCOPES = {"src": "source", "dest": "destination", "both": "both"}


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
