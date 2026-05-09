"""Strawberry types for network/system.

Phase 6 PR2 Task 23 migration target. Nine read shapes that used to live
in ``unifi_api.serializers.network.system``:

- ``Alarm`` — ``unifi_list_alarms`` (LIST)
- ``Backup`` — ``unifi_list_backups`` (LIST)
- ``SystemInfo`` — ``unifi_get_system_info`` (DETAIL)
- ``NetworkHealth`` — ``unifi_get_network_health`` (LIST; manager returns
                      multi-element list of subsystems)
- ``SiteSettings`` — ``unifi_get_site_settings`` (DETAIL)
- ``SnmpSettings`` — ``unifi_get_snmp_settings`` (DETAIL; manager returns
                     ``list[dict]``, type unwraps the first item)
- ``EventTypes`` — ``unifi_get_event_types`` (DETAIL; wraps the list under
                   a stable ``event_types`` key)
- ``AutoBackupSettings`` — ``unifi_get_autobackup_settings`` (DETAIL)
- ``TopClient`` — ``unifi_get_top_clients`` (LIST)
- ``SpeedtestResult`` — ``unifi_get_speedtest_results`` (LIST)

The mutation ack (``SystemMutationAckSerializer``) stays in the original
module for archive/backup/autobackup dispatch.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import strawberry


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


@strawberry.type(description="A controller alarm (V1 /list/alarm entry).")
class Alarm:
    id: strawberry.ID | None
    key: str | None
    msg: str | None
    archived: bool
    time: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["time", "key", "msg", "archived"],
            "sort_default": "time:desc",
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "Alarm":
        if not isinstance(record, dict):
            return cls(
                id=None, key=None, msg=None, archived=False,
                time=None, _was_dict=False,
            )
        return cls(
            id=_get(record, "_id", "id"),
            key=_get(record, "key", "event_type"),
            msg=_get(record, "msg", "message"),
            archived=bool(record.get("archived", False)),
            time=_get(record, "time", "timestamp"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {"id": None}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="A controller backup file metadata record.")
class Backup:
    id: strawberry.ID | None
    filename: str | None
    size: int | None
    created_at: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["filename", "size", "created_at"],
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "Backup":
        if not isinstance(record, dict):
            return cls(
                id=None, filename=None, size=None, created_at=None,
                _was_dict=False,
            )
        return cls(
            id=_get(record, "_id", "id"),
            filename=_get(record, "filename", "name"),
            size=_get(record, "size"),
            created_at=_get(record, "time", "created_at", "timestamp"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {"id": None}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="Controller system information.")
class SystemInfo:
    name: str | None
    version: str | None
    hostname: str | None
    uptime: int | None
    num_devices: int | None
    num_clients: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SystemInfo":
        if not isinstance(obj, dict):
            return cls(
                name=None, version=None, hostname=None, uptime=None,
                num_devices=None, num_clients=None, _was_dict=False,
            )
        return cls(
            name=_get(obj, "name", "controller_name"),
            version=_get(obj, "version", "build"),
            hostname=_get(obj, "hostname", "host"),
            uptime=_get(obj, "uptime"),
            num_devices=_get(obj, "num_devices"),
            num_clients=_get(obj, "num_clients"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="A network-health subsystem entry.")
class NetworkHealth:
    subsystem: str | None
    status: str | None
    num_user: int | None
    num_guest: int | None
    num_iot: int | None
    rx_bytes: int | None
    tx_bytes: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "subsystem",
            "display_columns": [
                "subsystem", "status", "num_user", "rx_bytes", "tx_bytes",
            ],
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "NetworkHealth":
        if not isinstance(record, dict):
            return cls(
                subsystem=None, status=None, num_user=None, num_guest=None,
                num_iot=None, rx_bytes=None, tx_bytes=None, _was_dict=False,
            )
        return cls(
            subsystem=_get(record, "subsystem"),
            status=_get(record, "status"),
            num_user=_get(record, "num_user"),
            num_guest=_get(record, "num_guest"),
            num_iot=_get(record, "num_iot"),
            rx_bytes=_get(record, "rx_bytes-r", "rx_bytes"),
            tx_bytes=_get(record, "tx_bytes-r", "tx_bytes"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="Controller site settings.")
class SiteSettings:
    site_id: str | None
    name: str | None
    role: str | None
    country: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SiteSettings":
        if not isinstance(obj, dict):
            return cls(
                site_id=None, name=None, role=None, country=None,
                _was_dict=False,
            )

        # The system manager returns ``{"raw": [...], "sections": {key: dict}}``.
        # Pull display fields from the sections that own them: super_identity
        # owns the site display name and the controller's persisted ``_id``;
        # country owns the regulatory code. Sections that don't exist on this
        # firmware simply leave the field None.
        sections = obj.get("sections") if isinstance(obj.get("sections"), dict) else {}
        identity = sections.get("super_identity", {}) if isinstance(sections.get("super_identity"), dict) else {}
        country_section = sections.get("country", {}) if isinstance(sections.get("country"), dict) else {}

        site_id = _get(identity, "_id", "site_id") or _get(obj, "_id", "site_id")
        name = _get(identity, "name") or _get(obj, "name")
        role = _get(identity, "role") or _get(obj, "role")
        country_raw = _get(country_section, "code") or _get(obj, "country")
        try:
            country = int(country_raw) if country_raw is not None else None
        except (TypeError, ValueError):
            country = None

        return cls(
            site_id=site_id,
            name=name,
            role=role,
            country=country,
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="Controller SNMP settings.")
class SnmpSettings:
    enabled: bool
    community: str | None
    port: int | None
    version: str | None
    _had_payload: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "SnmpSettings":
        # Manager returns list[dict]; type unwraps first item to match the
        # legacy serializer contract.
        if isinstance(obj, list):
            obj = obj[0] if obj else {}
        if not isinstance(obj, dict):
            return cls(
                enabled=False, community=None, port=None, version=None,
                _had_payload=False,
            )
        return cls(
            enabled=bool(obj.get("enabled", False)),
            community=_get(obj, "community", default=""),
            port=_get(obj, "port"),
            version=_get(obj, "version"),
            _had_payload=True,
        )

    def to_dict(self) -> dict:
        if not self._had_payload:
            return {}
        d = asdict(self)
        d.pop("_had_payload", None)
        return d


@strawberry.type(description="Wrapper for event-type prefix descriptors.")
class EventTypes:
    # The catalog of event-type prefixes is unstructured (varies by
    # firmware), so each descriptor passes through as a plain dict.
    # Exposed as a ``JSON`` scalar on the GraphQL surface so the
    # heterogeneous payload survives without an enumerated sub-type.
    event_types: strawberry.scalars.JSON  # type: ignore[name-defined]

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "EventTypes":
        if isinstance(obj, list):
            return cls(
                event_types=[e for e in obj if isinstance(e, dict)],
            )
        if isinstance(obj, dict):
            inner = obj.get("event_types")
            if isinstance(inner, list):
                return cls(event_types=list(inner))
            return cls(event_types=[obj])
        return cls(event_types=[])

    def to_dict(self) -> dict:
        return {"event_types": list(self.event_types)}


@strawberry.type(description="Auto-backup schedule + retention settings.")
class AutoBackupSettings:
    enabled: bool
    schedule: str | None
    max_count: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "AutoBackupSettings":
        if not isinstance(obj, dict):
            return cls(
                enabled=False, schedule=None, max_count=None,
                _was_dict=False,
            )
        return cls(
            enabled=bool(obj.get("enabled", False)),
            schedule=_get(obj, "schedule", "cron"),
            max_count=_get(obj, "max_count", "max_backups"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="A top-traffic client entry.")
class TopClient:
    mac: str | None
    hostname: str | None
    tx_bytes: int | None
    rx_bytes: int | None
    total_bytes: int | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "mac",
            "display_columns": ["mac", "hostname", "total_bytes"],
            "sort_default": "total_bytes:desc",
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "TopClient":
        if not isinstance(record, dict):
            return cls(
                mac=None, hostname=None, tx_bytes=None, rx_bytes=None,
                total_bytes=None, _was_dict=False,
            )
        return cls(
            mac=_get(record, "mac"),
            hostname=_get(record, "name", "hostname"),
            tx_bytes=_get(record, "tx_bytes"),
            rx_bytes=_get(record, "rx_bytes"),
            total_bytes=_get(record, "total_bytes", "bytes"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {"mac": None}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d


@strawberry.type(description="A speedtest result entry.")
class SpeedtestResult:
    timestamp: int | None
    download_mbps: float | None
    upload_mbps: float | None
    latency_ms: float | None
    _was_dict: strawberry.Private[bool] = True

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "display_columns": [
                "timestamp", "download_mbps", "upload_mbps", "latency_ms",
            ],
            "sort_default": "timestamp:desc",
        }

    @classmethod
    def from_manager_output(cls, record: Any) -> "SpeedtestResult":
        if not isinstance(record, dict):
            return cls(
                timestamp=None, download_mbps=None, upload_mbps=None,
                latency_ms=None, _was_dict=False,
            )
        return cls(
            timestamp=_get(record, "time", "timestamp"),
            download_mbps=_get(record, "xput_download", "download_mbps"),
            upload_mbps=_get(record, "xput_upload", "upload_mbps"),
            latency_ms=_get(record, "latency", "latency_ms"),
            _was_dict=True,
        )

    def to_dict(self) -> dict:
        if not self._was_dict:
            return {}
        d = asdict(self)
        d.pop("_was_dict", None)
        return d
