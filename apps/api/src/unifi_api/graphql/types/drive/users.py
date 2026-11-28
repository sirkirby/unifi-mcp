"""UniFi Drive users and the user groups shared drive access can be granted to."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection

_USER_ID_SCOPE = "These IDs are scoped to UniFi Drive users; do not pass them as shared drive or group ids."
_GROUP_ID_SCOPE = "These IDs are scoped to UniFi Drive user groups; do not pass them as user or shared drive ids."


@strawberry.type(description=DESCRIPTION)
class DriveUser(Projection):
    id: str | None = strawberry.field(description=f"User id. {_USER_ID_SCOPE}")
    username: str | None = strawberry.field(description="Login name")
    full_name: str | None = strawberry.field(description="Display name")
    email: str | None = strawberry.field(description="Email address, when one is set")
    status: str | None = strawberry.field(description="Account status, such as active, deactivated or pending")
    access_level: str | None = strawberry.field(
        description=(
            "owner, admin or user, worked out as Drive's web app does: the console owner, any account "
            "with a role, or everyone else"
        )
    )
    roles: list[str] | None = strawberry.field(
        description="Console roles the account holds, such as super_administrator"
    )
    personal_drive_enabled: bool | None = strawberry.field(description="Whether the user's personal drive is on")
    must_change_password: bool | None = strawberry.field(
        description="Whether the user must change the password at next login"
    )
    linked_to_ad: bool | None = strawberry.field(description="Whether the account comes from Active Directory")
    has_ui_account: bool | None = strawberry.field(description="Whether the account has a UniFi SSO (UI.com) identity")
    created_at: str | None = strawberry.field(description="When the account was created")
    last_login: str | None = strawberry.field(description="Last login time; absent when the user never logged in")

    _identity = "id"
    _columns = ["username", "full_name", "status", "access_level", "last_login"]


@strawberry.type(description=DESCRIPTION)
class DriveGroup(Projection):
    id: str | None = strawberry.field(description=f"Group id. {_GROUP_ID_SCOPE}")
    name: str | None = strawberry.field(description="Group name")

    _identity = "id"
    _columns = ["name"]
