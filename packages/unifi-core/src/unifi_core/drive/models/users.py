"""Drive users and user groups.

Users come from ``GET /proxy/drive/api/v1/users?type=detail``, groups from
``GET /proxy/drive/api/v2/groups``.

The plain ``/users`` list carries names only; ``type=detail`` adds the status,
roles and owner flag that Drive's user management page reads. Avatar URLs, SSO
identifiers and employee numbers are dropped.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.drive.models._coerce import as_dict, as_list, flag, text

_USER_ID_SCOPE = "These IDs are scoped to UniFi Drive users; do not pass them as shared drive or group ids."
_GROUP_ID_SCOPE = "These IDs are scoped to UniFi Drive user groups; do not pass them as user or shared drive ids."
# Drive writes a never-used login time as the Unix epoch.
_NEVER = "1970-"


class DriveUser(BaseModel):
    """A UniFi OS user as UniFi Drive sees it."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description=f"User id. {_USER_ID_SCOPE}")
    username: str | None = Field(default=None, description="Login name")
    full_name: str | None = Field(default=None, description="Display name")
    email: str | None = Field(default=None, description="Email address, when one is set")
    status: str | None = Field(default=None, description="Account status, such as active, deactivated or pending")
    access_level: str | None = Field(
        default=None,
        description=(
            "owner, admin or user, worked out as Drive's web app does: the console owner, any account "
            "with a role, or everyone else"
        ),
    )
    roles: list[str] = Field(
        default_factory=list, description="Console roles the account holds, such as super_administrator"
    )
    personal_drive_enabled: bool | None = Field(default=None, description="Whether the user's personal drive is on")
    must_change_password: bool | None = Field(
        default=None, description="Whether the user must change the password at next login"
    )
    linked_to_ad: bool | None = Field(default=None, description="Whether the account comes from Active Directory")
    has_ui_account: bool | None = Field(
        default=None, description="Whether the account has a UniFi SSO (UI.com) identity"
    )
    created_at: str | None = Field(default=None, description="When the account was created")
    last_login: str | None = Field(default=None, description="Last login time; absent when the user never logged in")


class DriveGroup(BaseModel):
    """A UniFi OS user group that shared drive access can be granted to."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description=f"Group id. {_GROUP_ID_SCOPE}")
    name: str | None = Field(default=None, description="Group name")


def _access_level(user: dict[str, Any], roles: list[str]) -> str | None:
    owner = flag(user.get("isOwner"))
    if owner:
        return "owner"
    if owner is None and "roles" not in user:
        return None
    # Any role makes the account an admin, as in the Drive web app, including a role
    # without a system key (a custom UniFi OS role).
    return "admin" if roles or as_list(user.get("roles")) else "user"


def drive_user_from_api(raw: Any) -> DriveUser:
    user = as_dict(raw)
    roles = [key for key in (text(as_dict(role).get("systemKey")) for role in as_list(user.get("roles"))) if key]
    profile = user.get("appliedStorageProfile")
    last_login = text(user.get("lastLogin"))
    return DriveUser(
        id=text(user.get("id")),
        username=text(user.get("username")),
        full_name=text(user.get("fullName")),
        email=text(user.get("email")),
        status=text(user.get("status")),
        access_level=_access_level(user, roles),
        roles=roles,
        personal_drive_enabled=flag(profile.get("enable")) if isinstance(profile, dict) else None,
        must_change_password=flag(user.get("mustChangePassword")),
        linked_to_ad=flag(user.get("linkedToAD")),
        has_ui_account=flag(user.get("hasUniFiSsoId")),
        created_at=text(user.get("createdAt")),
        last_login=None if last_login is None or last_login.startswith(_NEVER) else last_login,
    )


def drive_group_from_api(raw: Any) -> DriveGroup:
    group = as_dict(raw)
    return DriveGroup(id=text(group.get("id")), name=text(group.get("name")))
