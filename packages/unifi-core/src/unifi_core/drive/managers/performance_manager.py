"""Live network throughput, fan profile and per-disk activity history. Read-only: nothing here sets the fan."""

from __future__ import annotations

import time

from unifi_core.drive.managers.connection_manager import DriveConnectionManager, drive_path
from unifi_core.drive.models._coerce import as_dict, number
from unifi_core.drive.models.performance import (
    DiskStats,
    FanProfile,
    NetworkThroughput,
    disk_stats_from_api,
    fan_profile_from_api,
    network_throughput_from_api,
)
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiValidationError

#: Longest window ``get_disk_stats`` reads, in hours (90 days).
MAX_DISK_STATS_HOURS = 2160

_HOUR = 3600
_DAY = 24 * _HOUR


def disk_stats_interval(hours: int) -> int:
    """Bucket length in seconds for a window of ``hours``, by the steps the Drive dashboard uses.

    15 minutes under 7 days, 1 hour under 30 days, 6 hours from 30 days. Each
    stays below the roughly thousand buckets Drive serves in one answer.
    """
    span = hours * _HOUR
    if span >= 30 * _DAY:
        return 6 * _HOUR
    if span >= 7 * _DAY:
        return _HOUR
    return 15 * 60


class PerformanceManager:
    """Reads ``/proxy/drive/api/v2/systems/{network-io,fan-control,disk-stats}``."""

    def __init__(self, connection: DriveConnectionManager) -> None:
        self._connection = connection

    async def get_network_throughput(self) -> NetworkThroughput:
        raw = await self._connection.get(drive_path(2, "systems", "network-io"))
        if not isinstance(raw, dict):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable network throughput.")
        return network_throughput_from_api(raw)

    async def get_fan_profile(self) -> FanProfile:
        raw = await self._connection.get(drive_path(2, "systems", "fan-control"))
        if not isinstance(raw, dict):
            raise UniFiMalformedResponseError("UniFi Drive returned an unreadable fan profile.")
        return fan_profile_from_api(raw)

    async def get_disk_stats(self, *, hours: int = 24) -> DiskStats:
        """Per-disk temperature, throughput and bad sectors over the last ``hours`` hours."""
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= MAX_DISK_STATS_HOURS:
            raise UniFiValidationError(f"hours must be a whole number from 1 to {MAX_DISK_STATS_HOURS}.")
        interval = disk_stats_interval(hours)
        end = int(time.time())
        start = end - hours * _HOUR
        path = drive_path(2, "systems", "disk-stats") + f"?start={start}&end={end}&interval={interval}"
        raw = await self._connection.get(path)
        window = as_dict(raw.get("window")) if isinstance(raw, dict) else {}
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("series"), dict)
            or not isinstance(raw["series"].get("disks"), list)
            or number(window.get("start")) is None
            or not number(window.get("interval"))
        ):
            raise UniFiMalformedResponseError("UniFi Drive returned unreadable disk statistics.")
        return disk_stats_from_api(raw)
