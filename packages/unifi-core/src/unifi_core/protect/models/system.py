"""Shared field models for Protect system/health/firmware/viewer.

Five classes cover the output shapes for:
- ``protect_get_system_info``   → ``ProtectSystemInfo``
- ``protect_get_health``        → ``ProtectHealth``
- ``protect_get_firmware_status`` → ``FirmwareStatus``
- ``protect_list_viewers`` per-row → ``Viewer``
- ``protect_list_viewers`` wrapper → ``ViewerList``

The read shapes remain read-only. Viewer mutation input is represented by
``ViewerUpdate`` and translated through ``to_viewer_public_update`` because
the Protect public API uses ``liveview`` for the nullable assignment field
while agents use ``liveview_id`` / ``clear_liveview``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError, model_validator


class ProtectSystemInfo(BaseModel):
    """NVR-level system info snapshot (read-only)."""

    id: Optional[str] = Field(default=None, description="NVR UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="NVR display name", json_schema_extra={"mutable": False})
    model: Optional[str] = Field(default=None, description="NVR model", json_schema_extra={"mutable": False})
    firmware_version: Optional[str] = Field(
        default=None, description="Protect firmware version", json_schema_extra={"mutable": False}
    )
    version: Optional[str] = Field(
        default=None, description="Protect software version", json_schema_extra={"mutable": False}
    )
    host: Optional[str] = Field(default=None, description="NVR IP/host", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="NVR MAC address", json_schema_extra={"mutable": False})
    uptime_seconds: Optional[int] = Field(
        default=None, description="NVR uptime in seconds", json_schema_extra={"mutable": False}
    )
    up_since: Optional[str] = Field(
        default=None, description="ISO timestamp when the NVR last started", json_schema_extra={"mutable": False}
    )
    is_updating: Optional[bool] = Field(
        default=None, description="Whether the NVR is currently updating", json_schema_extra={"mutable": False}
    )
    storage: Optional[Any] = Field(
        default=None, description="Storage stats (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    camera_count: Optional[int] = Field(
        default=None, description="Number of adopted cameras", json_schema_extra={"mutable": False}
    )
    light_count: Optional[int] = Field(
        default=None, description="Number of adopted lights", json_schema_extra={"mutable": False}
    )
    sensor_count: Optional[int] = Field(
        default=None, description="Number of adopted sensors", json_schema_extra={"mutable": False}
    )
    viewer_count: Optional[int] = Field(
        default=None, description="Number of adopted viewers", json_schema_extra={"mutable": False}
    )
    chime_count: Optional[int] = Field(
        default=None, description="Number of adopted chimes", json_schema_extra={"mutable": False}
    )


class ProtectHealth(BaseModel):
    """NVR health snapshot (read-only)."""

    cpu: Optional[Any] = Field(
        default=None, description="CPU health stats (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    memory: Optional[Any] = Field(
        default=None, description="Memory health stats (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    storage: Optional[Any] = Field(
        default=None, description="Storage health stats (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    is_updating: Optional[bool] = Field(
        default=None, description="Whether the NVR is currently updating", json_schema_extra={"mutable": False}
    )
    uptime_seconds: Optional[int] = Field(
        default=None, description="NVR uptime in seconds", json_schema_extra={"mutable": False}
    )


class FirmwareStatus(BaseModel):
    """Firmware update status for the NVR and all adopted devices (read-only)."""

    nvr: Optional[Any] = Field(
        default=None, description="NVR firmware info (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    devices: Optional[Any] = Field(
        default=None,
        description="Per-device firmware info list (JSON pass-through)",
        json_schema_extra={"mutable": False},
    )
    total_devices: Optional[int] = Field(
        default=None, description="Total number of adopted devices", json_schema_extra={"mutable": False}
    )
    devices_with_updates: Optional[int] = Field(
        default=None,
        description="Number of devices with firmware updates available",
        json_schema_extra={"mutable": False},
    )


class Viewer(BaseModel):
    """Canonical Protect viewer (Viewport) model (read-only)."""

    id: Optional[str] = Field(default=None, description="Viewer UUID", json_schema_extra={"mutable": False})
    name: Optional[str] = Field(default=None, description="Viewer display name", json_schema_extra={"mutable": False})
    type: Optional[str] = Field(default=None, description="Viewer device type", json_schema_extra={"mutable": False})
    mac: Optional[str] = Field(default=None, description="Viewer MAC address", json_schema_extra={"mutable": False})
    host: Optional[str] = Field(default=None, description="Viewer IP/host", json_schema_extra={"mutable": False})
    firmware_version: Optional[str] = Field(
        default=None, description="Viewer firmware version", json_schema_extra={"mutable": False}
    )
    is_connected: Optional[bool] = Field(
        default=None, description="Whether the viewer is connected", json_schema_extra={"mutable": False}
    )
    is_updating: Optional[bool] = Field(
        default=None, description="Whether the viewer is currently updating", json_schema_extra={"mutable": False}
    )
    uptime_seconds: Optional[int] = Field(
        default=None, description="Viewer uptime in seconds", json_schema_extra={"mutable": False}
    )
    state: Optional[str] = Field(
        default=None, description="Viewer connection state", json_schema_extra={"mutable": False}
    )
    software_version: Optional[str] = Field(
        default=None, description="Viewer software version", json_schema_extra={"mutable": False}
    )
    liveview_id: Optional[str] = Field(
        default=None, description="UUID of the liveview assigned to this viewer", json_schema_extra={"mutable": False}
    )


class ViewerList(BaseModel):
    """Wrapper shape returned by ``protect_list_viewers`` (read-only)."""

    viewers: Optional[Any] = Field(
        default=None, description="List of viewer dicts (JSON pass-through)", json_schema_extra={"mutable": False}
    )
    count: Optional[int] = Field(
        default=None, description="Number of viewers in the list", json_schema_extra={"mutable": False}
    )


class ViewerUpdate(BaseModel):
    """Agent-facing viewer settings accepted by ``protect_update_viewer``."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, description="Viewer display name")
    liveview_id: Optional[str] = Field(default=None, min_length=1, description="Liveview UUID to assign")
    clear_liveview: StrictBool = Field(default=False, description="Clear the viewer's current liveview assignment")

    @model_validator(mode="after")
    def _validate_update(self) -> "ViewerUpdate":
        if self.liveview_id is not None and self.clear_liveview:
            raise ValueError("liveview_id and clear_liveview=True cannot be used together.")
        if self.name is None and self.liveview_id is None and not self.clear_liveview:
            raise ValueError("No viewer settings provided. Specify at least one setting to update.")
        return self


