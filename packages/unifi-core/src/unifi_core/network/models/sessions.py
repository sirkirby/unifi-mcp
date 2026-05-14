"""Shared field models for Network client session resources.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.session``:

- ``ClientSession``    — get_client_sessions (hotspot/captive portal sessions)
- ``ClientWifiDetails`` — get_client_wifi_details (current WiFi parameters)

Both classes are read-only (no create/update/delete tools).

Factory helpers:
- ``client_session_from_controller``     — normalise raw → ClientSession
- ``client_wifi_details_from_controller`` — normalise raw → ClientWifiDetails

MUTABLE_FIELDS = frozenset() for both classes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Return the first non-None value among the listed keys."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


# ---------------------------------------------------------------------------
# ClientSession
# ---------------------------------------------------------------------------


class ClientSession(BaseModel):
    """Historical client association session entry (hotspot/captive portal)."""

    mac: Optional[str] = Field(
        default=None,
        description="Client MAC address",
        json_schema_extra={"mutable": False},
    )
    hostname: Optional[str] = Field(
        default=None,
        description="Client hostname or display name",
        json_schema_extra={"mutable": False},
    )
    ap: Optional[str] = Field(
        default=None,
        description="Access point MAC the client was associated with",
        json_schema_extra={"mutable": False},
    )
    ssid: Optional[str] = Field(
        default=None,
        description="SSID the client was connected to",
        json_schema_extra={"mutable": False},
    )
    connected_at: Optional[int] = Field(
        default=None,
        description="Unix epoch timestamp of association start",
        json_schema_extra={"mutable": False},
    )
    disconnected_at: Optional[int] = Field(
        default=None,
        description="Unix epoch timestamp of disassociation",
        json_schema_extra={"mutable": False},
    )
    duration: Optional[int] = Field(
        default=None,
        description="Session duration in seconds",
        json_schema_extra={"mutable": False},
    )


CLIENTSESSION_MUTABLE_FIELDS: frozenset[str] = frozenset()
CLIENTSESSION_READ_ONLY_FIELDS: frozenset[str] = frozenset(ClientSession.model_fields.keys())


def client_session_from_controller(record: Any) -> ClientSession:
    """Build a ClientSession from a controller API response dict."""
    if not isinstance(record, dict):
        return ClientSession()
    return ClientSession(
        mac=_get(record, "mac"),
        hostname=_get(record, "hostname", "name"),
        ap=_get(record, "ap", "ap_mac"),
        ssid=_get(record, "essid", "ssid"),
        connected_at=_get(record, "assoc_time", "connected_at", "first_seen"),
        disconnected_at=_get(record, "disassoc_time", "disconnected_at", "last_seen"),
        duration=_get(record, "duration"),
    )


# ---------------------------------------------------------------------------
# ClientWifiDetails
# ---------------------------------------------------------------------------


class ClientWifiDetails(BaseModel):
    """Current WiFi parameters for a single wireless client."""

    mac: Optional[str] = Field(
        default=None,
        description="Client MAC address",
        json_schema_extra={"mutable": False},
    )
    ssid: Optional[str] = Field(
        default=None,
        description="SSID the client is connected to",
        json_schema_extra={"mutable": False},
    )
    ap: Optional[str] = Field(
        default=None,
        description="Associated AP MAC address",
        json_schema_extra={"mutable": False},
    )
    signal: Optional[int] = Field(
        default=None,
        description="Signal strength in dBm",
        json_schema_extra={"mutable": False},
    )
    tx_rate: Optional[int] = Field(
        default=None,
        description="Transmit rate in Kbps",
        json_schema_extra={"mutable": False},
    )
    rx_rate: Optional[int] = Field(
        default=None,
        description="Receive rate in Kbps",
        json_schema_extra={"mutable": False},
    )
    channel: Optional[int] = Field(
        default=None,
        description="WiFi channel number",
        json_schema_extra={"mutable": False},
    )


CLIENTWIFIDETAILS_MUTABLE_FIELDS: frozenset[str] = frozenset()
CLIENTWIFIDETAILS_READ_ONLY_FIELDS: frozenset[str] = frozenset(ClientWifiDetails.model_fields.keys())

# Module-level alias (symmetry test fallback)
MUTABLE_FIELDS = CLIENTSESSION_MUTABLE_FIELDS


def client_wifi_details_from_controller(obj: Any) -> ClientWifiDetails:
    """Build a ClientWifiDetails from a controller API response."""
    if obj is None:
        return ClientWifiDetails()
    if not isinstance(obj, dict):
        raw = getattr(obj, "raw", None)
        obj = raw if isinstance(raw, dict) else {}
    return ClientWifiDetails(
        mac=_get(obj, "mac"),
        ssid=_get(obj, "essid", "ssid"),
        ap=_get(obj, "ap_mac", "ap"),
        signal=_get(obj, "signal", "rssi"),
        tx_rate=_get(obj, "tx_rate"),
        rx_rate=_get(obj, "rx_rate"),
        channel=_get(obj, "channel"),
    )
