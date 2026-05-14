"""Shared field models for Network system settings.

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.system``:

Scope-A classes (CRUD):
- ``SnmpSettings``        — get_snmp_settings + update_snmp_settings
- ``AutoBackupSettings``  — get_autobackup_settings + update_autobackup_settings

Scope-B classes (read-only):
- ``SystemInfo``     — get_system_info
- ``NetworkHealth``  — get_network_health
- ``Alarm``          — list_alarms
- ``Backup``         — list_backups
- ``SiteSettings``   — get_site_settings
- ``EventTypes``     — get_event_types
- ``TopClient``      — get_top_clients
- ``SpeedtestResult`` — get_speedtest_results

Factory helpers:
- ``snmp_from_controller``         — normalise raw → SnmpSettings
- ``autobackup_from_controller``   — normalise raw → AutoBackupSettings
- ``snmp_to_controller_update``    — filter partial dict to SNMP mutable keys
- ``autobackup_to_controller_update`` — filter partial dict to autobackup mutable keys
- ``system_info_from_controller``  — normalise raw → SystemInfo
- ``network_health_from_controller`` — normalise raw → NetworkHealth
- ``alarm_from_controller``        — normalise raw → Alarm
- ``backup_from_controller``       — normalise raw → Backup
- ``site_settings_from_controller`` — normalise raw → SiteSettings
- ``event_types_from_controller``  — normalise raw → EventTypes
- ``top_client_from_controller``   — normalise raw → TopClient
- ``speedtest_result_from_controller`` — normalise raw → SpeedtestResult

Per-class MUTABLE_FIELDS constants drive the cross-layer symmetry test.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# SnmpSettings
# ---------------------------------------------------------------------------


class SnmpSettings(BaseModel):
    """Canonical SNMP settings model."""

    # --- mutable ---
    enabled: Optional[bool] = Field(
        default=None,
        description="Enable or disable SNMP on the site",
    )
    community: Optional[str] = Field(
        default=None,
        description="SNMP community string (e.g., 'public')",
    )

    # --- read-only context ---
    port: Optional[int] = Field(
        default=None,
        description="SNMP listen port (read-only; set by controller)",
        json_schema_extra={"mutable": False},
    )
    version: Optional[str] = Field(
        default=None,
        description="SNMP version (read-only; set by controller)",
        json_schema_extra={"mutable": False},
    )


# ---------------------------------------------------------------------------
# AutoBackupSettings
# ---------------------------------------------------------------------------


class AutoBackupSettings(BaseModel):
    """Canonical auto-backup schedule and retention settings model.

    Field names match the controller's autobackup section keys
    (``autobackup_enabled``, ``autobackup_cron_expr``, etc.) so the
    pydantic model maps directly to the update payload without translation.
    """

    # --- mutable ---
    autobackup_enabled: Optional[bool] = Field(
        default=None,
        description="Enable or disable automatic backups",
    )
    autobackup_cron_expr: Optional[str] = Field(
        default=None,
        description="Cron expression for backup schedule (e.g., '30 2 * * *')",
    )
    autobackup_days: Optional[int] = Field(
        default=None,
        description="Backup retention in days (0 = use max_files instead)",
    )
    autobackup_max_files: Optional[int] = Field(
        default=None,
        description="Maximum number of backup files to keep",
    )
    autobackup_timezone: Optional[str] = Field(
        default=None,
        description="Timezone for backup schedule (e.g., 'America/Denver')",
    )
    autobackup_cloud_enabled: Optional[bool] = Field(
        default=None,
        description="Enable cloud backup storage",
    )


# ---------------------------------------------------------------------------
# Field sets
# ---------------------------------------------------------------------------

SNMPSETTINGS_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name for name, field in SnmpSettings.model_fields.items() if (field.json_schema_extra or {}).get("mutable", True)
)

SNMPSETTINGS_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in SnmpSettings.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)

AUTOBACKUPSETTINGS_MUTABLE_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in AutoBackupSettings.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True)
)

AUTOBACKUPSETTINGS_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    name
    for name, field in AutoBackupSettings.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True) is False
)

# Module-level alias
MUTABLE_FIELDS = SNMPSETTINGS_MUTABLE_FIELDS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    if isinstance(obj, list):
        obj = obj[0] if obj else {}
    if not isinstance(obj, dict):
        return default
    for k in keys:
        v = obj.get(k)
        if v is not None:
            return v
    return default


# ---------------------------------------------------------------------------
# Public factory helpers — SnmpSettings
# ---------------------------------------------------------------------------


def snmp_from_controller(raw: Any) -> SnmpSettings:
    """Build a SnmpSettings from a controller API response.

    The controller returns SNMP settings as a list; this unwraps the first element.
    """
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    return SnmpSettings(
        enabled=_get(raw, "enabled"),
        community=_get(raw, "community"),
        port=_get(raw, "port"),
        version=_get(raw, "version"),
    )


def snmp_to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only SNMP mutable keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in SNMPSETTINGS_MUTABLE_FIELDS and v is not None}


# ---------------------------------------------------------------------------
# Public factory helpers — AutoBackupSettings
# ---------------------------------------------------------------------------


def autobackup_from_controller(raw: Any) -> AutoBackupSettings:
    """Build an AutoBackupSettings from a controller API response dict."""
    if not isinstance(raw, dict):
        return AutoBackupSettings()
    return AutoBackupSettings(
        autobackup_enabled=raw.get("autobackup_enabled")
        if raw.get("autobackup_enabled") is not None
        else raw.get("enabled"),
        autobackup_cron_expr=raw.get("autobackup_cron_expr") or raw.get("cron"),
        autobackup_days=raw.get("autobackup_days"),
        autobackup_max_files=raw.get("autobackup_max_files") or raw.get("max_backups"),
        autobackup_timezone=raw.get("autobackup_timezone") or raw.get("timezone"),
        autobackup_cloud_enabled=raw.get("autobackup_cloud_enabled"),
    )


def autobackup_to_controller_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Filter a partial dict to only autobackup mutable keys.

    Read-only fields and unrecognised keys are dropped.
    ``None`` values are dropped; boolean ``False`` is preserved.
    """
    return {k: v for k, v in fields.items() if k in AUTOBACKUPSETTINGS_MUTABLE_FIELDS and v is not None}


