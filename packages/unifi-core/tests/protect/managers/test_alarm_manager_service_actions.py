"""Tests for AlarmManagerService profile arm/disarm actions (v2 Alarm Manager)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from uiprotect.exceptions import BadRequest, NotAuthorized, PublicOnlyModeError
from unifi_core.protect.managers.alarm_manager_service import AlarmManagerPermissionError, AlarmManagerService

_PROFILE_ID = "019e473a-0000-7000-8000-000000000002"
_PROFILE = {"id": _PROFILE_ID, "title": "Arm All", "state": "arming", "activation_delay": 60}


def _service(response=_PROFILE, error=None):
    cm = MagicMock()
    cm.client.api_request = AsyncMock(side_effect=error, return_value=response)
    return AlarmManagerService(cm), cm.client.api_request


@pytest.mark.asyncio
async def test_arm_profile_posts_v2_action():
    service, api_request = _service()
    result = await service.arm_profile(_PROFILE_ID)
    api_request.assert_awaited_once_with(
        f"profiles/{_PROFILE_ID}/actions/arm", method="post", api_path="/api/v2/alarms/"
    )
    assert result == _PROFILE


@pytest.mark.asyncio
async def test_disarm_profile_posts_v2_action():
    service, api_request = _service(response={**_PROFILE, "state": "disarmed"})
    result = await service.disarm_profile(_PROFILE_ID)
    api_request.assert_awaited_once_with(
        f"profiles/{_PROFILE_ID}/actions/disarm", method="post", api_path="/api/v2/alarms/"
    )
    assert result["state"] == "disarmed"


@pytest.mark.asyncio
async def test_profile_action_coerces_non_dict_response():
    service, _ = _service(response=None)
    assert await service.arm_profile(_PROFILE_ID) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("profile_id", ["", None])
async def test_profile_action_requires_profile_id(profile_id):
    service, api_request = _service()
    with pytest.raises(ValueError, match="profile_id is required"):
        await service.arm_profile(profile_id)
    api_request.assert_not_called()


@pytest.mark.asyncio
async def test_profile_action_maps_forbidden_to_permission_error():
    service, _ = _service(error=NotAuthorized("forbidden"))
    with pytest.raises(AlarmManagerPermissionError):
        await service.disarm_profile(_PROFILE_ID)


@pytest.mark.asyncio
async def test_profile_action_bad_request_surfaces_reason_without_url():
    error = BadRequest(
        f"Request failed: https://192.0.2.10/api/v2/alarms/profiles/{_PROFILE_ID}/actions/arm - Status: 400 - "
        "Reason: Cannot arm alarm profile with no alarms assigned"
    )
    service, _ = _service(error=error)
    with pytest.raises(ValueError) as exc:
        await service.arm_profile(_PROFILE_ID)
    message = str(exc.value)
    assert "Cannot arm alarm profile with no alarms assigned" in message
    assert "192.0.2.10" not in message and "https://" not in message
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
async def test_profile_action_keeps_a_reason_that_contains_the_delimiter():
    error = BadRequest(
        f"Request failed: https://192.0.2.10/api/v2/alarms/profiles/{_PROFILE_ID}/actions/arm - Status: 400 - "
        "Reason: Cannot arm - Reason: no alarms assigned"
    )
    service, _ = _service(error=error)
    with pytest.raises(ValueError, match="arm alarm profile .*: Cannot arm - Reason: no alarms assigned$"):
        await service.arm_profile(_PROFILE_ID)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [
        "Cannot arm profile on https://192.0.2.10:7443; no alarms assigned",
        "Console 192.0.2.10 refused the request",
        "Console [2001:db8::10] refused the request",
        "",
        "   ",
    ],
)
async def test_profile_action_drops_a_reason_with_an_address(reason):
    error = BadRequest(
        f"Request failed: https://192.0.2.10/api/v2/alarms/profiles/{_PROFILE_ID}/actions/arm - Status: 400 - "
        f"Reason: {reason}"
    )
    service, _ = _service(error=error)
    with pytest.raises(ValueError) as exc:
        await service.arm_profile(_PROFILE_ID)
    message = str(exc.value)
    assert message.endswith(": request rejected")
    assert "192.0.2.10" not in message and "2001:db8" not in message and "://" not in message


@pytest.mark.asyncio
async def test_profile_action_keeps_the_public_only_session_error():
    error = PublicOnlyModeError("Private authentication is unavailable on a public-only client")
    service, _ = _service(error=error)
    with pytest.raises(PublicOnlyModeError, match="public-only client"):
        await service.disarm_profile(_PROFILE_ID)
