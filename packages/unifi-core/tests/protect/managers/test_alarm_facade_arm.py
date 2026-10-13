"""Tests for AlarmRulesFacade arm/disarm — v2-first, verified against controller state."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.exceptions import BadRequest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.managers.alarm_facade import AlarmRulesFacade
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError

_NIGHT_ID = "019e473a-0000-7000-8000-000000000001"
_ALL_ID = "019e473a-0000-7000-8000-000000000002"
_V2_NIGHT = {
    "id": _NIGHT_ID,
    "title": "Arm Night",
    "state": "disarmed",
    "state_set_at": "2026-10-12T11:03:14Z",
    "activation_delay": None,
    "alarm_ids": ["a1"],
}
_V2_ALL = {
    "id": _ALL_ID,
    "title": "Arm All",
    "state": "disarmed",
    "state_set_at": "2026-10-10T21:42:22Z",
    "activation_delay": 60,
    "alarm_ids": ["a1", "a2"],
}
_LEGACY_PROFILE = {
    "id": "66a5c92a0022f903e4000401",
    "name": "Home",
    "record_everything": False,
    "activation_delay_ms": 30000,
    "schedule_count": 1,
    "automation_count": 3,
}


def _facade(profiles, after=None):
    """Facade whose v2 profile reads return ``profiles`` first, then ``after``."""
    service = MagicMock()
    legacy = MagicMock()
    reads = [profiles, after if after is not None else profiles]
    service.list_profiles = AsyncMock(side_effect=lambda: reads.pop(0) if len(reads) > 1 else reads[0])
    service.arm_profile = AsyncMock(return_value={})
    service.disarm_profile = AsyncMock(return_value={})
    legacy.list_arm_profiles = AsyncMock(return_value=[])
    legacy.is_global_alarm_manager = AsyncMock(return_value=False)
    legacy.arm = AsyncMock(return_value={"armed": True, "profile_id": "legacy"})
    legacy.disarm = AsyncMock(return_value={"armed": False})
    legacy.preview_arm = AsyncMock(return_value={"target_profile_id": "legacy"})
    legacy.preview_disarm = AsyncMock(return_value={"active_profile_id": "legacy"})
    return AlarmRulesFacade(service, legacy)


def _legacy_facade():
    facade = _facade([])
    facade._service.list_profiles = AsyncMock(return_value=[])
    facade._legacy.list_arm_profiles = AsyncMock(return_value=[_LEGACY_PROFILE])
    return facade


@pytest.mark.asyncio
async def test_arm_uses_v2_action_and_verifies_state():
    facade = _facade([_V2_NIGHT, _V2_ALL], after=[_V2_NIGHT, {**_V2_ALL, "state": "arming"}])
    result = await facade.arm(_ALL_ID)
    facade._service.arm_profile.assert_awaited_once_with(_ALL_ID)
    facade._legacy.arm.assert_not_called()
    assert result["armed"] is True
    assert result["profile_name"] == "Arm All"
    assert result["state"] == "arming"
    assert result["activation_delay_s"] == 60


@pytest.mark.asyncio
async def test_arm_resolves_profile_by_name_case_insensitively():
    facade = _facade([_V2_NIGHT, _V2_ALL], after=[{**_V2_NIGHT, "state": "armed"}, _V2_ALL])
    result = await facade.arm("arm night")
    facade._service.arm_profile.assert_awaited_once_with(_NIGHT_ID)
    assert result["profile_id"] == _NIGHT_ID
    assert result["state"] == "armed"


@pytest.mark.asyncio
async def test_arm_requires_profile_when_several_exist():
    facade = _facade([_V2_NIGHT, _V2_ALL])
    with pytest.raises(ValueError, match="profile_id is required"):
        await facade.arm(None)
    facade._service.arm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_arm_defaults_to_the_only_profile():
    facade = _facade([_V2_ALL], after=[{**_V2_ALL, "state": "armed"}])
    result = await facade.arm(None)
    facade._service.arm_profile.assert_awaited_once_with(_ALL_ID)
    assert result["state"] == "armed"


@pytest.mark.asyncio
async def test_arm_unknown_profile_raises_not_found():
    facade = _facade([_V2_NIGHT, _V2_ALL])
    with pytest.raises(UniFiNotFoundError):
        await facade.arm("nope")
    facade._service.arm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_arm_is_idempotent_when_profile_already_active():
    facade = _facade([{**_V2_NIGHT, "state": "armed"}, _V2_ALL])
    result = await facade.arm(_NIGHT_ID)
    assert result["already_armed"] is True
    assert result["state"] == "armed"
    facade._service.arm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_arm_reports_silent_noop_as_error():
    facade = _facade([_V2_NIGHT, _V2_ALL], after=[_V2_NIGHT, _V2_ALL])
    with pytest.raises(ValueError, match="still 'disarmed'"):
        await facade.arm(_ALL_ID)


@pytest.mark.asyncio
async def test_arm_falls_back_to_legacy_when_v2_unavailable():
    facade = _legacy_facade()
    result = await facade.arm("66a5c92a0022f903e4000401")
    facade._legacy.arm.assert_awaited_once_with("66a5c92a0022f903e4000401")
    facade._service.arm_profile.assert_not_called()
    assert result["profile_id"] == "legacy"


@pytest.mark.asyncio
async def test_disarm_all_active_profiles_and_verifies():
    active = [{**_V2_NIGHT, "state": "armed"}, {**_V2_ALL, "state": "arming"}]
    facade = _facade(active, after=[_V2_NIGHT, _V2_ALL])
    result = await facade.disarm(None)
    assert facade._service.disarm_profile.await_count == 2
    assert result["armed"] is False
    assert [p["profile_name"] for p in result["profiles"]] == ["Arm Night", "Arm All"]
    assert all(p["state"] == "disarmed" for p in result["profiles"])


@pytest.mark.asyncio
async def test_disarm_single_profile_by_id_leaves_others_alone():
    active = [{**_V2_NIGHT, "state": "armed"}, {**_V2_ALL, "state": "armed"}]
    facade = _facade(active, after=[_V2_NIGHT, {**_V2_ALL, "state": "armed"}])
    result = await facade.disarm(_NIGHT_ID)
    facade._service.disarm_profile.assert_awaited_once_with(_NIGHT_ID)
    assert result["profiles"][0]["profile_id"] == _NIGHT_ID


@pytest.mark.asyncio
async def test_disarm_is_idempotent_when_nothing_active():
    facade = _facade([_V2_NIGHT, _V2_ALL])
    result = await facade.disarm(None)
    assert result == {"armed": False, "already_disarmed": True}
    facade._service.disarm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_disarm_reports_silent_noop_as_error():
    active = [{**_V2_NIGHT, "state": "armed"}, _V2_ALL]
    facade = _facade(active, after=active)
    with pytest.raises(ValueError, match="still 'armed'"):
        await facade.disarm(None)


@pytest.mark.asyncio
async def test_disarm_falls_back_to_legacy_when_v2_unavailable():
    facade = _legacy_facade()
    await facade.disarm(None)
    facade._legacy.disarm.assert_awaited_once_with()
    facade._service.disarm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_preview_arm_and_disarm_reflect_v2_state():
    facade = _facade([{**_V2_NIGHT, "state": "armed"}, _V2_ALL])
    arm_preview = await facade.preview_arm(_ALL_ID)
    assert arm_preview["target_profile_name"] == "Arm All"
    assert arm_preview["current_state"]["armed"] is True
    assert arm_preview["current_state"]["active_profile_id"] == _NIGHT_ID
    assert arm_preview["proposed_changes"] == {"armed": True, "active_profile_id": _ALL_ID}

    disarm_preview = await facade.preview_disarm(None)
    assert disarm_preview["active_profile_name"] == "Arm Night"
    assert disarm_preview["current_state"]["profiles"] == [{"id": _NIGHT_ID, "name": "Arm Night", "state": "armed"}]
    facade._legacy.preview_arm.assert_not_called()
    facade._legacy.preview_disarm.assert_not_called()


@pytest.mark.asyncio
async def test_previews_fall_back_to_legacy_when_v2_unavailable():
    facade = _legacy_facade()
    assert await facade.preview_arm(None) == {"target_profile_id": "legacy"}
    assert await facade.preview_disarm(None) == {"active_profile_id": "legacy"}


# ---------------------------------------------------------------------------
# Backend selection must fail closed on a Global-mode console
# ---------------------------------------------------------------------------

_PERM = AlarmManagerPermissionError("SuperAdmin is required for Alarm Manager v2")


def _blocked_facade(v2_error, global_mode):
    """v2 profiles unavailable (403 / 4xx / empty), legacy profiles exist, console mode as given."""
    facade = _facade([])
    facade._service.list_profiles = AsyncMock(side_effect=v2_error, return_value=[] if v2_error is None else None)
    facade._legacy.list_arm_profiles = AsyncMock(return_value=[_LEGACY_PROFILE])
    facade._legacy.is_global_alarm_manager = AsyncMock(
        side_effect=global_mode if isinstance(global_mode, Exception) else None, return_value=global_mode
    )
    return facade


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["arm", "disarm", "preview_arm", "preview_disarm"])
async def test_v2_forbidden_in_global_mode_never_mutates_legacy(operation):
    facade = _blocked_facade(_PERM, global_mode=True)
    with pytest.raises(AlarmManagerPermissionError, match="Global mode"):
        await getattr(facade, operation)(None)
    facade._legacy.arm.assert_not_called()
    facade._legacy.disarm.assert_not_called()
    facade._legacy.preview_arm.assert_not_called()
    facade._legacy.preview_disarm.assert_not_called()
    facade._service.arm_profile.assert_not_called()
    facade._service.disarm_profile.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("v2_error", [None, BadRequest("unsupported")])
async def test_v2_empty_or_rejected_in_global_mode_never_mutates_legacy(v2_error):
    facade = _blocked_facade(v2_error, global_mode=True)
    with pytest.raises(ValueError, match="Global mode"):
        await facade.arm("Home")
    with pytest.raises(ValueError, match="Global mode"):
        await facade.disarm(None)
    facade._legacy.arm.assert_not_called()
    facade._legacy.disarm.assert_not_called()


@pytest.mark.asyncio
async def test_v2_forbidden_in_local_mode_falls_back_to_legacy():
    facade = _blocked_facade(_PERM, global_mode=False)
    result = await facade.arm("66a5c92a0022f903e4000401")
    facade._legacy.arm.assert_awaited_once_with("66a5c92a0022f903e4000401")
    assert result["profile_id"] == "legacy"
    await facade.disarm(None)
    facade._legacy.disarm.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_unreadable_console_mode_fails_closed():
    facade = _blocked_facade(_PERM, global_mode=RuntimeError("nvr unreachable"))
    with pytest.raises(ValueError, match="Cannot determine"):
        await facade.arm(None)
    facade._legacy.arm.assert_not_called()


@pytest.mark.asyncio
async def test_v2_profiles_served_skips_mode_check():
    facade = _facade([_V2_ALL], after=[{**_V2_ALL, "state": "armed"}])
    await facade.arm(None)
    facade._legacy.is_global_alarm_manager.assert_not_called()
