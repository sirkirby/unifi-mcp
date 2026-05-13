"""Strawberry types for network/switch and the switch-cluster read shapes.

Phase 6 PR2 Task 24 migration target. One type per read serializer that used to
live in ``unifi_api.serializers.network.switch``:

- ``PortProfile``        — list_port_profiles + get_port_profile_details
- ``SwitchPorts``        — get_switch_ports (wrapper-dict: name/model + port_overrides[])
- ``PortStats``          — get_port_stats   (wrapper-dict: name/model + port_table[])
- ``SwitchCapabilities`` — get_switch_capabilities

The wrapper-dict types follow the Task 20 ``DeviceRadio`` / ``LldpNeighbors``
precedent: a wrapper type holds typed scalar fields plus a ``list[SubRow]`` of
typed row entries; ``to_dict()`` walks the list to produce the same dict shape
the legacy serializer emitted.

Mutation acks (``SwitchMutationAckSerializer``) stay in the original module —
they cover ``create/update/delete_port_profile``, ``set_*``,
``configure_*``, ``power_cycle_*``, ``set_jumbo_frames``,
``update_switch_stp`` with bool/dict coercion.

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/switch.py. ``to_dict()`` exposes
the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A switch port profile (PoE / VLAN tagging template).")
class PortProfile:
    id: strawberry.ID | None
    name: str | None
    forward: str | None
    native_networkconf_id: str | None
    tagged_networkconf_ids: list[str]
    voice_networkconf_id: str | None
    poe_mode: str | None
    isolation: bool | None
    stp_port_mode: bool | None
    dot1x_ctrl: str | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", "forward", "poe_mode", "native_networkconf_id"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "PortProfile":
        tagged = _get(obj, "tagged_networkconf_ids", []) or []
        if not isinstance(tagged, list):
            tagged = []
        return cls(
            id=_get(obj, "_id") or _get(obj, "id"),
            name=_get(obj, "name"),
            forward=_get(obj, "forward"),
            native_networkconf_id=_get(obj, "native_networkconf_id"),
            tagged_networkconf_ids=list(tagged),
            voice_networkconf_id=_get(obj, "voice_networkconf_id"),
            poe_mode=_get(obj, "poe_mode"),
            isolation=_get(obj, "isolation"),
            stp_port_mode=_get(obj, "stp_port_mode"),
            dot1x_ctrl=_get(obj, "dot1x_ctrl"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A single port-override row on a switch.")
class PortOverrideRow:
    port_idx: int | None
    name: str | None
    portconf_id: str | None
    poe_mode: str | None
    op_mode: str | None

    @classmethod
    def from_manager_output(cls, p: Any) -> "PortOverrideRow":
        return cls(
            port_idx=_get(p, "port_idx"),
            name=_get(p, "name"),
            portconf_id=_get(p, "portconf_id"),
            poe_mode=_get(p, "poe_mode"),
            op_mode=_get(p, "op_mode"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Wrapper dict containing port-override rows for a switch.")
class SwitchPorts:
    """Wrapper-dict shape: manager returns ``{name, model, port_overrides: [...]}``.
    The port-override rows are passed through with field whitelisting."""

    name: str | None
    model: str | None
    port_overrides: list[PortOverrideRow]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SwitchPorts":
        rows = _get(obj, "port_overrides", []) or []
        return cls(
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            port_overrides=[PortOverrideRow.from_manager_output(p) for p in rows],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "port_overrides": [p.to_dict() for p in self.port_overrides],
        }


@strawberry.type(description="A single port-table row reporting per-port stats.")
class PortStatRow:
    port_idx: int | None
    name: str | None
    enable: bool
    speed: int | None
    duplex: bool | None
    tx_bytes: int
    rx_bytes: int
    tx_packets: int
    rx_packets: int
    tx_dropped: int
    rx_dropped: int
    poe_enable: bool
    poe_mode: str | None
    poe_power: float | None

    @classmethod
    def from_manager_output(cls, p: Any) -> "PortStatRow":
        return cls(
            port_idx=_get(p, "port_idx"),
            name=_get(p, "name"),
            enable=bool(_get(p, "enable", True)),
            speed=_get(p, "speed"),
            duplex=_get(p, "full_duplex"),
            tx_bytes=_get(p, "tx_bytes", 0),
            rx_bytes=_get(p, "rx_bytes", 0),
            tx_packets=_get(p, "tx_packets", 0),
            rx_packets=_get(p, "rx_packets", 0),
            tx_dropped=_get(p, "tx_dropped", 0),
            rx_dropped=_get(p, "rx_dropped", 0),
            poe_enable=bool(_get(p, "poe_enable", False)),
            poe_mode=_get(p, "poe_mode"),
            poe_power=_get(p, "poe_power"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Wrapper dict containing the per-port stats table for a switch.")
class PortStats:
    """Wrapper-dict shape: manager returns ``{name, model, port_table: [...]}``.
    The port-table rows are passed through with field whitelisting."""

    name: str | None
    model: str | None
    port_table: list[PortStatRow]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "PortStats":
        rows = _get(obj, "port_table", []) or []
        return cls(
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            port_table=[PortStatRow.from_manager_output(p) for p in rows],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "port_table": [p.to_dict() for p in self.port_table],
        }


@strawberry.type(description="Switch capabilities (caps dict + STP / dot1x flags).")
class SwitchCapabilities:
    name: str | None
    model: str | None
    switch_caps: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    stp_version: str | None
    stp_priority: str | None
    jumboframe_enabled: bool | None
    dot1x_portctrl_enabled: bool | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SwitchCapabilities":
        caps = _get(obj, "switch_caps", {}) or {}
        return cls(
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            switch_caps=caps,
            stp_version=_get(obj, "stp_version"),
            stp_priority=_get(obj, "stp_priority"),
            jumboframe_enabled=_get(obj, "jumboframe_enabled"),
            dot1x_portctrl_enabled=_get(obj, "dot1x_portctrl_enabled"),
        )

    def to_dict(self) -> dict:
        return asdict(self)
