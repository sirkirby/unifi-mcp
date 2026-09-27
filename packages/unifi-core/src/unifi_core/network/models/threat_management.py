"""Typed site-wide threat management (IDS/IPS) and traffic identification settings.

Single source of truth for threat management settings projection.
Excludes controller-internal keys and secrets (such as utm_token).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, ValidationError, field_validator
from pydantic.json_schema import SkipJsonSchema

KNOWN_ENABLED_MODES: frozenset[str] = frozenset({"ids", "ips", "ipsInline"})
KNOWN_DISABLED_MODES: frozenset[str] = frozenset({"disabled"})

MUTABLE_FIELDS: frozenset[str] = frozenset(
    {"ips_mode", "enabled_categories", "traffic_identification_enabled", "device_fingerprinting_enabled"}
)
READ_ONLY_FIELDS: frozenset[str] = frozenset(
    {
        "enabled",
        "enabled_networks",
        "advanced_filtering_preference",
    }
)


class ThreatManagementSettings(BaseModel):
    """Canonical threat management (IDS/IPS) and DPI settings model.

    Public projection of site-wide IPS and DPI settings records.
    Explicit allowlist only: excludes controller secrets (e.g. utm_token)
    and unverified fields.
    """

    ips_mode: str | None = Field(
        default=None,
        description="Raw IPS operation mode string from controller (e.g. 'disabled', 'ids', 'ips', 'ipsInline').",
    )
    advanced_filtering_preference: str | None = Field(
        default=None,
        description="Controller category selection mode (manual, auto, or disabled); derived on mode/category updates.",
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
    )
    enabled_networks: list[str] | None = Field(
        default=None,
        description="Protected network IDs (null when absent from controller).",
        json_schema_extra={"mutable": False},
    )
    traffic_identification_enabled: bool | None = Field(
        default=None,
        description="Traffic identification (DPI) enabled state (strict boolean, null if missing/malformed).",
    )
    device_fingerprinting_enabled: bool | None = Field(
        default=None,
        description="Device fingerprinting enabled state (strict boolean, null if missing/malformed).",
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
        advanced_filtering_preference=(
            ips_dict.get("advanced_filtering_preference")
            if isinstance(ips_dict.get("advanced_filtering_preference"), str)
            else None
        ),
        enabled=enabled,
        enabled_categories=enabled_categories,
        enabled_networks=enabled_networks,
        traffic_identification_enabled=traffic_id_enabled,
        device_fingerprinting_enabled=device_fp_enabled,
    )


class ThreatManagementValidationError(ValueError):
    """Fixed public validation errors; never contain controller exception text."""


class ThreatManagementUpdate(BaseModel):
    """Strict partial update; one settings endpoint per request, never null."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    ips_mode: StrictStr | SkipJsonSchema[None] = Field(
        default=None, description="IDS detection: ids; prevention: ips or ipsInline; off: disabled"
    )
    enabled_categories: list[StrictStr] | SkipJsonSchema[None] = Field(
        default=None, description="Full category code list; selects manual mode; validated against gateway catalog"
    )
    traffic_identification_enabled: StrictBool | SkipJsonSchema[None] = Field(
        default=None, description="Enable traffic identification; disabling can stop application-based rules matching"
    )
    device_fingerprinting_enabled: StrictBool | SkipJsonSchema[None] = Field(
        default=None, description="Enable device fingerprinting when supported by this controller"
    )

    @field_validator("ips_mode")
    @classmethod
    def known_mode(cls, value: str | None) -> str | None:
        if value not in KNOWN_ENABLED_MODES | KNOWN_DISABLED_MODES:
            raise ValueError("unsupported IPS mode")
        return value

    @field_validator("enabled_categories")
    @classmethod
    def category_codes(cls, value: list[str] | None) -> list[str] | None:
        if value is None or any(not item.strip() for item in value) or len(set(value)) != len(value):
            raise ValueError("categories require unique nonempty codes")
        return value


