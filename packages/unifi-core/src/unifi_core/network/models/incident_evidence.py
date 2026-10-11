"""Validated arguments for bounded Network incident evidence collection."""

from __future__ import annotations

from pydantic import Field, field_validator

from unifi_core.incident_collection import MAX_FILTER_IDS, IncidentCollectionRequest
from unifi_core.mac import canonical_mac


class NetworkIncidentRequest(IncidentCollectionRequest):
    device_macs: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_FILTER_IDS,
        description=(
            "Exact device MAC addresses; only events naming one of them are kept. "
            "Network events identify devices by MAC, never by name."
        ),
    )

    @field_validator("device_macs", mode="before")
    @classmethod
    def _none_is_empty(cls, value: object) -> object:
        return () if value is None else value

    @field_validator("device_macs")
    @classmethod
    def _macs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        canonical = [canonical_mac(mac) for mac in value]
        if any(mac is None for mac in canonical):
            raise ValueError("device_macs must be MAC addresses (six hex pairs)")
        return tuple(sorted(set(canonical)))  # type: ignore[arg-type]
