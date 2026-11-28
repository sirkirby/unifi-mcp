"""User and group tools: response shape and error reporting. Fixtures are synthetic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from unifi_core.drive.models.users import drive_group_from_api, drive_user_from_api
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiPermissionError
from unifi_drive_mcp.tools import users

USER_ID = "55555555-5555-4555-8555-555555555555"
GROUP_ID = "88888888-8888-4888-8888-888888888888"


@pytest.fixture
def manager(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(users, "user_manager", fake)
    return fake


async def test_list_users(manager):
    manager.list_users.return_value = [
        drive_user_from_api(
            {
                "id": USER_ID,
                "username": "synthetic",
                "fullName": "Synthetic User",
                "email": "",
                "avatar": "https://192.0.2.10/avatar.png",
                "status": "active",
                "isOwner": False,
                "roles": [{"level": 2, "systemKey": "super_administrator"}],
            }
        )
    ]

    result = await users.drive_list_users()

    assert result == {
        "success": True,
        "data": {
            "users": [
                {
                    "id": USER_ID,
                    "username": "synthetic",
                    "full_name": "Synthetic User",
                    "status": "active",
                    "access_level": "admin",
                    "roles": ["super_administrator"],
                }
            ],
            "count": 1,
        },
    }


async def test_list_users_refused_by_the_nas_names_the_operation(manager):
    manager.list_users.side_effect = UniFiPermissionError("UniFi Drive refused GET /x (403).")

    result = await users.drive_list_users()

    assert result == {"success": False, "error": "Failed to list users: UniFi Drive refused GET /x (403)."}


async def test_list_groups(manager):
    manager.list_groups.return_value = [drive_group_from_api({"id": GROUP_ID, "name": "Family"})]

    result = await users.drive_list_groups()

    assert result == {"success": True, "data": {"groups": [{"id": GROUP_ID, "name": "Family"}], "count": 1}}


async def test_no_groups_is_an_empty_list(manager):
    manager.list_groups.return_value = []

    result = await users.drive_list_groups()

    assert result == {"success": True, "data": {"groups": [], "count": 0}}


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            UniFiMalformedResponseError("UniFi Drive returned an unreadable group list."),
            "Failed to list groups: UniFi Drive returned an unreadable group list.",
        ),
        (RuntimeError("https://192.0.2.10/detail"), "Failed to list groups: unexpected RuntimeError"),
    ],
)
async def test_list_groups_errors(manager, error, message):
    manager.list_groups.side_effect = error

    result = await users.drive_list_groups()

    assert result == {"success": False, "error": message}