MUTABLE_FIELDS: frozenset = frozenset()
VIEWER_UPDATE_FIELDS: frozenset = frozenset(ViewerUpdate.model_fields.keys())
READ_ONLY_FIELDS: frozenset = (
    frozenset(ProtectSystemInfo.model_fields.keys())
    | frozenset(ProtectHealth.model_fields.keys())
    | frozenset(FirmwareStatus.model_fields.keys())
    | frozenset(Viewer.model_fields.keys())
    | frozenset(ViewerList.model_fields.keys())
)


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


def _json_passthrough(value: Any) -> Optional[Any]:
    """Accept dict or list; coalesce anything else (including None) to None."""
    if isinstance(value, (dict, list)):
        return value
    return None


def system_info_from_controller(raw: Any) -> ProtectSystemInfo:
    """Build a ProtectSystemInfo from a manager dict or object."""
    return ProtectSystemInfo(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        model=_get(raw, "model"),
        firmware_version=_get(raw, "firmware_version"),
        version=_get(raw, "version"),
        host=_get(raw, "host"),
        mac=_get(raw, "mac"),
        uptime_seconds=_get(raw, "uptime_seconds"),
        up_since=_stringify_dt(_get(raw, "up_since")),
        is_updating=_get(raw, "is_updating"),
        storage=_json_passthrough(_get(raw, "storage")),
        camera_count=_get(raw, "camera_count"),
        light_count=_get(raw, "light_count"),
        sensor_count=_get(raw, "sensor_count"),
        viewer_count=_get(raw, "viewer_count"),
        chime_count=_get(raw, "chime_count"),
    )