# ===========================================================================
# Scope-B read-only models
# ===========================================================================


# ---------------------------------------------------------------------------
# SystemInfo
# ---------------------------------------------------------------------------


class SystemInfo(BaseModel):
    """Controller system information (read-only)."""

    name: Optional[str] = Field(
        default=None,
        description="Controller name",
        json_schema_extra={"mutable": False},
    )
    version: Optional[str] = Field(
        default=None,
        description="Controller software version",
        json_schema_extra={"mutable": False},
    )
    hostname: Optional[str] = Field(
        default=None,
        description="Hostname of the controller",
        json_schema_extra={"mutable": False},
    )
    uptime: Optional[int] = Field(
        default=None,
        description="Controller uptime in seconds",
        json_schema_extra={"mutable": False},
    )
    num_devices: Optional[int] = Field(
        default=None,
        description="Number of managed devices",
        json_schema_extra={"mutable": False},
    )
    num_clients: Optional[int] = Field(
        default=None,
        description="Number of connected clients",
        json_schema_extra={"mutable": False},
    )


SYSTEMINFO_MUTABLE_FIELDS: frozenset[str] = frozenset()
SYSTEMINFO_READ_ONLY_FIELDS: frozenset[str] = frozenset(SystemInfo.model_fields.keys())


def system_info_from_controller(raw: Any) -> SystemInfo:
    """Build a SystemInfo from a controller API response dict."""
    if not isinstance(raw, dict):
        return SystemInfo()
    return SystemInfo(
        name=_get(raw, "name", "controller_name"),
        version=_get(raw, "version", "build"),
        hostname=_get(raw, "hostname", "host"),
        uptime=_get(raw, "uptime"),
        num_devices=_get(raw, "num_devices"),
        num_clients=_get(raw, "num_clients"),
    )


# ---------------------------------------------------------------------------
# NetworkHealth
# ---------------------------------------------------------------------------


class NetworkHealth(BaseModel):
    """A network-health subsystem entry (read-only)."""

    subsystem: Optional[str] = Field(
        default=None,
        description="Subsystem name (e.g., 'wan', 'lan', 'wlan')",
        json_schema_extra={"mutable": False},
    )
    status: Optional[str] = Field(
        default=None,
        description="Subsystem health status",
        json_schema_extra={"mutable": False},
    )
    num_user: Optional[int] = Field(
        default=None,
        description="Number of user clients on this subsystem",
        json_schema_extra={"mutable": False},
    )
    num_guest: Optional[int] = Field(
        default=None,
        description="Number of guest clients on this subsystem",
        json_schema_extra={"mutable": False},
    )
    num_iot: Optional[int] = Field(
        default=None,
        description="Number of IoT clients on this subsystem",
        json_schema_extra={"mutable": False},
    )
    rx_bytes: Optional[int] = Field(
        default=None,
        description="Received bytes on this subsystem",
        json_schema_extra={"mutable": False},
    )
    tx_bytes: Optional[int] = Field(
        default=None,
        description="Transmitted bytes on this subsystem",
        json_schema_extra={"mutable": False},
    )


NETWORKHEALTH_MUTABLE_FIELDS: frozenset[str] = frozenset()
NETWORKHEALTH_READ_ONLY_FIELDS: frozenset[str] = frozenset(NetworkHealth.model_fields.keys())