def threat_management_to_controller_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate without I/O; preserve public names until selecting one endpoint."""
    if not isinstance(fields, dict) or set(fields) - MUTABLE_FIELDS:
        raise ThreatManagementValidationError("Invalid threat management update fields")
    if any(value is None for value in fields.values()):
        raise ThreatManagementValidationError("Threat management fields cannot be null")
    try:
        parsed = ThreatManagementUpdate.model_validate(fields)
    except ValidationError:
        raise ThreatManagementValidationError(
            "Invalid threat management fields; use a supported mode, category list, or boolean"
        ) from None
    ips_fields = {"ips_mode", "enabled_categories"}
    if set(fields) & ips_fields and set(fields) - ips_fields:
        raise ThreatManagementValidationError("Update IPS and traffic identification settings in separate calls")
    return parsed.model_dump(exclude_unset=True)


def merge_threat_management_update(
    fields: dict[str, Any], before: dict[str, Any], supported_categories: set[str] | None = None
) -> dict[str, Any]:
    """Derive explicit mode/category effects without changing network coverage."""
    updates = threat_management_to_controller_update(fields)
    if not (set(updates) & {"ips_mode", "enabled_categories"}):
        mapping = {
            "traffic_identification_enabled": "enabled",
            "device_fingerprinting_enabled": "fingerprintingEnabled",
        }
        if any(type(before.get(mapping[key])) is not bool for key in updates):
            raise ThreatManagementValidationError(
                "Requested traffic identification setting is unavailable on this controller"
            )
        return {mapping[key]: value for key, value in updates.items()}
    mode = updates.get("ips_mode", before.get("ips_mode"))
    if mode == "ipsInline" and before.get("ips_mode") != "ipsInline":
        raise ThreatManagementValidationError("ipsInline can only be preserved on a controller already using that mode")
    if mode not in KNOWN_ENABLED_MODES | KNOWN_DISABLED_MODES:
        raise ThreatManagementValidationError("Set a supported ips_mode before updating categories")
    if mode == "disabled":
        if updates.get("enabled_categories"):
            raise ThreatManagementValidationError("Disabled IPS requires an empty category list")
        return {
            **updates,
            "ips_mode": "disabled",
            "advanced_filtering_preference": "disabled",
            "enabled_categories": [],
        }
    preference = before.get("advanced_filtering_preference") or "manual"
    if "enabled_categories" in updates or preference == "disabled":
        preference = "manual"
    if preference not in {"auto", "manual"}:
        raise ThreatManagementValidationError("Unsupported controller category selection mode")
    categories = updates.get("enabled_categories", before.get("enabled_categories"))
    if preference == "manual":
        if not isinstance(categories, list) or not categories or not all(isinstance(x, str) for x in categories):
            raise ThreatManagementValidationError("Enabled manual IPS requires a nonempty enabled_categories list")
        if supported_categories is None or not set(categories) <= supported_categories:
            raise ThreatManagementValidationError("Requested IPS categories are not supported by this gateway")
    networks = before.get("enabled_networks")
    if not isinstance(networks, list) or not networks or not all(isinstance(x, str) and x for x in networks):
        raise ThreatManagementValidationError("Configure protected networks in UniFi before enabling IPS")
    return {**updates, "ips_mode": mode, "advanced_filtering_preference": preference}


class ThreatManagementToolInput(BaseModel):
    """Model-derived MCP and API action input contract."""

    model_config = ConfigDict(extra="forbid", strict=True)
    update_data: ThreatManagementUpdate
    confirm: bool = False


def threat_management_input_schema(model_type: type[BaseModel] = ThreatManagementUpdate) -> dict[str, Any]:
    """Inline definitions for schema consumers, following the VPN/NAT model anchor."""
    schema = model_type.model_json_schema()
    definitions = schema.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, list):
            return [inline(value) for value in node]
        if isinstance(node, dict):
            if "$ref" in node:
                return inline(definitions[node["$ref"].removeprefix("#/$defs/")])
            return {key: inline(value) for key, value in node.items() if not (key == "default" and value is None)}
        return node

    return inline(schema)
