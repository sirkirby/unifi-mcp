"""Typed site-wide threat management (IDS/IPS) and traffic identification settings.

Single source of truth for threat management settings projection.
Excludes controller-internal keys and secrets (such as utm_token).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

KNOWN_ENABLED_MODES: frozenset[str] = frozenset({"ids", "ips", "ipsInline"})
KNOWN_DISABLED_MODES: frozenset[str] = frozenset({"disabled"})

MUTABLE_FIELDS: frozenset[str] = frozenset()
READ_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "ips_mode",
        "enabled",
        "enabled_categories",
        "enabled_networks",
        "traffic_identification_enabled",
        "device_fingerprinting_enabled",
    }
)


class ThreatManagementSettings(BaseModel):
    """Canonical threat management (IDS/IPS) and DPI settings model.

    Read-only projection of site-wide IPS and DPI settings records.
    Explicit allowlist only: excludes controller secrets (e.g. utm_token)
    and unverified fields.
    """

    ips_mode: str | None = Field(
        default=None,
        description="Raw IPS operation mode string from controller (e.g. 'disabled', 'ids', 'ips', 'ipsInline').",
        json_schema_extra={"mutable": False},
    )
    enabled: bool | None = Field(
        default=None,
        description=(
            "Normalized enabled state: true for known modes ('ids', 'ips', 'ipsInline'), "
            "false for 'disabled', null for unknown/missing."
        ),
        json_schema_extra={"mutable": False},
    )
    enabled_categories: list[str] | None = Field(
        default=None,
        description="Enabled threat category codes (null when absent from controller).",
        json_schema_extra={"mutable": False},
    )
    enabled_networks: list[str] | None = Field(
        default=None,
        description="Protected network IDs (null when absent from controller).",
        json_schema_extra={"mutable": False},
    )
    traffic_identification_enabled: bool | None = Field(
        default=None,
        description="Traffic identification (DPI) enabled state (strict boolean, null if missing/malformed).",
        json_schema_extra={"mutable": False},
    )
    device_fingerprinting_enabled: bool | None = Field(
        default=None,
        description="Device fingerprinting enabled state (strict boolean, null if missing/malformed).",
        json_schema_extra={"mutable": False},
    )


def threat_management_from_controller(
    ips: dict[str, Any] | None = None,
    dpi: dict[str, Any] | None = None,
) -> ThreatManagementSettings:
    """Project IPS and DPI records into ThreatManagementSettings without leaking controller secrets."""
    ips_dict = ips if isinstance(ips, dict) else {}
    dpi_dict = dpi if isinstance(dpi, dict) else {}

    # 1. ips_mode: preserve raw string, null if missing or non-string
    raw_mode = ips_dict.get("ips_mode")
    ips_mode = raw_mode if isinstance(raw_mode, str) else None

    # 2. enabled: true for known active modes, false for disabled, None for unknown/missing
    if ips_mode in KNOWN_ENABLED_MODES:
        enabled: bool | None = True
    elif ips_mode in KNOWN_DISABLED_MODES:
        enabled = False
    else:
        enabled = None

    # 3. enabled_categories: None when absent or malformed, preserve actual empty lists and valid string lists
    raw_categories = ips_dict.get("enabled_categories")
    if raw_categories is None or not isinstance(raw_categories, list):
        enabled_categories: list[str] | None = None
    elif not all(isinstance(c, str) for c in raw_categories):
        enabled_categories = None
    else:
        enabled_categories = list(raw_categories)

    # 4. enabled_networks: None when absent or malformed, preserve actual empty lists and valid string lists
    raw_networks = ips_dict.get("enabled_networks")
    if raw_networks is None or not isinstance(raw_networks, list):
        enabled_networks: list[str] | None = None
    elif not all(isinstance(n, str) for n in raw_networks):
        enabled_networks = None
    else:
        enabled_networks = list(raw_networks)

    # 5. traffic_identification_enabled: strict boolean from dpi.enabled only
    raw_dpi_enabled = dpi_dict.get("enabled")
    traffic_id_enabled = raw_dpi_enabled if type(raw_dpi_enabled) is bool else None

    # 6. device_fingerprinting_enabled: strict boolean from dpi.fingerprintingEnabled only
    raw_fingerprinting = dpi_dict.get("fingerprintingEnabled")
    device_fp_enabled = raw_fingerprinting if type(raw_fingerprinting) is bool else None

    return ThreatManagementSettings(
        ips_mode=ips_mode,
        enabled=enabled,
        enabled_categories=enabled_categories,
        enabled_networks=enabled_networks,
        traffic_identification_enabled=traffic_id_enabled,
        device_fingerprinting_enabled=device_fp_enabled,
    )
