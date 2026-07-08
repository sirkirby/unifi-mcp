"""Shared field model for Protect sensors (motion / leak / temperature)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)


class Sensor(BaseModel):
    """Canonical Protect sensor model (read-only)."""

    id: Optional[str] = Field(default=None, description="Sensor UUID", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="MAC address", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Display name")
    type: Optional[str] = Field(
        default=None, description="Sensor type (motion, leak, temperature, etc.)", json_schema_extra={"mutable": False}
    )
    battery_status: Optional[str] = Field(
        default=None, description="Battery state summary", json_schema_extra={"mutable": False}
    )
    humidity_status: Optional[str] = Field(
        default=None, description="Humidity reading summary", json_schema_extra={"mutable": False}
    )
    light_status: Optional[str] = Field(
        default=None, description="Ambient light reading summary", json_schema_extra={"mutable": False}
    )
    motion_detected_at: Optional[str] = Field(
        default=None, description="ISO timestamp of last motion event", json_schema_extra={"mutable": False}
    )


MUTABLE_FIELDS = frozenset(
    name for name, info in Sensor.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is not False
)
READ_ONLY_FIELDS = frozenset(
    name for name, info in Sensor.model_fields.items() if (info.json_schema_extra or {}).get("mutable") is False
)

PUBLIC_UPDATE_FIELDS = frozenset(
    {
        "name",
        "light_settings",
        "humidity_settings",
        "temperature_settings",
        "motion_settings",
        "glass_break_settings",
        "alarm_settings",
        "schedule_mode",
        "arm_profile_ids",
        "has_custom_sensitivity_when_armed",
    }
)

_NESTED_PUBLIC_SETTING_FIELDS: dict[str, dict[str, str]] = {
    "light_settings": {
        "is_enabled": "isEnabled",
        "low_threshold": "lowThreshold",
        "high_threshold": "highThreshold",
        "margin": "margin",
    },
    "humidity_settings": {
        "is_enabled": "isEnabled",
        "low_threshold": "lowThreshold",
        "high_threshold": "highThreshold",
        "margin": "margin",
    },
    "temperature_settings": {
        "is_enabled": "isEnabled",
        "low_threshold": "lowThreshold",
        "high_threshold": "highThreshold",
        "margin": "margin",
    },
    "motion_settings": {
        "is_enabled": "isEnabled",
        "sensitivity": "sensitivity",
        "sensitivity_when_armed": "sensitivityWhenArmed",
    },
    "glass_break_settings": {
        "is_enabled": "isEnabled",
        "sensitivity": "sensitivity",
        "sensitivity_when_armed": "sensitivityWhenArmed",
    },
    "alarm_settings": {
        "is_enabled": "isEnabled",
    },
}

_SUPPORTED_SCHEDULE_MODES = frozenset({"always", "when_armed", "unknown"})


class _SensorThresholdSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: Optional[StrictBool] = None
    low_threshold: Optional[StrictFloat | StrictInt] = None
    high_threshold: Optional[StrictFloat | StrictInt] = None
    margin: Optional[StrictFloat | StrictInt] = None

    @model_validator(mode="after")
    def _require_field(self) -> "_SensorThresholdSettingsUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("must include at least one non-null field")
        return self


class _SensorSensitivitySettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: Optional[StrictBool] = None
    sensitivity: Optional[StrictInt] = Field(default=None, ge=0, le=100)
    sensitivity_when_armed: Optional[StrictInt] = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _require_field(self) -> "_SensorSensitivitySettingsUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("must include at least one non-null field")
        return self


class _SensorAlarmSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_enabled: Optional[StrictBool] = None

    @model_validator(mode="after")
    def _require_field(self) -> "_SensorAlarmSettingsUpdate":
        if self.is_enabled is None:
            raise ValueError("must include at least one non-null field")
        return self


class _SensorPublicUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1)
    light_settings: Optional[_SensorThresholdSettingsUpdate] = None
    humidity_settings: Optional[_SensorThresholdSettingsUpdate] = None
    temperature_settings: Optional[_SensorThresholdSettingsUpdate] = None
    motion_settings: Optional[_SensorSensitivitySettingsUpdate] = None
    glass_break_settings: Optional[_SensorSensitivitySettingsUpdate] = None
    alarm_settings: Optional[_SensorAlarmSettingsUpdate] = None
    schedule_mode: Optional[str] = None
    arm_profile_ids: Optional[list[str]] = None
    has_custom_sensitivity_when_armed: Optional[StrictBool] = None

    @field_validator("schedule_mode")
    @classmethod
    def _validate_schedule_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).lower()
        if normalized not in _SUPPORTED_SCHEDULE_MODES:
            supported = ", ".join(sorted(_SUPPORTED_SCHEDULE_MODES))
            raise ValueError(f"schedule_mode must be one of: {supported}")
        return normalized

    @field_validator("arm_profile_ids")
    @classmethod
    def _validate_arm_profile_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not all(isinstance(item, str) and item for item in value):
            raise ValueError("arm_profile_ids must be a list of non-empty strings")
        return value

    @model_validator(mode="after")
    def _require_field(self) -> "_SensorPublicUpdate":
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("No sensor settings provided. Specify at least one non-null setting to update.")
        return self


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _stringify_dt(value: Any) -> Optional[str]:
    """Coerce a datetime-ish value to ISO 8601 string for serialization."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:
            return None
    return str(value)


