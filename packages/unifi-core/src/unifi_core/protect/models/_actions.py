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

from pydantic import BaseModel, Field, model_validator


def _require_non_empty_actions(body: dict) -> None:
    """Reject rule bodies that would brick the Protect UI.

    Protect's controller accepts ``actions: []`` (and even a body with no
    ``actions`` key at all) and returns a normal-looking rule on POST. But
    the resulting rule cannot be opened in the Protect web UI -- clicking
    it shows "We're Unable to Complete Your Request" and the rule becomes
    only deletable via API. Found via live-test 2026-05-27. Reject here so
    the failure mode never reaches a homelab.

    ``body`` is already type-validated as ``dict`` by the calling Pydantic
    model field, so this helper does not re-check that.
    """
    actions = body.get("actions")
    if not isinstance(actions, list) or len(actions) == 0:
        raise ValueError(
            "body.actions must be a non-empty list. Protect accepts rules "
            "with no actions, but the resulting rule cannot be opened in "
            "the Protect UI."
        )


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


class AlarmGetRuleInput(BaseModel):
    """Input for ``protect_alarm_get_rule``."""

    __action_input__: ClassVar[bool] = True

    rule_id: str = Field(description="Alarm rule (automation) UUID")


class AlarmUpdateRuleInput(BaseModel):
    """Input for ``protect_alarm_update_rule``.

    Protect's PATCH endpoint requires the full rule payload, so ``body``
    is the complete rule dict (typically produced by reading via
    ``protect_alarm_get_rule`` and mutating the returned dict).
    """

    __action_input__: ClassVar[bool] = True

    rule_id: str = Field(description="Alarm rule (automation) UUID")
    body: dict = Field(
        description=(
            "Full rule payload (Protect rejects partial bodies). "
            "Read-modify-write: call protect_alarm_get_rule, mutate, pass back here."
        )
    )

    @model_validator(mode="after")
    def _check_actions(self) -> "AlarmUpdateRuleInput":
        _require_non_empty_actions(self.body)
        return self


class AlarmCreateRuleInput(BaseModel):
    """Input for ``protect_alarm_create_rule``.

    The tool layer translates snake_case keys in ``body`` (as returned by
    ``protect_alarm_get_rule``) to the camelCase shape the controller
    requires on POST, so a natural read-modify-write flow works for clone-
    style creates. Both casings of a field are accepted; the camelCase
    value wins if both are present.
    """

    __action_input__: ClassVar[bool] = True

    body: dict = Field(
        description=(
            "Full rule payload matching the Protect automations schema "
            "(name, enable, sources, conditions, actions, cooldown). "
            "Server assigns the id and returns the created rule. "
            "``actions`` MUST be a non-empty list -- the controller accepts "
            "an empty actions list but the resulting rule cannot be opened "
            "in the Protect UI."
        )
    )

    @model_validator(mode="after")
    def _check_actions(self) -> "AlarmCreateRuleInput":
        _require_non_empty_actions(self.body)
        return self


class AlarmDeleteRuleInput(BaseModel):
    """Input for ``protect_alarm_delete_rule``."""

    __action_input__: ClassVar[bool] = True

    rule_id: str = Field(description="Alarm rule (automation) UUID to delete")


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


class MergeKnownFacesInput(BaseModel):
    """Input for ``protect_merge_known_faces``."""

    __action_input__: ClassVar[bool] = True

    source_face_id: str = Field(description="Face group UUID that will be folded into the target")
    target_face_id: str = Field(description="Face group UUID that survives the merge")


class DeleteKnownFaceInput(BaseModel):
    """Input for ``protect_delete_known_face``."""

    __action_input__: ClassVar[bool] = True

    face_id: str = Field(description="Face group UUID to remove")


class DeleteKnownLicensePlateInput(BaseModel):
    """Input for ``protect_delete_known_license_plate``."""

    __action_input__: ClassVar[bool] = True

    plate_id: str = Field(description="License-plate group id to remove")
