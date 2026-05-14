"""Tests for Protect action-tool input models (_actions.py)."""

import pytest
from pydantic import ValidationError
from unifi_core.protect.models._actions import (
    AcknowledgeEventInput,
    AlarmArmInput,
    AlarmDisarmInput,
    DeleteLiveviewInput,
    DeleteRecordingInput,
    ExportClipInput,
    PtzMoveInput,
    PtzPresetInput,
    PtzZoomInput,
    RebootCameraInput,
    ToggleRecordingInput,
    TriggerChimeInput,
)

# ---------------------------------------------------------------------------
# PtzMoveInput
# ---------------------------------------------------------------------------


class TestPtzMoveInput:
    def test_action_input_flag(self):
        assert PtzMoveInput.__action_input__ is True

    def test_required_camera_id(self):
        with pytest.raises(Exception):
            PtzMoveInput()

    def test_defaults_applied(self):
        m = PtzMoveInput(camera_id="abc")
        assert m.pan is None
        assert m.tilt is None
        assert m.duration_ms == 250

    def test_valid_full(self):
        m = PtzMoveInput(camera_id="abc", pan=500.0, tilt=-200.0, duration_ms=1000)
        assert m.pan == 500.0
        assert m.tilt == -200.0
        assert m.duration_ms == 1000

    def test_pan_out_of_range_high(self):
        with pytest.raises(ValidationError):
            PtzMoveInput(camera_id="abc", pan=1500)

    def test_pan_out_of_range_low(self):
        with pytest.raises(ValidationError):
            PtzMoveInput(camera_id="abc", pan=-1001)

    def test_tilt_out_of_range(self):
        with pytest.raises(ValidationError):
            PtzMoveInput(camera_id="abc", tilt=1001)

    def test_duration_ms_negative(self):
        with pytest.raises(ValidationError):
            PtzMoveInput(camera_id="abc", duration_ms=-1)

    def test_duration_ms_too_large(self):
        with pytest.raises(ValidationError):
            PtzMoveInput(camera_id="abc", duration_ms=5001)


# ---------------------------------------------------------------------------
# PtzZoomInput
# ---------------------------------------------------------------------------


class TestPtzZoomInput:
    def test_action_input_flag(self):
        assert PtzZoomInput.__action_input__ is True

    def test_required_camera_id(self):
        with pytest.raises(Exception):
            PtzZoomInput()

    def test_defaults_applied(self):
        m = PtzZoomInput(camera_id="abc")
        assert m.zoom_speed == 0
        assert m.duration_ms == 250

    def test_zoom_speed_out_of_range_high(self):
        with pytest.raises(ValidationError):
            PtzZoomInput(camera_id="abc", zoom_speed=1001)

    def test_zoom_speed_out_of_range_low(self):
        with pytest.raises(ValidationError):
            PtzZoomInput(camera_id="abc", zoom_speed=-1001)

    def test_duration_ms_negative(self):
        with pytest.raises(ValidationError):
            PtzZoomInput(camera_id="abc", duration_ms=-1)

    def test_duration_ms_too_large(self):
        with pytest.raises(ValidationError):
            PtzZoomInput(camera_id="abc", duration_ms=5001)


# ---------------------------------------------------------------------------
# PtzPresetInput
# ---------------------------------------------------------------------------


class TestPtzPresetInput:
    def test_action_input_flag(self):
        assert PtzPresetInput.__action_input__ is True

    def test_required_fields(self):
        with pytest.raises(Exception):
            PtzPresetInput()  # missing camera_id and preset_slot

    def test_camera_id_required(self):
        with pytest.raises(Exception):
            PtzPresetInput(preset_slot=0)

    def test_preset_slot_required(self):
        with pytest.raises(Exception):
            PtzPresetInput(camera_id="abc")

    def test_valid(self):
        m = PtzPresetInput(camera_id="abc", preset_slot=3)
        assert m.preset_slot == 3

    def test_preset_slot_negative(self):
        with pytest.raises(ValidationError):
            PtzPresetInput(camera_id="abc", preset_slot=-1)

    def test_preset_slot_zero_valid(self):
        m = PtzPresetInput(camera_id="abc", preset_slot=0)
        assert m.preset_slot == 0


# ---------------------------------------------------------------------------
# RebootCameraInput
# ---------------------------------------------------------------------------


class TestRebootCameraInput:
    def test_action_input_flag(self):
        assert RebootCameraInput.__action_input__ is True

    def test_required_camera_id(self):
        with pytest.raises(Exception):
            RebootCameraInput()

    def test_valid(self):
        m = RebootCameraInput(camera_id="cam-uuid-123")
        assert m.camera_id == "cam-uuid-123"


# ---------------------------------------------------------------------------
# ToggleRecordingInput
# ---------------------------------------------------------------------------


class TestToggleRecordingInput:
    def test_action_input_flag(self):
        assert ToggleRecordingInput.__action_input__ is True

    def test_required_fields(self):
        with pytest.raises(Exception):
            ToggleRecordingInput()

    def test_camera_id_required(self):
        with pytest.raises(Exception):
            ToggleRecordingInput(enabled=True)

    def test_enabled_required(self):
        with pytest.raises(Exception):
            ToggleRecordingInput(camera_id="abc")

    def test_valid_enable(self):
        m = ToggleRecordingInput(camera_id="abc", enabled=True)
        assert m.enabled is True

    def test_valid_disable(self):
        m = ToggleRecordingInput(camera_id="abc", enabled=False)
        assert m.enabled is False


# ---------------------------------------------------------------------------
# AlarmArmInput
# ---------------------------------------------------------------------------


