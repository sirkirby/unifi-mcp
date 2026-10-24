"""Tests for Protect action-tool input models (_actions.py)."""

import pytest
from pydantic import ValidationError
from unifi_core.protect.models._actions import (
    AcknowledgeEventInput,
    AlarmArmInput,
    AlarmCreateRuleInput,
    AlarmDisarmInput,
    AlarmUpdateRuleInput,
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

_ACTION_INPUT_MODELS = (
    AlarmCreateRuleInput,
    AlarmUpdateRuleInput,
    PtzMoveInput,
    PtzZoomInput,
    PtzPresetInput,
    RebootCameraInput,
    ToggleRecordingInput,
    AlarmArmInput,
    AlarmDisarmInput,
    TriggerChimeInput,
    ExportClipInput,
    DeleteRecordingInput,
    DeleteLiveviewInput,
    AcknowledgeEventInput,
)

_REQUIRED_EMPTY_MODELS = (
    PtzMoveInput,
    PtzZoomInput,
    PtzPresetInput,
    RebootCameraInput,
    ToggleRecordingInput,
    TriggerChimeInput,
    ExportClipInput,
    DeleteRecordingInput,
    DeleteLiveviewInput,
    AcknowledgeEventInput,
)


def _valid_rule_body(actions: list | None = None) -> dict:
    """Minimum body shape that satisfies the create/update validators.

    Real Protect bodies are richer (sources/conditions/cooldown/etc.); we
    only need enough here to drive the actions-non-empty validator.
    """
    return {
        "name": "Test",
        "enable": False,
        "actions": [{"type": "HTTP_REQUEST", "metadata": {"url": "https://example.test/wh"}}]
        if actions is None
        else actions,
    }


@pytest.mark.parametrize("model", _ACTION_INPUT_MODELS, ids=lambda m: m.__name__)
def test_action_input_flag(model) -> None:
    assert model.__action_input__ is True


@pytest.mark.parametrize("model", _REQUIRED_EMPTY_MODELS, ids=lambda m: m.__name__)
def test_required_fields_empty_constructor(model) -> None:
    with pytest.raises(Exception):
        model()


# ---------------------------------------------------------------------------
# AlarmCreateRuleInput / AlarmUpdateRuleInput — shape validation only
# ---------------------------------------------------------------------------


class TestAlarmCreateRuleInput:
    def test_valid_with_actions(self) -> None:
        m = AlarmCreateRuleInput(body=_valid_rule_body())
        assert m.body["actions"]

    def test_allows_body_without_actions_guard_lives_in_facade(self) -> None:
        m = AlarmCreateRuleInput(body={"title": "x"})
        assert m.body == {"title": "x"}


class TestAlarmUpdateRuleInput:
    def test_valid_with_actions(self) -> None:
        m = AlarmUpdateRuleInput(rule_id="r-1", body=_valid_rule_body())
        assert m.rule_id == "r-1"

    def test_allows_partial_update_without_actions_guard_lives_in_facade(self) -> None:
        m = AlarmUpdateRuleInput(rule_id="r-1", body={"title": "x"})
        assert m.body == {"title": "x"}


# ---------------------------------------------------------------------------
# PtzMoveInput
# ---------------------------------------------------------------------------


class TestPtzMoveInput:
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

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"pan": 1500},
            {"pan": -1001},
            {"tilt": 1001},
            {"duration_ms": -1},
            {"duration_ms": 5001},
        ],
        ids=["pan_high", "pan_low", "tilt_high", "duration_negative", "duration_too_large"],
    )
    def test_out_of_range(self, kwargs):
        with pytest.raises(ValidationError):
            PtzMoveInput(camera_id="abc", **kwargs)


# ---------------------------------------------------------------------------
# PtzZoomInput
# ---------------------------------------------------------------------------


class TestPtzZoomInput:
    def test_defaults_applied(self):
        m = PtzZoomInput(camera_id="abc")
        assert m.zoom_speed == 0
        assert m.duration_ms == 250

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"zoom_speed": 1001},
            {"zoom_speed": -1001},
            {"duration_ms": -1},
            {"duration_ms": 5001},
        ],
        ids=["zoom_high", "zoom_low", "duration_negative", "duration_too_large"],
    )
    def test_out_of_range(self, kwargs):
        with pytest.raises(ValidationError):
            PtzZoomInput(camera_id="abc", **kwargs)


# ---------------------------------------------------------------------------
# PtzPresetInput
# ---------------------------------------------------------------------------


class TestPtzPresetInput:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"preset_slot": 0},
            {"camera_id": "abc"},
        ],
        ids=["missing_camera_id", "missing_preset_slot"],
    )
    def test_individual_required_fields(self, kwargs):
        with pytest.raises(Exception):
            PtzPresetInput(**kwargs)

    @pytest.mark.parametrize("preset_slot", [3, 0], ids=["slot_3", "slot_zero"])
    def test_valid(self, preset_slot):
        m = PtzPresetInput(camera_id="abc", preset_slot=preset_slot)
        assert m.preset_slot == preset_slot

    def test_preset_slot_negative(self):
        with pytest.raises(ValidationError):
            PtzPresetInput(camera_id="abc", preset_slot=-1)


