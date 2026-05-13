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


# ---------------------------------------------------------------------------
# LockDoorInput
# ---------------------------------------------------------------------------


class TestLockDoorInput:
    def test_action_input_flag(self):
        assert LockDoorInput.__action_input__ is True

    def test_required_door_id(self):
        with pytest.raises(ValidationError):
            LockDoorInput()

    def test_valid_construction(self):
        m = LockDoorInput(door_id="door-uuid-123")
        assert m.door_id == "door-uuid-123"


# ---------------------------------------------------------------------------
# UnlockDoorInput
# ---------------------------------------------------------------------------


class TestUnlockDoorInput:
    def test_action_input_flag(self):
        assert UnlockDoorInput.__action_input__ is True

    def test_required_door_id(self):
        with pytest.raises(ValidationError):
            UnlockDoorInput()

    def test_duration_default(self):
        m = UnlockDoorInput(door_id="door-uuid-456")
        assert m.duration == 2

    def test_duration_boundary_min(self):
        m = UnlockDoorInput(door_id="door-uuid-456", duration=1)
        assert m.duration == 1

    def test_duration_boundary_max(self):
        m = UnlockDoorInput(door_id="door-uuid-456", duration=300)
        assert m.duration == 300

    def test_duration_below_min(self):
        with pytest.raises(ValidationError):
            UnlockDoorInput(door_id="door-uuid-456", duration=0)

    def test_duration_above_max(self):
        with pytest.raises(ValidationError):
            UnlockDoorInput(door_id="door-uuid-456", duration=301)

    def test_valid_full(self):
        m = UnlockDoorInput(door_id="door-uuid-789", duration=30)
        assert m.door_id == "door-uuid-789"
        assert m.duration == 30


# ---------------------------------------------------------------------------
# RebootDeviceInput
# ---------------------------------------------------------------------------


class TestRebootDeviceInput:
    def test_action_input_flag(self):
        assert RebootDeviceInput.__action_input__ is True

    def test_required_device_id(self):
        with pytest.raises(ValidationError):
            RebootDeviceInput()

    def test_valid_construction(self):
        m = RebootDeviceInput(device_id="device-uuid-123")
        assert m.device_id == "device-uuid-123"


# ---------------------------------------------------------------------------
# RevokeCredentialInput
# ---------------------------------------------------------------------------


class TestRevokeCredentialInput:
    def test_action_input_flag(self):
        assert RevokeCredentialInput.__action_input__ is True

    def test_required_credential_id(self):
        with pytest.raises(ValidationError):
            RevokeCredentialInput()

    def test_valid_construction(self):
        m = RevokeCredentialInput(credential_id="cred-uuid-123")
        assert m.credential_id == "cred-uuid-123"


# ---------------------------------------------------------------------------
# DeleteVisitorInput
# ---------------------------------------------------------------------------


class TestDeleteVisitorInput:
    def test_action_input_flag(self):
        assert DeleteVisitorInput.__action_input__ is True

    def test_required_visitor_id(self):
        with pytest.raises(ValidationError):
            DeleteVisitorInput()

    def test_valid_construction(self):
        m = DeleteVisitorInput(visitor_id="visitor-uuid-123")
        assert m.visitor_id == "visitor-uuid-123"
