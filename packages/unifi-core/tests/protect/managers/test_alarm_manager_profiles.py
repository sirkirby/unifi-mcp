"""Tests for legacy Protect alarm profile selection."""

from unittest.mock import AsyncMock, MagicMock, call

import pytest
from uiprotect.exceptions import BadRequest
from unifi_core.protect.managers.alarm_manager import AlarmManager

_PROFILES_RESPONSE = [
    {
        "id": "p-night",
        "name": "Arm Night",
        "recordEverything": False,
        "activationDelay": 60000,
        "schedules": [],
        "automations": ["a1", "a2"],
    }
]


def _nvr_response(*, status: str = "disabled", profile_id: str | None = None) -> dict:
    return {
        "mac": "AABBCCDDEEFF",
        "name": "UNVR",
        "armMode": {
            "status": status,
            "armProfileId": profile_id,
            "armedAt": None,
            "willBeArmedAt": None,
            "breachDetectedAt": None,
            "breachEventCount": 0,
            "breachTriggerEventId": None,
            "breachEventId": None,
        },
    }


def _make_cm(responses: list[object]) -> MagicMock:
    cm = MagicMock()
    cm.client.api_request = AsyncMock(side_effect=responses)
    return cm


class TestLegacyProfileSelection:
    @pytest.mark.asyncio
    async def test_arm_translates_legacy_arm_profile_not_found(self) -> None:
        profile_id = "01a06cca-1111-4222-8333-444444444444"
        missing_profile = {
            "error": "Entity 'armProfile' not found",
            "name": "NOT_FOUND",
            "entity": "armProfile",
            "id": profile_id,
            "idKey": "id",
        }
        cm = _make_cm(
            [
                _nvr_response(),
                _PROFILES_RESPONSE,
                BadRequest(missing_profile),
            ]
        )
        manager = AlarmManager(cm)

        with pytest.raises(ValueError, match="did not recognize this profile_id"):
            await manager.arm(profile_id)

        mutating_calls = [
            item for item in cm.client.api_request.await_args_list if item.kwargs.get("method") in ("patch", "post")
        ]
        assert mutating_calls == [call("arm", method="patch", json={"armProfileId": profile_id})]

    @pytest.mark.asyncio
    async def test_arm_uuid_shaped_profile_id_reaches_legacy_endpoint_when_accepted(
        self,
    ) -> None:
        profile_id = "01a06cca-1111-4222-8333-444444444444"
        cm = _make_cm(
            [
                _nvr_response(),
                _PROFILES_RESPONSE,
                None,
                None,
            ]
        )
        manager = AlarmManager(cm)

        result = await manager.arm(profile_id)

        assert result == {
            "armed": True,
            "profile_id": profile_id,
            "profile_name": None,
        }
        mutating_calls = [
            item for item in cm.client.api_request.await_args_list if item.kwargs.get("method") in ("patch", "post")
        ]
        assert mutating_calls == [
            call("arm", method="patch", json={"armProfileId": profile_id}),
            call("arm/enable", method="post"),
        ]

    @pytest.mark.asyncio
    async def test_preview_arm_accepts_unknown_profile_id_shape(self) -> None:
        profile_id = "01a06cca-1111-4222-8333-444444444444"
        cm = _make_cm(
            [
                _nvr_response(),
                _PROFILES_RESPONSE,
            ]
        )
        manager = AlarmManager(cm)

        preview = await manager.preview_arm(profile_id)

        assert preview["target_profile_id"] == profile_id
        assert preview["target_profile_name"] is None
