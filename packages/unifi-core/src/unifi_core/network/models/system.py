"""Shared field models for Network system settings (Scope-A subset).

Mirrors the Strawberry types in
``unifi_api.graphql.types.network.system``:

Scope-A classes (this file):
- ``SnmpSettings``        — get_snmp_settings + update_snmp_settings
- ``AutoBackupSettings``  — get_autobackup_settings + update_autobackup_settings

Scope-B classes (added in a later task):
  Alarm, Backup, SystemInfo, NetworkHealth, SiteSettings, EventTypes,
  TopClient, SpeedtestResult.

Factory helpers:
- ``snmp_from_controller``        — normalise raw → SnmpSettings
- ``autobackup_from_controller``  — normalise raw → AutoBackupSettings
- ``snmp_to_controller_update``   — filter partial dict to SNMP mutable keys
- ``autobackup_to_controller_update`` — filter partial dict to autobackup mutable keys

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
    name
    for name, field in SnmpSettings.model_fields.items()
    if (field.json_schema_extra or {}).get("mutable", True)
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
    return {
        k: v
        for k, v in fields.items()
        if k in SNMPSETTINGS_MUTABLE_FIELDS and v is not None
    }


# ---------------------------------------------------------------------------
# Public factory helpers — AutoBackupSettings
# ---------------------------------------------------------------------------


def autobackup_from_controller(raw: Any) -> AutoBackupSettings:
    """Build an AutoBackupSettings from a controller API response dict."""
    if not isinstance(raw, dict):
        return AutoBackupSettings()
    return AutoBackupSettings(
        autobackup_enabled=raw.get("autobackup_enabled") if raw.get("autobackup_enabled") is not None else raw.get("enabled"),
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
    return {
        k: v
        for k, v in fields.items()
        if k in AUTOBACKUPSETTINGS_MUTABLE_FIELDS and v is not None
    }
