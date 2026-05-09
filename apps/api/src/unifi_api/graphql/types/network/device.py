"""Strawberry types for network/devices and the device-cluster read shapes.

Phase 6 PR2 Task 20 migration target. One type per read serializer that used to
live in ``unifi_api.serializers.network.devices``:

- ``Device``               — list_devices + get_device_details
- ``DeviceRadio``          — get_device_radio (wrapper-dict: name/model + radios[])
- ``LldpNeighbors``        — get_lldp_neighbors (wrapper-dict: name/model + lldp_table[])
- ``RogueAp``              — list_rogue_aps
- ``RfScanResult``         — get_rf_scan_results
- ``AvailableChannel``     — list_available_channels
- ``SpeedtestStatus``      — get_speedtest_status

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/devices.py. ``to_dict()``
exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from unifi_api.graphql.types.network.client import Client


_STATE_MAP = {
    0: "disconnected",
    1: "connected",
    2: "pending",
    4: "upgrading",
    5: "provisioning",
    6: "heartbeat-missed",
    7: "adopting",
    9: "adoption-error",
    11: "isolated",
}


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A UniFi network device (AP, switch, gateway).")
class Device:
    mac: strawberry.ID | None
    name: str | None
    model: str | None
    type: str | None
    version: str | None
    uptime: int | None
    state: str | None
    ip: str | None
    ports: strawberry.scalars.JSON | None  # type: ignore[name-defined]

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None
    _site: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "mac",
            "display_columns": ["name", "model", "type", "state", "ip"],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Device":
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        state_raw = raw.get("state")
        return cls(
            mac=raw.get("mac"),
            name=raw.get("name"),
            model=raw.get("model"),
            type=raw.get("type"),
            version=raw.get("version"),
            uptime=raw.get("uptime"),
            state=_STATE_MAP.get(state_raw, state_raw),
            ip=raw.get("ip"),
            ports=raw.get("port_table") or raw.get("ports"),
        )

    def to_dict(self) -> dict:
        out = asdict(self)
        return {k: v for k, v in out.items() if not k.startswith("_") and not callable(v)}

    @strawberry.field(description="Clients currently connected through this AP/switch.")
    async def port_clients(
        self, info: Info,
    ) -> list[Annotated["Client", strawberry.lazy("unifi_api.graphql.types.network.client")]]:
        """Resolves to clients whose ap_mac matches this device's mac."""
        from unifi_api.graphql.resolvers.network import _fetch_clients
        from unifi_api.graphql.types.network.client import Client

        if not self._controller_id:
            return []
        site = self._site or "default"
        raw_clients = await _fetch_clients(info.context, self._controller_id, site)
        out: list[Client] = []
        for c in raw_clients:
            if isinstance(c, dict):
                ap_mac = c.get("ap_mac")
            else:
                raw = getattr(c, "raw", None)
                ap_mac = raw.get("ap_mac") if isinstance(raw, dict) else getattr(c, "ap_mac", None)
            if ap_mac == self.mac:
                inst = Client.from_manager_output(c)
                inst._controller_id = self._controller_id
                inst._site = site
                out.append(inst)
        return out


