"""Tests for AlarmManager (arm/disarm via Protect Alarm Manager)."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from unifi_core.protect.managers.alarm_manager import AlarmManager

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


_PROFILES_RESPONSE = [
    {
        "id": "p-night",
        "name": "Arm Night",
        "recordEverything": False,
        "activationDelay": 60000,
        "schedules": [],
        "automations": ["a1", "a2"],
    },
    {
        "id": "p-all",
        "name": "Arm All",
        "recordEverything": True,
        "activationDelay": 30000,
        "schedules": [{"id": "s1"}],
        "automations": [],
    },
]


def _nvr_response(status="disabled", profile_id="p-night", armed_at=None):
    return {
        "mac": "AABBCCDDEEFF",
        "name": "UNVR",
        "armMode": {
            "status": status,
            "armProfileId": profile_id,
            "armedAt": armed_at,
            "willBeArmedAt": None,
            "breachDetectedAt": 1775310901100,
            "breachEventCount": 0,
            "breachTriggerEventId": None,
            "breachEventId": "evt-1",
        },
    }


def _make_cm(responses):
    """Build a mock connection manager with a queued api_request side_effect."""
    cm = MagicMock()
    cm.client.api_request = AsyncMock(side_effect=list(responses))
    return cm


# ---------------------------------------------------------------------------
# list_arm_profiles
# ---------------------------------------------------------------------------


class TestListArmProfiles:
    @pytest.mark.asyncio
    async def test_formats_profiles(self):
        cm = _make_cm([_PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        profiles = await mgr.list_arm_profiles()

        assert len(profiles) == 2
        assert profiles[0] == {
            "id": "p-night",
            "name": "Arm Night",
            "record_everything": False,
            "activation_delay_ms": 60000,
            "schedule_count": 0,
            "automation_count": 2,
        }
        assert profiles[1]["schedule_count"] == 1
        cm.client.api_request.assert_awaited_once_with("arm/profiles", method="get")

    @pytest.mark.asyncio
    async def test_non_list_response(self):
        cm = _make_cm([{"error": "nope"}])
        mgr = AlarmManager(cm)
        assert await mgr.list_arm_profiles() == []


# ---------------------------------------------------------------------------
# get_arm_state
# ---------------------------------------------------------------------------


class TestGetArmState:
    @pytest.mark.parametrize(
        ("status", "armed_at", "expected_armed", "expected_armed_at"),
        [
            ("disabled", None, False, None),
            ("armed", 1775400000000, True, "2026-04-05T14:40:00+00:00"),
            ("active", None, True, None),
            ("disarmed", None, False, None),
        ],
    )
    @pytest.mark.asyncio
    async def test_status_aliases(self, status, armed_at, expected_armed, expected_armed_at):
        cm = _make_cm([_nvr_response(status=status, armed_at=armed_at), _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        state = await mgr.get_arm_state()

        assert state["armed"] is expected_armed
        assert state["status"] == status
        assert state["active_profile_id"] == "p-night"
        assert state["active_profile_name"] == "Arm Night"
        assert state["armed_at"] == expected_armed_at
        assert len(state["profiles"]) == 2

    @pytest.mark.asyncio
    async def test_unknown_profile_id(self):
        cm = _make_cm([_nvr_response(status="disabled", profile_id="p-ghost"), _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        state = await mgr.get_arm_state()
        assert state["active_profile_id"] == "p-ghost"
        assert state["active_profile_name"] is None

    @pytest.mark.asyncio
    async def test_empty_armmode(self):
        cm = _make_cm([{"mac": "x"}, _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        state = await mgr.get_arm_state()
        assert state["armed"] is False
        assert state["status"] is None


# ---------------------------------------------------------------------------
# _resolve_profile_id
# ---------------------------------------------------------------------------


class TestResolveProfileId:
    @pytest.mark.asyncio
    async def test_explicit_passthrough_no_api_call(self):
        cm = _make_cm([])
        mgr = AlarmManager(cm)
        assert await mgr._resolve_profile_id("p-explicit") == "p-explicit"
        cm.client.api_request.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_falls_back_to_nvr_armmode_profile(self):
        cm = _make_cm([_nvr_response(profile_id="p-night"), _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        assert await mgr._resolve_profile_id(None) == "p-night"

    @pytest.mark.asyncio
    async def test_falls_back_to_first_profile_when_no_current(self):
        nvr = _nvr_response()
        nvr["armMode"]["armProfileId"] = None
        cm = _make_cm([nvr, _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        assert await mgr._resolve_profile_id(None) == "p-night"

    @pytest.mark.asyncio
    async def test_raises_when_no_profiles(self):
        nvr = _nvr_response()
        nvr["armMode"]["armProfileId"] = None
        cm = _make_cm([nvr, []])
        mgr = AlarmManager(cm)
        with pytest.raises(ValueError, match="No arm profiles"):
            await mgr._resolve_profile_id(None)


# ---------------------------------------------------------------------------
# preview_arm / preview_disarm
# ---------------------------------------------------------------------------


class TestPreviewArm:
    @pytest.mark.asyncio
    async def test_preview_with_explicit_profile(self):
        cm = _make_cm([_nvr_response(status="disabled", profile_id="p-night"), _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        preview = await mgr.preview_arm("p-all")

        assert preview["target_profile_id"] == "p-all"
        assert preview["target_profile_name"] == "Arm All"
        assert preview["current_state"]["armed"] is False
        assert preview["current_state"]["active_profile_id"] == "p-night"
        assert preview["proposed_changes"] == {"armed": True, "active_profile_id": "p-all"}

    @pytest.mark.asyncio
    async def test_preview_reflects_armed_current_state(self):
        cm = _make_cm([_nvr_response(status="armed", profile_id="p-night"), _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        preview = await mgr.preview_arm(None)

        assert preview["target_profile_id"] == "p-night"
        assert preview["current_state"]["armed"] is True
        assert preview["current_state"]["status"] == "armed"

    @pytest.mark.asyncio
    async def test_preview_raises_without_profiles(self):
        nvr = _nvr_response()
        nvr["armMode"]["armProfileId"] = None
        cm = _make_cm([nvr, []])
        mgr = AlarmManager(cm)
        with pytest.raises(ValueError, match="No arm profiles"):
            await mgr.preview_arm(None)


class TestPreviewDisarm:
    @pytest.mark.asyncio
    async def test_preview_disarm_when_armed(self):
        cm = _make_cm([_nvr_response(status="armed", profile_id="p-night"), _PROFILES_RESPONSE])
        mgr = AlarmManager(cm)
        preview = await mgr.preview_disarm()

        assert preview["active_profile_id"] == "p-night"
        assert preview["active_profile_name"] == "Arm Night"
        assert preview["current_state"]["armed"] is True
        assert preview["proposed_changes"] == {"armed": False}


# ---------------------------------------------------------------------------
# arm / disarm
# ---------------------------------------------------------------------------


class TestArm:
    @pytest.mark.asyncio
    async def test_arm_with_explicit_profile_patches_then_posts(self):
        cm = _make_cm(
            [
                _nvr_response(status="disabled", profile_id="p-night"),  # state check
                _PROFILES_RESPONSE,
                None,  # PATCH arm (select profile)
                None,  # POST arm/enable
            ]
        )
        mgr = AlarmManager(cm)
        result = await mgr.arm("p-all")

        assert result == {
            "armed": True,
            "profile_id": "p-all",
            "profile_name": "Arm All",
        }

        mutating_calls = [
            c for c in cm.client.api_request.await_args_list if c.kwargs.get("method") in ("patch", "post")
        ]
        assert mutating_calls[0] == call("arm", method="patch", json={"armProfileId": "p-all"})
        assert mutating_calls[1] == call("arm/enable", method="post")

    @pytest.mark.asyncio
    async def test_arm_no_profile_uses_currently_selected(self):
        cm = _make_cm(
            [
                _nvr_response(status="disabled", profile_id="p-night"),
                _PROFILES_RESPONSE,
                None,  # POST arm/enable
            ]
        )
        mgr = AlarmManager(cm)
        result = await mgr.arm(None)

        assert result["profile_id"] == "p-night"
        assert result["profile_name"] == "Arm Night"

        # No PATCH when profile_id is None and matches current selection
        patch_calls = [c for c in cm.client.api_request.await_args_list if c.kwargs.get("method") == "patch"]
        assert patch_calls == []

        post_calls = [c for c in cm.client.api_request.await_args_list if c.args == ("arm/enable",)]
        assert len(post_calls) == 1

    @pytest.mark.asyncio
    async def test_arm_idempotent_when_already_armed_same_profile(self):
        cm = _make_cm(
            [
                _nvr_response(status="armed", profile_id="p-night"),
                _PROFILES_RESPONSE,
            ]
        )
        mgr = AlarmManager(cm)
        result = await mgr.arm("p-night")

        assert result == {
            "armed": True,
            "profile_id": "p-night",
            "profile_name": "Arm Night",
            "already_armed": True,
        }
        # No PATCH, no POST
        mutating = [c for c in cm.client.api_request.await_args_list if c.kwargs.get("method") in ("patch", "post")]
        assert mutating == []

    @pytest.mark.asyncio
    async def test_arm_raises_when_switching_profile_while_armed(self):
        cm = _make_cm(
            [
                _nvr_response(status="armed", profile_id="p-night"),
                _PROFILES_RESPONSE,
            ]
        )
        mgr = AlarmManager(cm)
        with pytest.raises(ValueError, match="Cannot switch arm profile while system is armed"):
            await mgr.arm("p-all")

        # No PATCH, no POST should be issued
        mutating = [c for c in cm.client.api_request.await_args_list if c.kwargs.get("method") in ("patch", "post")]
        assert mutating == []


class TestDisarm:
    @pytest.mark.asyncio
    async def test_disarm_posts_disable_no_body(self):
        cm = _make_cm(
            [
                _nvr_response(status="armed", profile_id="p-night"),  # get_arm_state -> nvr
                _PROFILES_RESPONSE,  # get_arm_state -> profiles
                None,  # POST arm/disable
            ]
        )
        mgr = AlarmManager(cm)
        result = await mgr.disarm()

        assert result == {"armed": False}
        post_calls = [c for c in cm.client.api_request.await_args_list if c.args == ("arm/disable",)]
        assert len(post_calls) == 1

    @pytest.mark.asyncio
    async def test_disarm_idempotent_when_already_disarmed(self):
        cm = _make_cm(
            [
                _nvr_response(status="disabled"),
                _PROFILES_RESPONSE,
            ]
        )
        mgr = AlarmManager(cm)
        result = await mgr.disarm()

        assert result == {"armed": False, "already_disarmed": True}
        post_calls = [c for c in cm.client.api_request.await_args_list if c.args == ("arm/disable",)]
        assert post_calls == []
