"""Pydantic input models for Protect action tools.

Action tools (PTZ control, reboot, toggle, alarm arm/disarm, trigger,
export, delete, acknowledge) take typed action parameters rather than
a round-trip domain object. Each input class lives here.

The class-level ``__action_input__`` flag marks these as out-of-scope
for the cross-layer field-symmetry test — they have no Strawberry read
shape to compare against. Tools import the relevant input class and
validate kwargs via ``ToolInput(**kwargs)`` at the top of the body.
"""

from __future__ import annotations

from typing import ClassVar, Optional

from pydantic import BaseModel, Field


class PtzMoveInput(BaseModel):
    """Input for ``protect_ptz_move``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID of a PTZ-capable camera")
    pan: Optional[float] = Field(default=None, ge=-1000, le=1000, description="Pan speed (-1000..1000); 0 stops")
    tilt: Optional[float] = Field(default=None, ge=-1000, le=1000, description="Tilt speed (-1000..1000); 0 stops")
    duration_ms: int = Field(default=250, ge=0, le=5000, description="Movement duration before auto-stop (ms)")


class PtzZoomInput(BaseModel):
    """Input for ``protect_ptz_zoom``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID of a PTZ-capable camera")
    zoom_speed: int = Field(default=0, ge=-1000, le=1000, description="Zoom speed (-1000..1000); 0 stops")
    duration_ms: int = Field(default=250, ge=0, le=5000, description="Zoom duration before auto-stop (ms)")


class PtzPresetInput(BaseModel):
    """Input for ``protect_ptz_preset``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID of a PTZ-capable camera")
    preset_slot: int = Field(ge=0, description="Preset slot number to move the camera to")


class RebootCameraInput(BaseModel):
    """Input for ``protect_reboot_camera``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID")


class ToggleRecordingInput(BaseModel):
    """Input for ``protect_toggle_recording``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID")
    enabled: bool = Field(description="True enables recording (always); False disables (never)")


class AlarmArmInput(BaseModel):
    """Input for ``protect_alarm_arm``."""

    __action_input__: ClassVar[bool] = True

    profile_id: Optional[str] = Field(
        default=None,
        description="Arm profile UUID; omit to use the currently selected profile",
    )


class AlarmDisarmInput(BaseModel):
    """Input for ``protect_alarm_disarm`` (no parameters)."""

    __action_input__: ClassVar[bool] = True


class TriggerChimeInput(BaseModel):
    """Input for ``protect_trigger_chime``."""

    __action_input__: ClassVar[bool] = True

    chime_id: str = Field(description="Chime device UUID")
    volume: Optional[int] = Field(default=None, ge=0, le=100, description="One-shot volume override (0-100)")
    repeat_times: Optional[int] = Field(default=None, ge=1, le=6, description="One-shot repeat count override (1-6)")


class ExportClipInput(BaseModel):
    """Input for ``protect_export_clip``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID to export footage from")
    start: str = Field(description="ISO 8601 start timestamp")
    end: str = Field(description="ISO 8601 end timestamp (max 2 hours after start)")
    channel_index: int = Field(default=0, ge=0, le=2, description="Channel index: 0=high, 1=med, 2=low")
    fps: Optional[int] = Field(default=None, ge=1, description="Timelapse fps; omit for normal speed")


class DeleteRecordingInput(BaseModel):
    """Input for ``protect_delete_recording``."""

    __action_input__: ClassVar[bool] = True

    camera_id: str = Field(description="Camera UUID to delete recordings from")
    start: str = Field(description="ISO 8601 start of deletion range")
    end: str = Field(description="ISO 8601 end of deletion range")


class DeleteLiveviewInput(BaseModel):
    """Input for ``protect_delete_liveview``."""

    __action_input__: ClassVar[bool] = True

    liveview_id: str = Field(description="Liveview UUID")


class AcknowledgeEventInput(BaseModel):
    """Input for ``protect_acknowledge_event``."""

    __action_input__: ClassVar[bool] = True

    event_id: str = Field(description="Event UUID to acknowledge")