@strawberry.type(description="Radio configuration entry on a UniFi access point.")
class RadioEntry:
    name: str | None
    radio: str | None
    channel: int | None
    ht: int | None
    tx_power: int | None
    tx_power_mode: str | None
    current_channel: int | None
    current_tx_power: int | None
    num_sta: int | None

    @classmethod
    def from_manager_output(cls, r: Any) -> "RadioEntry":
        return cls(
            name=_get(r, "name"),
            radio=_get(r, "radio"),
            channel=_get(r, "channel"),
            ht=_get(r, "ht"),
            tx_power=_get(r, "tx_power"),
            tx_power_mode=_get(r, "tx_power_mode"),
            current_channel=_get(r, "current_channel"),
            current_tx_power=_get(r, "current_tx_power"),
            num_sta=_get(r, "num_sta"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Wrapper dict containing the radio table for a device.")
class DeviceRadio:
    """Wrapper-dict shape: manager returns ``{mac, name, model, radios: [...]}``
    (or None for non-AP devices). Pass through with light field whitelisting on
    the radio entries."""

    mac: strawberry.ID | None
    name: str | None
    model: str | None
    radios: list[RadioEntry]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "DeviceRadio":
        radios_raw = _get(obj, "radios", []) or []
        return cls(
            mac=_get(obj, "mac"),
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            radios=[RadioEntry.from_manager_output(r) for r in radios_raw],
        )

    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "name": self.name,
            "model": self.model,
            "radios": [r.to_dict() for r in self.radios],
        }


@strawberry.type(description="A single LLDP neighbor row reported by a switch.")
class LldpRow:
    local_port_idx: int | None
    chassis_id: str | None
    port_id: str | None
    system_name: str | None
    capabilities: list[str]

    @classmethod
    def from_manager_output(cls, r: Any) -> "LldpRow":
        return cls(
            local_port_idx=_get(r, "local_port_idx"),
            chassis_id=_get(r, "chassis_id"),
            port_id=_get(r, "port_id"),
            system_name=_get(r, "system_name"),
            capabilities=_get(r, "capabilities", []) or [],
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Wrapper dict containing LLDP neighbors for a switch.")
class LldpNeighbors:
    """Wrapper-dict shape: manager returns ``{name, model, lldp_table: [...]}``.
    The lldp_table rows are passed through with field whitelisting."""

    name: str | None
    model: str | None
    lldp_table: list[LldpRow]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "LldpNeighbors":
        rows = _get(obj, "lldp_table", []) or []
        return cls(
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            lldp_table=[LldpRow.from_manager_output(r) for r in rows],
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "model": self.model,
            "lldp_table": [r.to_dict() for r in self.lldp_table],
        }


def _rogue_row(obj: Any, *, is_known: bool) -> dict:
    """Project a manager rogue-AP row into the ``RogueAp`` shape. The
    ``is_known`` flag is supplied by the caller; ``RogueAp.from_manager_output``
    sets it to False since the project does not classify rogues."""

    return {
        "bssid": _get(obj, "bssid"),
        "ssid": _get(obj, "essid") or _get(obj, "ssid"),
        "channel": _get(obj, "channel"),
        "signal_dbm": _get(obj, "rssi") or _get(obj, "signal"),
        "last_seen": _get(obj, "last_seen"),
        "is_known": is_known,
    }


@strawberry.type(description="A rogue (unknown) AP detected by the controller.")
class RogueAp:
    """Detected rogue AP. ``is_known`` is hardcoded to False because the
    project does not classify rogues — the controller's API surface
    exposes only the raw scan list, with no allowlist primitive."""

    bssid: strawberry.ID | None
    ssid: str | None
    channel: int | None
    signal_dbm: int | None
    last_seen: int | None
    is_known: bool

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "bssid",
            "display_columns": ["bssid", "ssid", "channel", "signal_dbm", "last_seen"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "RogueAp":
        row = _rogue_row(obj, is_known=False)
        return cls(**row)

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A single RF-scan result row reported by an AP.")
class RfScanResult:
    bssid: strawberry.ID | None
    ssid: str | None
    channel: int | None
    signal_dbm: int | None
    captured_at: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "bssid",
            "display_columns": ["bssid", "ssid", "channel", "signal_dbm"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "RfScanResult":
        return cls(
            bssid=_get(obj, "bssid"),
            ssid=_get(obj, "essid") or _get(obj, "ssid"),
            channel=_get(obj, "channel"),
            signal_dbm=_get(obj, "rssi") or _get(obj, "signal"),
            captured_at=_get(obj, "ts") or _get(obj, "captured_at"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A wireless channel allowed by the regulatory domain.")
class AvailableChannel:
    channel: int | None
    frequency_mhz: int | None
    width_mhz: int | None
    allowed: bool

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "channel",
            "display_columns": ["channel", "frequency_mhz", "width_mhz", "allowed"],
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AvailableChannel":
        return cls(
            channel=_get(obj, "channel"),
            frequency_mhz=_get(obj, "freq") or _get(obj, "frequency_mhz"),
            width_mhz=_get(obj, "ht") or _get(obj, "width_mhz"),
            allowed=bool(_get(obj, "allowed", True)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Speedtest status reported by a UniFi gateway.")
class SpeedtestStatus:
    """Controller exposes status_download/status_upload as Mbps and latency in
    ms; status int (0=idle, 1=running) is mapped to a label."""

    status: str | None
    download_mbps: float | None
    upload_mbps: float | None
    latency_ms: int | None
    last_run: int | None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SpeedtestStatus":
        status_raw = _get(obj, "status")
        if isinstance(status_raw, int):
            status_label = "running" if status_raw == 1 else "idle"
        elif isinstance(status_raw, str):
            status_label = status_raw
        else:
            status_label = None
        return cls(
            status=status_label,
            download_mbps=_get(obj, "status_download") or _get(obj, "download_mbps"),
            upload_mbps=_get(obj, "status_upload") or _get(obj, "upload_mbps"),
            latency_ms=_get(obj, "latency") or _get(obj, "latency_ms"),
            last_run=_get(obj, "rundate") or _get(obj, "last_run"),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="A single outlet on a UniFi Smart Power PDU (UP6 / USP-Strip).")
class PduOutletEntry:
    index: int | None
    name: str | None
    has_relay: bool | None
    has_metering: bool | None
    relay_state: bool | None
    cycle_enabled: bool | None
    override_relay_state: bool | None
    override_cycle_enabled: bool | None
    has_override: bool

    @classmethod
    def from_manager_output(cls, r: Any) -> "PduOutletEntry":
        return cls(
            index=_get(r, "index"),
            name=_get(r, "name"),
            has_relay=_get(r, "has_relay"),
            has_metering=_get(r, "has_metering"),
            relay_state=_get(r, "relay_state"),
            cycle_enabled=_get(r, "cycle_enabled"),
            override_relay_state=_get(r, "override_relay_state"),
            override_cycle_enabled=_get(r, "override_cycle_enabled"),
            has_override=bool(_get(r, "has_override", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@strawberry.type(description="Wrapper dict containing per-outlet state for a Smart Power PDU.")
class PduOutlets:
    """Wrapper-dict shape: ``DeviceManager.get_pdu_outlets`` returns
    ``{mac, name, model, outlets: [...]}`` combining sensed outlet_table with
    desired outlet_overrides per outlet."""

    mac: strawberry.ID | None
    name: str | None
    model: str | None
    outlets: list[PduOutletEntry]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "PduOutlets":
        rows = _get(obj, "outlets", []) or []
        return cls(
            mac=_get(obj, "mac"),
            name=_get(obj, "name"),
            model=_get(obj, "model"),
            outlets=[PduOutletEntry.from_manager_output(r) for r in rows],
        )

    def to_dict(self) -> dict:
        return {
            "mac": self.mac,
            "name": self.name,
            "model": self.model,
            "outlets": [o.to_dict() for o in self.outlets],
        }