def network_health_from_controller(raw: Any) -> NetworkHealth:
    """Build a NetworkHealth from a single subsystem dict."""
    if not isinstance(raw, dict):
        return NetworkHealth()
    return NetworkHealth(
        subsystem=_get(raw, "subsystem"),
        status=_get(raw, "status"),
        num_user=_get(raw, "num_user"),
        num_guest=_get(raw, "num_guest"),
        num_iot=_get(raw, "num_iot"),
        rx_bytes=raw.get("rx_bytes-r") or raw.get("rx_bytes"),
        tx_bytes=raw.get("tx_bytes-r") or raw.get("tx_bytes"),
    )


# ---------------------------------------------------------------------------
# Alarm
# ---------------------------------------------------------------------------


class Alarm(BaseModel):
    """A controller alarm entry (read-only)."""

    id: Optional[str] = Field(
        default=None,
        description="Alarm identifier",
        json_schema_extra={"mutable": False},
    )
    key: Optional[str] = Field(
        default=None,
        description="Alarm key / event type",
        json_schema_extra={"mutable": False},
    )
    msg: Optional[str] = Field(
        default=None,
        description="Human-readable alarm message",
        json_schema_extra={"mutable": False},
    )
    archived: bool = Field(
        default=False,
        description="Whether the alarm has been archived",
        json_schema_extra={"mutable": False},
    )
    time: Optional[int] = Field(
        default=None,
        description="Unix timestamp of the alarm",
        json_schema_extra={"mutable": False},
    )


ALARM_MUTABLE_FIELDS: frozenset[str] = frozenset()
ALARM_READ_ONLY_FIELDS: frozenset[str] = frozenset(Alarm.model_fields.keys())


def alarm_from_controller(raw: Any) -> Alarm:
    """Build an Alarm from a controller API response dict."""
    if not isinstance(raw, dict):
        return Alarm()
    return Alarm(
        id=_get(raw, "_id", "id"),
        key=_get(raw, "key", "event_type"),
        msg=_get(raw, "msg", "message"),
        archived=bool(raw.get("archived", False)),
        time=_get(raw, "time", "timestamp"),
    )


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


class Backup(BaseModel):
    """A controller backup file metadata record (read-only)."""

    id: Optional[str] = Field(
        default=None,
        description="Backup identifier",
        json_schema_extra={"mutable": False},
    )
    filename: Optional[str] = Field(
        default=None,
        description="Backup filename",
        json_schema_extra={"mutable": False},
    )
    size: Optional[int] = Field(
        default=None,
        description="Backup file size in bytes",
        json_schema_extra={"mutable": False},
    )
    created_at: Optional[int] = Field(
        default=None,
        description="Unix timestamp of backup creation",
        json_schema_extra={"mutable": False},
    )


BACKUP_MUTABLE_FIELDS: frozenset[str] = frozenset()
BACKUP_READ_ONLY_FIELDS: frozenset[str] = frozenset(Backup.model_fields.keys())


def backup_from_controller(raw: Any) -> Backup:
    """Build a Backup from a controller API response dict."""
    if not isinstance(raw, dict):
        return Backup()
    return Backup(
        id=_get(raw, "_id", "id"),
        filename=_get(raw, "filename", "name"),
        size=_get(raw, "size"),
        created_at=_get(raw, "time", "created_at", "timestamp"),
    )


# ---------------------------------------------------------------------------
# SiteSettings
# ---------------------------------------------------------------------------


class SiteSettings(BaseModel):
    """Controller site settings (read-only)."""

    site_id: Optional[str] = Field(
        default=None,
        description="Site identifier",
        json_schema_extra={"mutable": False},
    )
    name: Optional[str] = Field(
        default=None,
        description="Site display name",
        json_schema_extra={"mutable": False},
    )
    role: Optional[str] = Field(
        default=None,
        description="Site role (e.g., 'master', 'slave')",
        json_schema_extra={"mutable": False},
    )
    country: Optional[int] = Field(
        default=None,
        description="Regulatory country code (numeric)",
        json_schema_extra={"mutable": False},
    )


SITESETTINGS_MUTABLE_FIELDS: frozenset[str] = frozenset()
SITESETTINGS_READ_ONLY_FIELDS: frozenset[str] = frozenset(SiteSettings.model_fields.keys())


