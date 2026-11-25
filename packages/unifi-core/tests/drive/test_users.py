"""Drive users and user groups.

The user entries keep the shape captured from a UNAS Pro 8 (UniFi OS 6.0.18,
Drive 4.4.31) with synthetic ids, names and addresses. That NAS had no user
groups, so the group entries are synthetic, modelled on the fields Drive's web
UI reads.
"""

import pytest
from unifi_core.drive.managers.user_manager import DriveUserManager
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiPermissionError

USERS = "/proxy/drive/api/v1/users"
GROUPS = "/proxy/drive/api/v2/groups"
OWNER_ID = "55555555-5555-4555-8555-555555555555"
ADMIN_ID = "66666666-6666-4666-8666-666666666666"
MEMBER_ID = "77777777-7777-4777-8777-777777777777"
GROUP_ID = "88888888-8888-4888-8888-888888888888"
PROFILE_ID = "99999999-9999-4999-8999-999999999999"


def _user(user_id, username, *, owner=False, roles=(), status="active", last_login="2026-01-02T03:04:05+00:00"):
    return {
        "appliedStorageProfile": {
            "enable": False,
            "id": PROFILE_ID,
            "name": "Default",
            "quota": 0,
            "storagePoolId": "",
        },
        "avatar": "https://192.0.2.10/avatar/synthetic.png",
        "createdAt": "2026-01-01T00:00:00+00:00",
        "email": "",
        "emailStatus": "unverified",
        "employeeNumber": "E-0001",
        "firstName": "Synthetic",
        "fullName": f"Synthetic {username}",
        "groupIds": ["role-group-1"],
        "hasUniFiSsoId": False,
        "id": user_id,
        "isInSyncWithSambaAccount": True,
        "isOwner": owner,
        "lastLogin": last_login,
        "lastName": username,
        "linkedToAD": False,
        "mustChangePassword": False,
        "onboardTime": 0,
        "quickStart": False,
        "roles": [{"level": level, "systemKey": key} for level, key in roles],
        "sharedDrives": None,
        "ssoId": "sso-synthetic",
        "status": status,
        "uidSsoId": "uid-sso-synthetic",
        "usage": 0,
        "username": username,
    }


def _v1(data):
    return {"err": None, "type": "single", "data": data, "offset": 0, "limit": 0, "total": len(data)}


@pytest.fixture
def users(connection):
    return DriveUserManager(connection)


async def test_users_carry_status_and_access_level(users, console):
    console.reply(
        "GET",
        USERS,
        _v1(
            [
                _user(OWNER_ID, "owner", owner=True, roles=[(1, "owner")]),
                _user(ADMIN_ID, "admin", roles=[(2, "super_administrator")]),
                _user(MEMBER_ID, "member", status="deactivated", last_login="1970-01-01T00:00:00Z"),
            ]
        ),
    )

    owner, admin, member = await users.list_users()

    assert (owner.id, owner.username, owner.full_name) == (OWNER_ID, "owner", "Synthetic owner")
    assert (owner.access_level, owner.roles, owner.status) == ("owner", ["owner"], "active")
    assert (admin.access_level, admin.roles) == ("admin", ["super_administrator"])
    assert (member.access_level, member.roles, member.status) == ("user", [], "deactivated")
    assert owner.email is None and owner.personal_drive_enabled is False and owner.must_change_password is False
    assert owner.last_login == "2026-01-02T03:04:05+00:00" and owner.created_at == "2026-01-01T00:00:00+00:00"
    # Drive writes the epoch for a user who never logged in.
    assert member.last_login is None


async def test_users_are_read_with_detail(users, connection, console, monkeypatch):
    # The plain list has names only; type=detail adds status, roles and the owner flag.
    console.reply("GET", USERS, _v1([]))
    sent = []
    get = connection.get

    async def spy(path, **kwargs):
        sent.append(path)
        return await get(path, **kwargs)

    monkeypatch.setattr(connection, "get", spy)

    assert await users.list_users() == []
    assert sent == [f"{USERS}?type=detail"] and console.writes == []


async def test_avatar_sso_and_employee_fields_are_dropped(users, console):
    console.reply("GET", USERS, _v1([_user(OWNER_ID, "owner", owner=True)]))

    (user,) = await users.list_users()

    dumped = str(user.model_dump())
    for value in ("avatar", "192.0.2.10", "sso-synthetic", "uid-sso-synthetic", "E-0001", PROFILE_ID, "role-group-1"):
        assert value not in dumped


async def test_a_user_without_role_fields_has_no_access_level(users, console):
    console.reply("GET", USERS, _v1([{"id": MEMBER_ID, "username": "brief"}]))

    (user,) = await users.list_users()

    assert user.access_level is None and user.roles == []


async def test_a_user_list_that_is_not_a_list_is_malformed(users, console):
    console.reply("GET", USERS, _v1({"users": []}))

    with pytest.raises(UniFiMalformedResponseError):
        await users.list_users()


async def test_a_refused_user_list_is_a_permission_error(users, console):
    console.reply("GET", USERS, {"err": {"msg": "Forbidden"}}, status=403)

    with pytest.raises(UniFiPermissionError):
        await users.list_users()


async def test_groups(users, console):
    console.reply("GET", GROUPS, {"groups": [{"id": GROUP_ID, "name": "Family", "unknownField": 1}]})

    (group,) = await users.list_groups()

    assert group.model_dump() == {"id": GROUP_ID, "name": "Family"}


async def test_no_groups_is_an_empty_list(users, console):
    console.reply("GET", GROUPS, {"groups": []})

    assert await users.list_groups() == []


@pytest.mark.parametrize("body", [[], {"data": []}, {"groups": None}])
async def test_a_group_list_without_groups_is_malformed(users, console, body):
    console.reply("GET", GROUPS, body)

    with pytest.raises(UniFiMalformedResponseError):
        await users.list_groups()