class TestAlarmArmInput:
    def test_action_input_flag(self):
        assert AlarmArmInput.__action_input__ is True

    def test_default_no_profile(self):
        m = AlarmArmInput()
        assert m.profile_id is None

    def test_with_profile_id(self):
        m = AlarmArmInput(profile_id="profile-uuid")
        assert m.profile_id == "profile-uuid"


# ---------------------------------------------------------------------------
# AlarmDisarmInput
# ---------------------------------------------------------------------------


class TestAlarmDisarmInput:
    def test_action_input_flag(self):
        assert AlarmDisarmInput.__action_input__ is True

    def test_no_params_needed(self):
        m = AlarmDisarmInput()
        assert m is not None

    def test_instantiates_cleanly(self):
        m = AlarmDisarmInput()
        assert isinstance(m, AlarmDisarmInput)


# ---------------------------------------------------------------------------
# TriggerChimeInput
# ---------------------------------------------------------------------------


class TestTriggerChimeInput:
    def test_action_input_flag(self):
        assert TriggerChimeInput.__action_input__ is True

    def test_required_chime_id(self):
        with pytest.raises(Exception):
            TriggerChimeInput()

    def test_defaults_applied(self):
        m = TriggerChimeInput(chime_id="chime-uuid")
        assert m.volume is None
        assert m.repeat_times is None

    def test_valid_with_overrides(self):
        m = TriggerChimeInput(chime_id="chime-uuid", volume=80, repeat_times=3)
        assert m.volume == 80
        assert m.repeat_times == 3

    def test_volume_out_of_range_high(self):
        with pytest.raises(ValidationError):
            TriggerChimeInput(chime_id="chime-uuid", volume=101)

    def test_volume_out_of_range_low(self):
        with pytest.raises(ValidationError):
            TriggerChimeInput(chime_id="chime-uuid", volume=-1)

    def test_repeat_times_out_of_range_high(self):
        with pytest.raises(ValidationError):
            TriggerChimeInput(chime_id="chime-uuid", repeat_times=7)

    def test_repeat_times_out_of_range_low(self):
        with pytest.raises(ValidationError):
            TriggerChimeInput(chime_id="chime-uuid", repeat_times=0)

    def test_volume_boundary_zero(self):
        m = TriggerChimeInput(chime_id="chime-uuid", volume=0)
        assert m.volume == 0

    def test_volume_boundary_100(self):
        m = TriggerChimeInput(chime_id="chime-uuid", volume=100)
        assert m.volume == 100

    def test_repeat_times_boundary_1(self):
        m = TriggerChimeInput(chime_id="chime-uuid", repeat_times=1)
        assert m.repeat_times == 1

    def test_repeat_times_boundary_6(self):
        m = TriggerChimeInput(chime_id="chime-uuid", repeat_times=6)
        assert m.repeat_times == 6


# ---------------------------------------------------------------------------
# ExportClipInput
# ---------------------------------------------------------------------------


class TestExportClipInput:
    def test_action_input_flag(self):
        assert ExportClipInput.__action_input__ is True

    def test_required_fields(self):
        with pytest.raises(Exception):
            ExportClipInput()

    def test_defaults_applied(self):
        m = ExportClipInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z")
        assert m.channel_index == 0
        assert m.fps is None

    def test_valid_full(self):
        m = ExportClipInput(
            camera_id="cam",
            start="2026-01-01T00:00:00Z",
            end="2026-01-01T01:00:00Z",
            channel_index=1,
            fps=4,
        )
        assert m.channel_index == 1
        assert m.fps == 4

    def test_channel_index_out_of_range_high(self):
        with pytest.raises(ValidationError):
            ExportClipInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z", channel_index=3)

    def test_channel_index_out_of_range_low(self):
        with pytest.raises(ValidationError):
            ExportClipInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z", channel_index=-1)

    def test_fps_zero_raises(self):
        with pytest.raises(ValidationError):
            ExportClipInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z", fps=0)

    def test_fps_negative_raises(self):
        with pytest.raises(ValidationError):
            ExportClipInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z", fps=-1)

    def test_channel_index_boundary_values(self):
        for idx in (0, 1, 2):
            m = ExportClipInput(
                camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z", channel_index=idx
            )
            assert m.channel_index == idx


# ---------------------------------------------------------------------------
# DeleteRecordingInput
# ---------------------------------------------------------------------------


class TestDeleteRecordingInput:
    def test_action_input_flag(self):
        assert DeleteRecordingInput.__action_input__ is True

    def test_required_fields(self):
        with pytest.raises(Exception):
            DeleteRecordingInput()

    def test_valid(self):
        m = DeleteRecordingInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T12:00:00Z")
        assert m.camera_id == "cam"
        assert m.start == "2026-01-01T00:00:00Z"
        assert m.end == "2026-01-01T12:00:00Z"


# ---------------------------------------------------------------------------
# DeleteLiveviewInput
# ---------------------------------------------------------------------------


class TestDeleteLiveviewInput:
    def test_action_input_flag(self):
        assert DeleteLiveviewInput.__action_input__ is True

    def test_required_liveview_id(self):
        with pytest.raises(Exception):
            DeleteLiveviewInput()

    def test_valid(self):
        m = DeleteLiveviewInput(liveview_id="lv-uuid")
        assert m.liveview_id == "lv-uuid"


# ---------------------------------------------------------------------------
# AcknowledgeEventInput
# ---------------------------------------------------------------------------


class TestAcknowledgeEventInput:
    def test_action_input_flag(self):
        assert AcknowledgeEventInput.__action_input__ is True

    def test_required_event_id(self):
        with pytest.raises(Exception):
            AcknowledgeEventInput()

    def test_valid(self):
        m = AcknowledgeEventInput(event_id="evt-uuid-123")
        assert m.event_id == "evt-uuid-123"
