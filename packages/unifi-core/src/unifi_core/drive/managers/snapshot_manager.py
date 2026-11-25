"""Snapshot settings and snapshots. Read-only: nothing here takes, locks, restores or deletes a snapshot."""

from __future__ import annotations

import re

from unifi_core.drive.managers.connection_manager import DriveConnectionManager, drive_path
from unifi_core.drive.managers.shared_drive_manager import SharedDriveManager
from unifi_core.drive.models.snapshots import Snapshot, SnapshotOverview, snapshot_from_api, snapshot_overview_from_api
from unifi_core.exceptions import (
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiValidationError,
)
from unifi_core.request_paths import InvalidRequestPathError, check_request_path

# Drive refuses a shared drive name that starts with a dot, has two dots in a
# row, or holds whitespace or any of `~!@#$%^&*()-=+[{]}\|;:'",<>/?. Of ASCII
# that leaves letters, digits, `_` and single dots, which keep the name one
# path segment. Anything else is refused before a request is sent.
_SHARED_DRIVE_NAME = re.compile(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*\.?")


def _snapshots_path(shared_drive_name: str) -> str:
    if not isinstance(shared_drive_name, str) or not _SHARED_DRIVE_NAME.fullmatch(shared_drive_name):
        raise UniFiValidationError("Invalid shared drive name")
    path = drive_path(1, "snapshots", "shared", shared_drive_name)
    try:
        check_request_path(path)
    except InvalidRequestPathError:
        raise UniFiValidationError("Invalid shared drive name") from None
    return path


class SnapshotManager:
    """Reads ``/proxy/drive/api/v1/systems/snapshot`` and ``/proxy/drive/api/v1/snapshots/shared/<name>``."""

    def __init__(self, connection: DriveConnectionManager, shared_drives: SharedDriveManager) -> None:
        self._connection = connection
        self._shared_drives = shared_drives

    async def get_snapshot_overview(self) -> SnapshotOverview:
        raw = await self._connection.get(drive_path(1, "systems", "snapshot"))
        if not isinstance(raw, dict) or not isinstance(raw.get("shared"), list):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable snapshot overview.")
        return snapshot_overview_from_api(raw)

    async def list_snapshots(self, shared_drive_name: str) -> list[Snapshot]:
        """One shared drive's snapshots, in Drive's order, by the drive's name."""
        path = _snapshots_path(shared_drive_name)
        try:
            raw = await self._connection.get(path)
        except UniFiPermissionError:
            # Drive answers 403, not 404, for a name no shared drive has.
            names = {drive.name for drive in await self._shared_drives.list_shared_drives()}
            if shared_drive_name not in names:
                raise UniFiNotFoundError("Shared drive", shared_drive_name) from None
            raise
        if not isinstance(raw, list):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable snapshot list.")
        return [snapshot_from_api(entry) for entry in raw if isinstance(entry, dict)]
