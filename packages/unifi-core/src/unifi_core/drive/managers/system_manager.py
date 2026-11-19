"""The NAS console's identity and health."""

from __future__ import annotations

from unifi_core.drive.managers.connection_manager import DriveConnectionManager
from unifi_core.drive.models.system import DriveSystemInfo, system_info_from_api
from unifi_core.exceptions import UniFiMalformedResponseError


class DriveSystemManager:
    """Reads ``/api/system`` from the UniFi Drive console."""

    def __init__(self, connection: DriveConnectionManager) -> None:
        self._connection = connection

    async def get_system_info(self) -> DriveSystemInfo:
        raw = await self._connection.get("/api/system")
        if not isinstance(raw, dict):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable system description.")
        return system_info_from_api(raw)
