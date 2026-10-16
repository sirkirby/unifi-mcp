"""AlarmRulesFacade arm/disarm: real mode detection and explicit v2 state verification."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.protect.managers.alarm_facade import AlarmRulesFacade
from unifi_core.protect.managers.alarm_manager import AlarmManager
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError

_NIGHT_ID = "019e473a-0000-7000-8000-000000000001"
_ALL_ID = "019e473a-0000-7000-8000-000000000002"
_NIGHT = {"id": _NIGHT_ID, "title": "Arm Night", "state": "disarmed", "alarm_ids": ["a1"]}
_ALL = {"id": _ALL_ID, "title": "Arm All", "state": "disarmed", "activation_delay": 60, "alarm_ids": ["a1", "a2"]}
_NO_STATE = {k: v for k, v in _NIGHT.items() if k != "state"}
_PERM = AlarmManagerPermissionError("SuperAdmin is required for Alarm Manager v2")


def _facade(profiles, after=None):
    """v2 serves ``profiles`` on the first read and ``after`` on the post-action re-read."""
    service = MagicMock()
    legacy = MagicMock()
    reads = [profiles, after if after is not None else profiles]
    service.list_profiles = AsyncMock(side_effect=lambda: reads.pop(0) if len(reads) > 1 else reads[0])
    service.arm_profile = AsyncMock(return_value={})
    service.disarm_profile = AsyncMock(return_value={})
    legacy.is_global_alarm_manager = AsyncMock(return_value=False)
    return AlarmRulesFacade(service, legacy)


def _facade_with_real_mode_reader(nvr_payload):
    """v2 forbidden, legacy profiles exist; the console mode comes from the real reader."""
    service = MagicMock()
    service.list_profiles = AsyncMock(side_effect=_PERM)
    service.arm_profile = AsyncMock()
    service.disarm_profile = AsyncMock()
    cm = MagicMock()
    cm.client.api_request = AsyncMock(return_value=nvr_payload)
    legacy = AlarmManager(cm)
    legacy.arm = AsyncMock(return_value={"armed": True, "profile_id": "legacy"})
    legacy.disarm = AsyncMock(return_value={"armed": False})
    legacy.preview_arm = AsyncMock(return_value={"target_profile_id": "legacy"})
    legacy.preview_disarm = AsyncMock(return_value={"active_profile_id": "legacy"})
    return AlarmRulesFacade(service, legacy)


# ---------------------------------------------------------------------------
# Mode detection through the real AlarmManager.is_global_alarm_manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nvr_payload", [{}, {"featureFlags": {}}, {"featureFlags": {"useExternalAlarmManager": False}}]
)
async def test_real_mode_reader_local_console_still_uses_legacy(nvr_payload):
    facade = _facade_with_real_mode_reader(nvr_payload)
    await facade.arm("66a5c92a0022f903e4000401")
    await facade.disarm(None)
    facade._legacy.arm.assert_awaited_once_with("66a5c92a0022f903e4000401")
    facade._legacy.disarm.assert_awaited_once_with()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "nvr_payload",
    [
        None,
        {"featureFlags": None},
        {"featureFlags": {"useExternalAlarmManager": None}},
        {"featureFlags": {"useExternalAlarmManager": "true"}},
    ],
)
@pytest.mark.parametrize("operation", ["arm", "disarm", "preview_arm", "preview_disarm"])
async def test_real_mode_reader_malformed_payload_fails_closed(nvr_payload, operation):
    facade = _facade_with_real_mode_reader(nvr_payload)
    with pytest.raises(ValueError, match="Cannot determine"):
        await getattr(facade, operation)(None)
    facade._legacy.arm.assert_not_called()
    facade._legacy.disarm.assert_not_called()
    facade._legacy.preview_arm.assert_not_called()
    facade._legacy.preview_disarm.assert_not_called()


@pytest.mark.asyncio
async def test_real_mode_reader_global_console_raises_permission_error():
    facade = _facade_with_real_mode_reader({"featureFlags": {"useExternalAlarmManager": True}})
    with pytest.raises(AlarmManagerPermissionError, match="Global mode"):
        await facade.arm(None)
    facade._legacy.arm.assert_not_called()


# ---------------------------------------------------------------------------
# Missing state is never read as disarmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", [_NO_STATE, {**_NIGHT, "state": None}, {**_NIGHT, "state": "  "}])
async def test_arm_refuses_profile_without_state(profile):
    facade = _facade([profile, _ALL])
    with pytest.raises(ValueError, match="no state"):
        await facade.arm(_NIGHT_ID)
    facade._service.arm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_disarm_by_id_refuses_profile_without_state():
    facade = _facade([_NO_STATE, _ALL])
    with pytest.raises(ValueError, match="no state"):
        await facade.disarm(_NIGHT_ID)
    facade._service.disarm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_disarm_all_refuses_when_any_profile_lacks_state():
    facade = _facade([_NO_STATE, {**_ALL, "state": "armed"}])
    with pytest.raises(ValueError, match="no state"):
        await facade.disarm(None)
    facade._service.disarm_profile.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation,profile_id", [("preview_arm", _ALL_ID), ("preview_disarm", None)])
async def test_previews_refuse_profile_without_state(operation, profile_id):
    facade = _facade([_NO_STATE, _ALL])
    with pytest.raises(ValueError, match="no state"):
        await getattr(facade, operation)(profile_id)


@pytest.mark.asyncio
async def test_targeted_disarm_preview_ignores_other_profiles_states():
    facade = _facade([_NO_STATE, {**_ALL, "state": "armed"}])
    preview = await facade.preview_disarm(_ALL_ID)
    assert preview["active_profile_id"] == _ALL_ID


@pytest.mark.asyncio
async def test_arm_reread_without_state_is_not_verified():
    facade = _facade([_NIGHT, _ALL], after=[_NO_STATE, _ALL])
    with pytest.raises(ValueError, match="still None"):
        await facade.arm(_NIGHT_ID)


@pytest.mark.asyncio
async def test_disarm_reread_without_state_is_not_verified():
    facade = _facade([{**_NIGHT, "state": "armed"}, _ALL], after=[_NO_STATE, _ALL])
    with pytest.raises(ValueError, match="still None"):
        await facade.disarm(_NIGHT_ID)


# ---------------------------------------------------------------------------
# Verification requires the expected state explicitly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("after_state", ["disarming", "breached", "future-state"])
async def test_arm_reread_in_unexpected_state_is_not_verified(after_state):
    facade = _facade([_NIGHT, _ALL], after=[{**_NIGHT, "state": after_state}, _ALL])
    with pytest.raises(ValueError, match=f"still '{after_state}'"):
        await facade.arm(_NIGHT_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("after_state", ["arming", "disarming", "future-state"])
async def test_disarm_reread_must_be_explicitly_disarmed(after_state):
    facade = _facade([{**_NIGHT, "state": "armed"}, _ALL], after=[{**_NIGHT, "state": after_state}, _ALL])
    with pytest.raises(ValueError, match=f"still '{after_state}'"):
        await facade.disarm(_NIGHT_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["breached", "disarming", "future-state"])
async def test_arm_refuses_profile_in_non_disarmed_state(state):
    facade = _facade([{**_NIGHT, "state": state}, _ALL])
    with pytest.raises(ValueError, match="arm was not attempted"):
        await facade.arm(_NIGHT_ID)
    facade._service.arm_profile.assert_not_called()


@pytest.mark.asyncio
async def test_disarm_breached_profile_sends_the_action():
    facade = _facade([{**_NIGHT, "state": "breached"}, _ALL], after=[_NIGHT, _ALL])
    result = await facade.disarm(None)
    facade._service.disarm_profile.assert_awaited_once_with(_NIGHT_ID)
    assert result["profiles"][0]["state"] == "disarmed"


@pytest.mark.asyncio
async def test_ambiguous_profile_name_asks_for_the_id():
    twin = {**_ALL, "title": "arm night"}
    facade = _facade([_NIGHT, twin])
    with pytest.raises(ValueError, match="pass the profile id") as exc:
        await facade.arm("ARM NIGHT")
    assert _NIGHT_ID in str(exc.value) and _ALL_ID in str(exc.value)
    facade._service.arm_profile.assert_not_called()


# ---------------------------------------------------------------------------
# Blank profile ids are refused, never widened to the omitted-id target
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("blank", ["", "   ", "\t"])
@pytest.mark.parametrize("operation", ["arm", "disarm", "preview_arm", "preview_disarm"])
async def test_blank_profile_id_is_refused_before_any_backend_call(operation, blank):
    armed = {**_NIGHT, "state": "armed"}
    facade = _facade([armed, {**_ALL, "state": "armed"}])

    with pytest.raises(ValueError, match="must not be blank"):
        await getattr(facade, operation)(blank)

    facade._service.list_profiles.assert_not_called()
    facade._service.arm_profile.assert_not_called()
    facade._service.disarm_profile.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["arm", "disarm", "preview_arm", "preview_disarm"])
async def test_blank_profile_id_is_refused_on_legacy_consoles(operation):
    facade = _facade_with_real_mode_reader({})

    with pytest.raises(ValueError, match="must not be blank"):
        await getattr(facade, operation)("  ")

    getattr(facade._legacy, operation).assert_not_called()


@pytest.mark.asyncio
async def test_omitted_profile_id_still_disarms_every_active_profile():
    armed = [{**_NIGHT, "state": "armed"}, {**_ALL, "state": "armed"}]
    after = [{**_NIGHT, "state": "disarmed"}, {**_ALL, "state": "disarmed"}]
    facade = _facade(armed, after)

    result = await facade.disarm(None)

    assert result["armed"] is False
    assert {p["profile_id"] for p in result["profiles"]} == {_NIGHT_ID, _ALL_ID}
