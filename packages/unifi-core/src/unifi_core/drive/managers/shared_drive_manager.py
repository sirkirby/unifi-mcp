"""Shared drives. Read-only: nothing here creates, changes or deletes a drive."""

from __future__ import annotations

from unifi_core.drive.managers.connection_manager import DriveConnectionManager, drive_path
from unifi_core.drive.models._coerce import as_list
from unifi_core.drive.models.drives import SharedDrive, shared_drive_from_api
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiValidationError
from unifi_core.request_paths import InvalidRequestPathError, object_id


class SharedDriveManager:
    """Reads ``/proxy/drive/api/v2/drives``."""

    def __init__(self, connection: DriveConnectionManager) -> None:
        self._connection = connection

    async def list_shared_drives(self) -> list[SharedDrive]:
        raw = await self._connection.get(drive_path(2, "drives"))
        if not isinstance(raw, dict) or not isinstance(raw.get("drives"), list):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable shared drive list.")
        return [shared_drive_from_api(drive) for drive in as_list(raw.get("drives")) if isinstance(drive, dict)]

    async def get_shared_drive(self, drive_id: str) -> SharedDrive:
        """One shared drive. The single-drive endpoint omits protections and member count."""
        try:
            segment = object_id(drive_id, "shared drive")
        except InvalidRequestPathError as exc:
            raise UniFiValidationError(str(exc)) from None
        raw = await self._connection.get(drive_path(2, "drives", segment), resource=("Shared drive", segment))
        if not isinstance(raw, dict):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable shared drive.")
        return shared_drive_from_api(raw)
