"""Tests for Access action-tool input models (_actions.py)."""

import pytest
from pydantic import ValidationError
from unifi_core.access.models._actions import (
    DeleteVisitorInput,
    LockDoorInput,
    RebootDeviceInput,
    RevokeCredentialInput,
    UnlockDoorInput,
)


@pytest.mark.parametrize(
    "model",
    [LockDoorInput, UnlockDoorInput, RebootDeviceInput, DeleteVisitorInput],
)
def test_action_input_flag(model):
    assert model.__action_input__ is True


@pytest.mark.parametrize(
    "model",
    [LockDoorInput, UnlockDoorInput, RebootDeviceInput, DeleteVisitorInput],
)
def test_required_id(model):
    with pytest.raises(ValidationError):
        model()


@pytest.mark.parametrize(
    ("model", "field", "value"),
    [
        (LockDoorInput, "door_id", "door-uuid-123"),
        (RebootDeviceInput, "device_id", "device-uuid-123"),
        (DeleteVisitorInput, "visitor_id", "visitor-uuid-123"),
    ],
)
def test_valid_construction(model, field, value):
    constructed = model(**{field: value})
    assert getattr(constructed, field) == value


class TestUnlockDoorInput:
    def test_duration_default(self):
        m = UnlockDoorInput(door_id="door-uuid-456")
        assert m.duration == 2

    @pytest.mark.parametrize("duration", [1, 30, 300])
    def test_duration_accepted(self, duration):
        m = UnlockDoorInput(door_id="door-uuid-456", duration=duration)
        assert m.door_id == "door-uuid-456"
        assert m.duration == duration

    @pytest.mark.parametrize("duration", [0, 301])
    def test_duration_out_of_range(self, duration):
        with pytest.raises(ValidationError):
            UnlockDoorInput(door_id="door-uuid-456", duration=duration)


class TestRevokeCredentialInput:
    def test_action_input_flag(self):
        assert RevokeCredentialInput.__action_input__ is True

    def test_required_credential_id(self):
        with pytest.raises(ValidationError):
            RevokeCredentialInput()

    def test_valid_construction(self):
        m = RevokeCredentialInput(credential_id="cred-uuid-123")
        assert m.credential_id == "cred-uuid-123"
