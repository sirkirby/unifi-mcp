"""Storage pools, RAID groups and disk slots. Read-only: nothing here erases, creates or deletes."""

from __future__ import annotations

from dataclasses import dataclass

from unifi_core.drive.managers.connection_manager import DriveConnectionManager, drive_path
from unifi_core.drive.models._coerce import as_list
from unifi_core.drive.models.storage import (
    EMPTY_DISK_STATE,
    DiskSlot,
    StoragePool,
    disk_slot_from_api,
    storage_pool_from_api,
)
from unifi_core.exceptions import UniFiMalformedResponseError


@dataclass(frozen=True)
class StorageOverview:
    pools: list[StoragePool]
    disks: list[DiskSlot]


class StorageManager:
    """Reads ``GET /proxy/drive/api/v2/storage``."""

    def __init__(self, connection: DriveConnectionManager) -> None:
        self._connection = connection

    async def get_storage(self) -> StorageOverview:
        raw = await self._connection.get(drive_path(2, "storage"))
        if not isinstance(raw, dict):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable storage description.")
        pools = [storage_pool_from_api(pool) for pool in as_list(raw.get("pools")) if isinstance(pool, dict)]
        disks = [disk_slot_from_api(disk) for disk in as_list(raw.get("disks")) if isinstance(disk, dict)]
        disks += [
            disk_slot_from_api(disk, bay_type="cache")
            for disk in as_list(raw.get("cacheSlots"))
            if isinstance(disk, dict)
        ]
        return StorageOverview(pools=pools, disks=disks)

    async def list_pools(self) -> list[StoragePool]:
        return (await self.get_storage()).pools

    async def list_disks(self, *, include_empty: bool = False, include_cache: bool = True) -> list[DiskSlot]:
        disks = (await self.get_storage()).disks
        return [
            disk
            for disk in disks
            if (include_empty or disk.state != EMPTY_DISK_STATE) and (include_cache or disk.bay_type != "cache")
        ]