def site_settings_from_controller(raw: Any) -> SiteSettings:
    """Build a SiteSettings from a controller API response.

    The system manager returns ``{"raw": [...], "sections": {key: dict}}``.
    Pull display fields from the sections that own them: ``super_identity``
    owns the site display name and the controller's persisted ``_id``;
    ``country`` owns the regulatory code.
    """
    if not isinstance(raw, dict):
        return SiteSettings()

    sections = raw.get("sections") if isinstance(raw.get("sections"), dict) else {}
    identity = sections.get("super_identity", {}) if isinstance(sections.get("super_identity"), dict) else {}
    country_section = sections.get("country", {}) if isinstance(sections.get("country"), dict) else {}

    site_id = _get(identity, "_id", "site_id") or _get(raw, "_id", "site_id")
    name = _get(identity, "name") or _get(raw, "name")
    role = _get(identity, "role") or _get(raw, "role")
    country_raw = _get(country_section, "code") or _get(raw, "country")
    try:
        country = int(country_raw) if country_raw is not None else None
    except (TypeError, ValueError):
        country = None

    return SiteSettings(
        site_id=site_id,
        name=name,
        role=role,
        country=country,
    )


# ---------------------------------------------------------------------------
# EventTypes
# ---------------------------------------------------------------------------


class EventTypes(BaseModel):
    """Wrapper for event-type prefix descriptors (read-only).

    The catalog of event-type prefixes is unstructured (varies by firmware),
    so each descriptor passes through as a plain list exposed as JSON.
    """

    event_types: Optional[List[Any]] = Field(
        default=None,
        description="List of event-type descriptor dicts",
        json_schema_extra={"mutable": False},
    )


EVENTTYPES_MUTABLE_FIELDS: frozenset[str] = frozenset()
EVENTTYPES_READ_ONLY_FIELDS: frozenset[str] = frozenset(EventTypes.model_fields.keys())


def event_types_from_controller(raw: Any) -> EventTypes:
    """Build an EventTypes from a controller API response."""
    if isinstance(raw, list):
        return EventTypes(event_types=[e for e in raw if isinstance(e, dict)])
    if isinstance(raw, dict):
        inner = raw.get("event_types")
        if isinstance(inner, list):
            return EventTypes(event_types=list(inner))
        return EventTypes(event_types=[raw])
    return EventTypes(event_types=[])


# ---------------------------------------------------------------------------
# TopClient
# ---------------------------------------------------------------------------


class TopClient(BaseModel):
    """A top-traffic client entry (read-only)."""

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
    tx_bytes: Optional[int] = Field(
        default=None,
        description="Bytes transmitted by this client",
        json_schema_extra={"mutable": False},
    )
    rx_bytes: Optional[int] = Field(
        default=None,
        description="Bytes received by this client",
        json_schema_extra={"mutable": False},
    )
    total_bytes: Optional[int] = Field(
        default=None,
        description="Total bytes (tx + rx) for this client",
        json_schema_extra={"mutable": False},
    )


TOPCLIENT_MUTABLE_FIELDS: frozenset[str] = frozenset()
TOPCLIENT_READ_ONLY_FIELDS: frozenset[str] = frozenset(TopClient.model_fields.keys())


def top_client_from_controller(raw: Any) -> TopClient:
    """Build a TopClient from a controller API response dict."""
    if not isinstance(raw, dict):
        return TopClient()
    return TopClient(
        mac=_get(raw, "mac"),
        hostname=_get(raw, "name", "hostname"),
        tx_bytes=_get(raw, "tx_bytes"),
        rx_bytes=_get(raw, "rx_bytes"),
        total_bytes=_get(raw, "total_bytes", "bytes"),
    )


# ---------------------------------------------------------------------------
# SpeedtestResult
# ---------------------------------------------------------------------------


class SpeedtestResult(BaseModel):
    """A speedtest result entry (read-only)."""

    timestamp: Optional[int] = Field(
        default=None,
        description="Unix timestamp of the speedtest",
        json_schema_extra={"mutable": False},
    )
    download_mbps: Optional[float] = Field(
        default=None,
        description="Download speed in Mbps",
        json_schema_extra={"mutable": False},
    )
    upload_mbps: Optional[float] = Field(
        default=None,
        description="Upload speed in Mbps",
        json_schema_extra={"mutable": False},
    )
    latency_ms: Optional[float] = Field(
        default=None,
        description="Measured latency in milliseconds",
        json_schema_extra={"mutable": False},
    )


SPEEDTESTRESULT_MUTABLE_FIELDS: frozenset[str] = frozenset()
SPEEDTESTRESULT_READ_ONLY_FIELDS: frozenset[str] = frozenset(SpeedtestResult.model_fields.keys())


def speedtest_result_from_controller(raw: Any) -> SpeedtestResult:
    """Build a SpeedtestResult from a controller API response dict."""
    if not isinstance(raw, dict):
        return SpeedtestResult()
    return SpeedtestResult(
        timestamp=_get(raw, "time", "timestamp"),
        download_mbps=_get(raw, "xput_download", "download_mbps"),
        upload_mbps=_get(raw, "xput_upload", "upload_mbps"),
        latency_ms=_get(raw, "latency", "latency_ms"),
    )
