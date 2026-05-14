"""Shared field models for Network device management.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.device``:

- ``Device``      — list_devices + get_device_details (mutable: name)
- ``DeviceRadio`` — get_device_radio + update_device_radio (mutable: radio update fields)

Factory helpers:
- ``from_controller``              — normalise raw dict → Device
- ``radio_from_controller``        — normalise raw radio entry dict → DeviceRadio
- ``to_controller_update``         — filter a partial Device dict to mutable keys
- ``radio_to_controller_update``   — filter a partial radio dict to mutable keys

Per-class MUTABLE_FIELDS constants drive the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Device — top-level device (mutable: name only; other mutations are actions)
# ---------------------------------------------------------------------------


class Device(BaseModel):
    """Canonical network device model.

    Most device mutations are action-shaped (reboot, locate, adopt — handled
    separately).  The only configurable field in the standard update API is
    ``name``.
    """

    # --- read-only ---
    mac: Optional[str] = Field(
        default=None,
        description="Device MAC address (primary key)",
        json_schema_extra={"mutable": False},
    )
    model: Optional[str] = Field(
        default=None,
        description="Device model identifier",
        json_schema_extra={"mutable": False},
    )
    type: Optional[str] = Field(
        default=None,
        description="Device type code (uap, usw, ugw, …)",
        json_schema_extra={"mutable": False},
    )
    version: Optional[str] = Field(
        default=None,
        description="Firmware version string",
        json_schema_extra={"mutable": False},
    )
    uptime: Optional[int] = Field(
        default=None,
        description="Device uptime in seconds",
        json_schema_extra={"mutable": False},
    )
    state: Optional[str] = Field(
        default=None,
        description="Device connection state (connected, disconnected, provisioning, …)",
        json_schema_extra={"mutable": False},
    )
    ip: Optional[str] = Field(
        default=None,
        description="Device IP address",
        json_schema_extra={"mutable": False},
    )

    # --- mutable ---
    name: Optional[str] = Field(
        default=None,
        description="Device display name (editable in the controller)",
    )


# ---------------------------------------------------------------------------
# DeviceRadio — per-band radio configuration (mutable: update fields)
# ---------------------------------------------------------------------------


class DeviceRadio(BaseModel):
    """Canonical per-radio entry model for access point radio updates.

    Mutable fields mirror the DEVICE_RADIO_UPDATE_SCHEMA.  The model is used
    to type-check and filter radio update dicts before passing them to the
    device manager.
    """

    # --- read-only context ---
    radio: Optional[str] = Field(
        default=None,
        description="Radio band identifier: na (5GHz), ng (2.4GHz), 6e (6GHz)",
        json_schema_extra={"mutable": False},
    )

    # --- mutable (accepted by update) ---
    tx_power_mode: Optional[str] = Field(
        default=None,
        description="Transmit power mode: auto, high, medium, low, custom",
    )
    tx_power: Optional[int] = Field(
        default=None,
        description="Custom transmit power in dBm (only used when tx_power_mode is 'custom')",
    )
    channel: Optional[int] = Field(
        default=None,
        description="Channel number (0 for auto)",
    )
    ht: Optional[str] = Field(
        default=None,
        description="Channel width: 20, 40, 80, 160, or 320 MHz",
    )
    min_rssi_enabled: Optional[bool] = Field(
        default=None,
        description="Enable minimum RSSI client filtering",
    )
    min_rssi: Optional[int] = Field(
        default=None,
        description="Minimum RSSI threshold in dBm",
    )
    assisted_roaming_enabled: Optional[bool] = Field(
        default=None,
        description="Enable 802.11k/v assisted roaming",
    )
    antenna_gain: Optional[int] = Field(
        default=None,
        description="External antenna gain in dBi",
    )
    vwire_enabled: Optional[bool] = Field(
        default=None,
        description="Enable virtual wire mode",
    )
    sens_level_enabled: Optional[bool] = Field(
        default=None,
        description="Enable receive sensitivity level adjustment",
    )
    sens_level: Optional[int] = Field(
        default=None,
        description="Receive sensitivity level in dBm",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

DEVICE_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in Device.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

DEVICE_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name for name, field in Device.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True) is False
)

DEVICERADIO_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in DeviceRadio.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

DEVICERADIO_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in DeviceRadio.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)

# Module-level alias for generic usage
MUTABLE_FIELDS = DEVICE_MUTABLE_FIELDS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public factory helpers — Device
# ---------------------------------------------------------------------------


def from_controller(raw: Any) -> Device:
    """Build a Device from a controller API response dict."""
    state_raw = _get(raw, "state")
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
    return Device(
        mac=_get(raw, "mac"),
        name=_get(raw, "name"),
        model=_get(raw, "model"),
        type=_get(raw, "type"),
        version=_get(raw, "version"),
        uptime=_get(raw, "uptime"),
        state=_STATE_MAP.get(state_raw, str(state_raw) if state_raw is not None else None),
        ip=_get(raw, "ip"),
    )


def to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial Device dict to only mutable, recognised keys.

    Currently only ``name`` is mutable on the Device document.
    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in DEVICE_MUTABLE_FIELDS and v is not None}


# ---------------------------------------------------------------------------
# Public factory helpers — DeviceRadio
# ---------------------------------------------------------------------------


def radio_from_controller(raw: Any) -> DeviceRadio:
    """Build a DeviceRadio (single radio entry) from a controller radio_table row."""
    return DeviceRadio(
        radio=_get(raw, "radio"),
        tx_power_mode=_get(raw, "tx_power_mode"),
        tx_power=_get(raw, "tx_power"),
        channel=_get(raw, "channel"),
        ht=_get(raw, "ht"),
        min_rssi_enabled=_get(raw, "min_rssi_enabled"),
        min_rssi=_get(raw, "min_rssi"),
        assisted_roaming_enabled=_get(raw, "assisted_roaming_enabled"),
        antenna_gain=_get(raw, "antenna_gain"),
        vwire_enabled=_get(raw, "vwire_enabled"),
        sens_level_enabled=_get(raw, "sens_level_enabled"),
        sens_level=_get(raw, "sens_level"),
    )


def radio_to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial radio update dict to only mutable, recognised keys.

    Read-only fields (radio) and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in DEVICERADIO_MUTABLE_FIELDS and v is not None}
