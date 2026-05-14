"""Strawberry types for network/sessions.

Phase 6 PR2 Task 23 migration target. Two read shapes that used to live in
``unifi_api.serializers.network.sessions``:

- ``ClientSession`` — ``unifi_get_client_sessions`` (LIST). Historical
                       association sessions with ``connected_at`` /
                       ``disconnected_at`` and duration.
- ``ClientWifiDetails`` — ``unifi_get_client_wifi_details`` (DETAIL).
                          Current WiFi parameters for a specific client
                          (signal, rates, channel).

Each type's ``from_manager_output(raw)`` classmethod replaces the dict-shaping
logic that used to live in serializers/network/sessions.py.
``to_dict()`` exposes the same dict contract the REST routes return today.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Return the first non-None value among the listed keys."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


@strawberry.type(description="A client association session entry.")
class ClientSession:
    mac: str | None
    hostname: str | None
    ap: str | None
    ssid: str | None
    connected_at: int | None
    disconnected_at: int | None
    duration: int | None
    # Tracks whether the source record was a dict (legacy serializer
    # returned ``{}`` for non-dict inputs; ``True`` for any dict source).
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "connected_at",
            "display_columns": [
                "mac",
                "hostname",
                "ssid",
                "connected_at",
                "duration",
            ],
            "sort_default": "connected_at:desc",
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "ClientSession":
        if not isinstance(record, dict):
            return cls(
                mac=None,
                hostname=None,
                ap=None,
                ssid=None,
                connected_at=None,
                disconnected_at=None,
                duration=None,
                _was_dict=False,
            )
        return cls(
            mac=_get(record, "mac"),
            hostname=_get(record, "hostname", "name"),
            ap=_get(record, "ap", "ap_mac"),
            ssid=_get(record, "essid", "ssid"),
            connected_at=_get(record, "assoc_time", "connected_at", "first_seen"),
            disconnected_at=_get(record, "disassoc_time", "disconnected_at", "last_seen"),
            duration=_get(record, "duration"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="Current WiFi parameters for a client.")
class ClientWifiDetails:
    mac: str | None
    ssid: str | None
    ap: str | None
    signal: int | None
    tx_rate: int | None
    rx_rate: int | None
    channel: int | None
    # Tracks whether the source was None (legacy serializer returned ``{}``
    # for ``None`` inputs).
    _was_none: strawberry.Private[bool] = False

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "ClientWifiDetails":
        if obj is None:
            return cls(
                mac=None,
                ssid=None,
                ap=None,
                signal=None,
                tx_rate=None,
                rx_rate=None,
                channel=None,
                _was_none=True,
            )
        if not isinstance(obj, dict):
            raw = getattr(obj, "raw", None)
            obj = raw if isinstance(raw, dict) else {}
        return cls(
            mac=_get(obj, "mac"),
            ssid=_get(obj, "essid", "ssid"),
            ap=_get(obj, "ap_mac", "ap"),
            signal=_get(obj, "signal", "rssi"),
            tx_rate=_get(obj, "tx_rate"),
            rx_rate=_get(obj, "rx_rate"),
            channel=_get(obj, "channel"),
        )

    def to_dict(self) -> dict:
        if self._was_none:
            return {}
        d = asdict(self)
        d.pop("_was_none", None)
        return d