def from_controller(raw: Any) -> Sensor:
    """Build a Sensor from a uiprotect / manager dict or object."""
    return Sensor(
        id=_get(raw, "id"),
        mac=_get(raw, "mac"),
        name=_get(raw, "name"),
        type=_get(raw, "type"),
        battery_status=_get(raw, "battery_status"),
        humidity_status=_get(raw, "humidity_status"),
        light_status=_get(raw, "light_status"),
        motion_detected_at=_stringify_dt(_get(raw, "motion_detected_at")),
    )


def to_public_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and filter a partial sensor public API settings update."""
    if not isinstance(fields, dict):
        raise ValueError("Sensor settings must be a dictionary for protect_update_sensor_settings.")
    if not fields:
        raise ValueError("No sensor settings provided. Specify at least one setting to update.")

    keys = set(fields)
    read_only = sorted(keys & READ_ONLY_FIELDS)
    if read_only:
        joined = ", ".join(read_only)
        raise ValueError(
            f"Cannot update read-only sensor fields: {joined}. "
            "Use protect_list_sensors for sensor IDs and pass only supported settings."
        )

    unknown = sorted(keys - PUBLIC_UPDATE_FIELDS)
    if unknown:
        joined = ", ".join(unknown)
        supported = ", ".join(sorted(PUBLIC_UPDATE_FIELDS))
        raise ValueError(
            f"Unsupported sensor setting fields for protect_update_sensor_settings: {joined}. "
            f"Supported fields: {supported}."
        )

    try:
        model = _SensorPublicUpdate(**fields)
    except ValidationError as exc:
        raise ValueError(_first_validation_message(exc)) from exc

    update = model.model_dump(exclude_none=True)
    return {
        key: _translate_nested_public_setting(key, value) if key in _NESTED_PUBLIC_SETTING_FIELDS else value
        for key, value in update.items()
    }


def to_agent_update(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Translate public API update kwargs back to the agent-facing snake_case shape."""
    return {
        key: _translate_nested_public_setting_to_agent(key, value) if key in _NESTED_PUBLIC_SETTING_FIELDS else value
        for key, value in fields.items()
    }


def _first_validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    message = first.get("msg", str(exc))
    if location:
        return f"Invalid sensor setting {location}: {message}"
    return f"Invalid sensor settings: {message}"


def _translate_nested_public_setting(parent_key: str, value: Any) -> dict[str, Any]:
    """Translate agent-facing snake_case nested settings to uiprotect's typed-dict keys."""
    if not isinstance(value, dict):
        raise ValueError(f"Sensor setting {parent_key} must be a dictionary.")

    field_map = _NESTED_PUBLIC_SETTING_FIELDS[parent_key]
    unknown = sorted(set(value) - set(field_map))
    if unknown:
        joined = ", ".join(unknown)
        supported = ", ".join(sorted(field_map))
        raise ValueError(
            f"Unsupported fields for sensor setting {parent_key}: {joined}. Use snake_case fields: {supported}."
        )

    translated = {field_map[key]: nested_value for key, nested_value in value.items() if nested_value is not None}
    if not translated:
        raise ValueError(f"Sensor setting {parent_key} must include at least one non-null field.")
    return translated


def _translate_nested_public_setting_to_agent(parent_key: str, value: Any) -> Any:
    """Translate uiprotect typed-dict keys to agent-facing snake_case keys."""
    if not isinstance(value, dict):
        return value

    reverse_map = {public_key: agent_key for agent_key, public_key in _NESTED_PUBLIC_SETTING_FIELDS[parent_key].items()}
    return {reverse_map.get(key, key): nested_value for key, nested_value in value.items()}