def health_from_controller(raw: Any) -> ProtectHealth:
    """Build a ProtectHealth from a manager dict or object."""
    return ProtectHealth(
        cpu=_json_passthrough(_get(raw, "cpu")),
        memory=_json_passthrough(_get(raw, "memory")),
        storage=_json_passthrough(_get(raw, "storage")),
        is_updating=_get(raw, "is_updating"),
        uptime_seconds=_get(raw, "uptime_seconds"),
    )


def firmware_status_from_controller(raw: Any) -> FirmwareStatus:
    """Build a FirmwareStatus from a manager dict or object."""
    return FirmwareStatus(
        nvr=_json_passthrough(_get(raw, "nvr")),
        devices=_json_passthrough(_get(raw, "devices")),
        total_devices=_get(raw, "total_devices"),
        devices_with_updates=_get(raw, "devices_with_updates"),
    )


def viewer_from_controller(raw: Any) -> Viewer:
    """Build a Viewer from a manager dict or object."""
    return Viewer(
        id=_get(raw, "id"),
        name=_get(raw, "name"),
        type=_get(raw, "type"),
        mac=_get(raw, "mac"),
        host=_get(raw, "host"),
        firmware_version=_get(raw, "firmware_version"),
        is_connected=_get(raw, "is_connected"),
        is_updating=_get(raw, "is_updating"),
        uptime_seconds=_get(raw, "uptime_seconds"),
        state=_get(raw, "state"),
        software_version=_get(raw, "software_version"),
        liveview_id=_get(raw, "liveview_id"),
    )


def viewer_list_from_controller(raw: Any) -> ViewerList:
    """Build a ViewerList from a manager dict or object.

    Accepts:
    - a dict with ``viewers`` (list) and ``count`` keys (wrapper shape)
    - a bare list (coerced to wrapper shape)
    - anything else: ``viewers`` coalesces to None
    """
    if isinstance(raw, list):
        return ViewerList(viewers=list(raw), count=len(raw))
    viewers = _get(raw, "viewers")
    if not isinstance(viewers, list):
        viewers = None
    return ViewerList(
        viewers=viewers,
        count=_get(raw, "count"),
    )


def to_viewer_public_update(fields: dict[str, Any]) -> dict[str, Any]:
    """Validate viewer update settings and translate to public API kwargs."""
    if not isinstance(fields, dict):
        raise ValueError("Viewer settings must be a dictionary for protect_update_viewer.")
    if not fields:
        raise ValueError("No viewer settings provided. Specify at least one setting to update.")

    unknown = sorted(set(fields) - VIEWER_UPDATE_FIELDS)
    if unknown:
        joined = ", ".join(unknown)
        supported = ", ".join(sorted(VIEWER_UPDATE_FIELDS))
        raise ValueError(
            f"Unsupported viewer setting fields for protect_update_viewer: {joined}. Supported fields: {supported}."
        )

    try:
        model = ViewerUpdate(**fields)
    except ValidationError as exc:
        raise ValueError(_first_validation_message(exc)) from exc

    update: dict[str, Any] = {}
    if model.name is not None:
        update["name"] = model.name
    if model.clear_liveview:
        update["liveview"] = None
    elif model.liveview_id is not None:
        update["liveview"] = model.liveview_id
    return update


def viewer_public_update_to_agent(fields: dict[str, Any]) -> dict[str, Any]:
    """Translate public API viewer update kwargs back to agent-facing names."""
    result: dict[str, Any] = {}
    if "name" in fields:
        result["name"] = fields["name"]
    if "liveview" in fields:
        result["liveview_id"] = fields["liveview"]
    return result


def _first_validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(part) for part in first.get("loc", ()) if part != "__root__")
    message = first.get("msg", str(exc))
    if location:
        return f"Invalid viewer setting {location}: {message}"
    return f"Invalid viewer settings: {message}"
