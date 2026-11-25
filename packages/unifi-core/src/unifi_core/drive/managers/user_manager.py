"""Drive users and user groups. Read-only: nothing here invites, changes or removes a user or group."""

from __future__ import annotations

from unifi_core.drive.managers.connection_manager import DriveConnectionManager, drive_path
from unifi_core.drive.models.users import DriveGroup, DriveUser, drive_group_from_api, drive_user_from_api
from unifi_core.exceptions import UniFiMalformedResponseError


class DriveUserManager:
    """Reads ``/proxy/drive/api/v1/users?type=detail`` and ``/proxy/drive/api/v2/groups``."""

    def __init__(self, connection: DriveConnectionManager) -> None:
        self._connection = connection

    async def list_users(self) -> list[DriveUser]:
        """Every user. Without an offset and limit Drive returns the whole list, as its web app asks for it."""
        raw = await self._connection.get(drive_path(1, "users") + "?type=detail")
        if not isinstance(raw, list):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable user list.")
        return [drive_user_from_api(user) for user in raw if isinstance(user, dict)]

    async def list_groups(self) -> list[DriveGroup]:
        raw = await self._connection.get(drive_path(2, "groups"))
        if not isinstance(raw, dict) or not isinstance(raw.get("groups"), list):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable group list.")
        return [drive_group_from_api(group) for group in raw["groups"] if isinstance(group, dict)]