# ---------------------------------------------------------------------------
# RebootCameraInput
# ---------------------------------------------------------------------------


class TestRebootCameraInput:
    def test_valid(self):
        m = RebootCameraInput(camera_id="cam-uuid-123")
        assert m.camera_id == "cam-uuid-123"


# ---------------------------------------------------------------------------
# ToggleRecordingInput
# ---------------------------------------------------------------------------


class TestToggleRecordingInput:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"enabled": True},
            {"camera_id": "abc"},
        ],
        ids=["missing_camera_id", "missing_enabled"],
    )
    def test_individual_required_fields(self, kwargs):
        with pytest.raises(Exception):
            ToggleRecordingInput(**kwargs)

    @pytest.mark.parametrize("enabled", [True, False], ids=["enable", "disable"])
    def test_valid(self, enabled):
        m = ToggleRecordingInput(camera_id="abc", enabled=enabled)
        assert m.enabled is enabled


# ---------------------------------------------------------------------------
# AlarmArmInput
# ---------------------------------------------------------------------------


class TestAlarmArmInput:
    @pytest.mark.parametrize(
        "kwargs, expected",
        [
            ({}, None),
            ({"profile_id": "profile-uuid"}, "profile-uuid"),
        ],
        ids=["default_none", "with_profile"],
    )
    def test_profile_id(self, kwargs, expected):
        m = AlarmArmInput(**kwargs)
        assert m.profile_id == expected


# ---------------------------------------------------------------------------
# AlarmDisarmInput
# ---------------------------------------------------------------------------


class TestAlarmDisarmInput:
    def test_instantiates_cleanly(self):
        m = AlarmDisarmInput()
        assert isinstance(m, AlarmDisarmInput)


# ---------------------------------------------------------------------------
# TriggerChimeInput
# ---------------------------------------------------------------------------


class TestTriggerChimeInput:
    def test_defaults_applied(self):
        m = TriggerChimeInput(chime_id="chime-uuid")
        assert m.volume is None
        assert m.repeat_times is None

    def test_valid_with_overrides(self):
        m = TriggerChimeInput(chime_id="chime-uuid", volume=80, repeat_times=3)
        assert m.volume == 80
        assert m.repeat_times == 3

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"volume": 101},
            {"volume": -1},
            {"repeat_times": 7},
            {"repeat_times": 0},
        ],
        ids=["volume_high", "volume_low", "repeat_high", "repeat_low"],
    )
    def test_out_of_range(self, kwargs):
        with pytest.raises(ValidationError):
            TriggerChimeInput(chime_id="chime-uuid", **kwargs)

    @pytest.mark.parametrize(
        "kwargs, attr, expected",
        [
            ({"volume": 0}, "volume", 0),
            ({"volume": 100}, "volume", 100),
            ({"repeat_times": 1}, "repeat_times", 1),
            ({"repeat_times": 6}, "repeat_times", 6),
        ],
        ids=["volume_0", "volume_100", "repeat_1", "repeat_6"],
    )
    def test_boundary_valid(self, kwargs, attr, expected):
        m = TriggerChimeInput(chime_id="chime-uuid", **kwargs)
        assert getattr(m, attr) == expected


# ---------------------------------------------------------------------------
# ExportClipInput
# ---------------------------------------------------------------------------


class TestExportClipInput:
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

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"channel_index": 3},
            {"channel_index": -1},
            {"fps": 0},
            {"fps": -1},
        ],
        ids=["channel_high", "channel_low", "fps_zero", "fps_negative"],
    )
    def test_out_of_range(self, kwargs):
        with pytest.raises(ValidationError):
            ExportClipInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T01:00:00Z", **kwargs)

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
    def test_valid(self):
        m = DeleteRecordingInput(camera_id="cam", start="2026-01-01T00:00:00Z", end="2026-01-01T12:00:00Z")
        assert m.camera_id == "cam"
        assert m.start == "2026-01-01T00:00:00Z"
        assert m.end == "2026-01-01T12:00:00Z"


# ---------------------------------------------------------------------------
# DeleteLiveviewInput
# ---------------------------------------------------------------------------


class TestDeleteLiveviewInput:
    def test_valid(self):
        m = DeleteLiveviewInput(liveview_id="lv-uuid")
        assert m.liveview_id == "lv-uuid"


# ---------------------------------------------------------------------------
# AcknowledgeEventInput
# ---------------------------------------------------------------------------


class TestAcknowledgeEventInput:
    def test_valid(self):
        m = AcknowledgeEventInput(event_id="evt-uuid-123")
        assert m.event_id == "evt-uuid-123"
