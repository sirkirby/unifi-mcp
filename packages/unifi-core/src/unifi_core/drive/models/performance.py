"""Live throughput, fan profile and per-disk activity history of a UniFi Drive NAS.

Read from ``/proxy/drive/api/v2/systems/...``:

* ``network-io`` -- ``{"receiveKBPS": float, "transmitKBPS": float, "timestamp": str}``,
  the NAS's network throughput right now, in KB/s.
* ``fan-control`` -- ``{"availableProfiles": [str], "currentProfile": str}``. The
  web app labels the profile ``default`` as Balanced.
* ``disk-stats?start=&end=&interval=`` -- one series per disk of temperature,
  read and write throughput (KB/s) and bad sector count. ``start`` and ``end``
  are Unix seconds and ``interval`` a bucket length in seconds; Drive aligns the
  window to the interval and answers ``window.start``, ``window.interval`` and
  one value per bucket, ``null`` where it has no data. It refuses more than about
  a thousand buckets ("too many sample points").
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.drive.models._coerce import as_dict, as_list, number, strings, text

#: Fan profile names as Drive reports them, with the labels the Drive web app shows.
FAN_PROFILE_LABELS: dict[str, str] = {"cooling": "Cooling", "default": "Balanced", "quiet": "Quiet"}


class NetworkThroughput(BaseModel):
    """The NAS's network throughput at the moment Drive sampled it."""

    model_config = ConfigDict(extra="ignore")

    receive_kbps: float | None = Field(default=None, description="Data the NAS is receiving, in KB/s")
    transmit_kbps: float | None = Field(default=None, description="Data the NAS is sending, in KB/s")
    timestamp: str | None = Field(
        default=None, description="When Drive took the sample, ISO 8601 with the console's UTC offset"
    )


class FanProfileOption(BaseModel):
    """A fan profile the NAS offers."""

    model_config = ConfigDict(extra="ignore")

    profile: str = Field(description="Profile name as Drive reports it, such as default")
    label: str | None = Field(
        default=None,
        description=(
            "Name the Drive web app shows: Cooling (maximum cooling, more noise), Balanced (even cooling and "
            "noise) or Quiet (minimum noise, higher drive temperatures)"
        ),
    )


class FanProfile(BaseModel):
    """The fan mode in effect. Fan control targets a disk temperature range; the profile sets how hard it works."""

    model_config = ConfigDict(extra="ignore")

    current_profile: str | None = Field(default=None, description="Profile in effect, as Drive reports it")
    current_label: str | None = Field(default=None, description="Web app name of that profile, such as Balanced")
    available_profiles: list[FanProfileOption] = Field(default_factory=list, description="Profiles the NAS offers")


class DiskStatsSample(BaseModel):
    """One time bucket of a disk's activity. Values are rounded to two decimals, as the dashboard shows them."""

    model_config = ConfigDict(extra="ignore")

    time: str | None = Field(default=None, description="Start of the bucket, ISO 8601 in UTC")
    temperature_c: float | None = Field(default=None, description="Disk temperature in degrees Celsius")
    read_kbps: float | None = Field(default=None, description="Average read throughput over the bucket, in KB/s")
    write_kbps: float | None = Field(default=None, description="Average write throughput over the bucket, in KB/s")
    bad_sector_count: int | None = Field(default=None, description="SMART bad sector count")


class DiskActivity(BaseModel):
    """One disk's activity over the window, summarized, with the samples it was summarized from."""

    model_config = ConfigDict(extra="ignore")

    slot_id: str | None = Field(default=None, description="Bay or cache slot number, as drive_list_disks reports it")
    bay_type: str = Field(description="'disk' for a drive bay, 'cache' for an SSD cache slot")
    type: str | None = Field(default=None, description="Disk type, such as HDD or SSD")
    samples_with_data: int = Field(description="Buckets in the window for which Drive has data for this disk")
    read_kbps_avg: float | None = Field(default=None, description="Mean read throughput over those buckets, KB/s")
    read_kbps_max: float | None = Field(default=None, description="Highest bucket read throughput, KB/s")
    write_kbps_avg: float | None = Field(default=None, description="Mean write throughput over those buckets, KB/s")
    write_kbps_max: float | None = Field(default=None, description="Highest bucket write throughput, KB/s")
    temperature_c_latest: float | None = Field(default=None, description="Most recent temperature, degrees Celsius")
    temperature_c_max: float | None = Field(default=None, description="Highest temperature in the window")
    bad_sector_count_latest: int | None = Field(default=None, description="Most recent SMART bad sector count")
    bad_sector_count_increase: int | None = Field(
        default=None, description="How much the bad sector count rose between the first and last bucket with data"
    )
    samples: list[DiskStatsSample] = Field(default_factory=list, description="Per-bucket values, oldest first")


class DiskStats(BaseModel):
    """Per-disk temperature, throughput and bad sectors over a time window."""

    model_config = ConfigDict(extra="ignore")

    window_start: str | None = Field(default=None, description="Start of the first bucket, ISO 8601 in UTC")
    window_end: str | None = Field(default=None, description="End of the last bucket, ISO 8601 in UTC")
    interval_seconds: int | None = Field(default=None, description="Length of each bucket in seconds")
    sample_count: int | None = Field(default=None, description="Buckets in the window")
    disks: list[DiskActivity] = Field(default_factory=list, description="One entry per disk and cache SSD")


def network_throughput_from_api(raw: Any) -> NetworkThroughput:
    body = as_dict(raw)
    return NetworkThroughput(
        receive_kbps=_rounded(body.get("receiveKBPS")),
        transmit_kbps=_rounded(body.get("transmitKBPS")),
        timestamp=text(body.get("timestamp")),
    )


def fan_profile_from_api(raw: Any) -> FanProfile:
    body = as_dict(raw)
    current = text(body.get("currentProfile"))
    return FanProfile(
        current_profile=current,
        current_label=FAN_PROFILE_LABELS.get(current) if current else None,
        available_profiles=[
            FanProfileOption(profile=name, label=FAN_PROFILE_LABELS.get(name))
            for name in strings(body.get("availableProfiles"))
        ],
    )


def _iso(seconds: int | float | None) -> str | None:
    if seconds is None:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _int(value: Any) -> int | None:
    found = number(value)
    return int(found) if found is not None else None


def _rounded(value: Any) -> int | float | None:
    """A number rounded to two decimals, as the Drive dashboard shows it, or ``None``."""
    found = number(value)
    return round(found, 2) if found is not None else None


def _present(values: list[Any]) -> list[int | float]:
    return [value for value in (_rounded(item) for item in values) if value is not None]


def _avg(values: list[int | float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _max(values: list[int | float]) -> float | None:
    return max(values) if values else None


def _disk_activity(raw: Any, *, bay_type: str, start: int | float | None, interval: int | None) -> DiskActivity:
    disk = as_dict(raw)
    temperatures = as_list(disk.get("temperatures"))
    reads = as_list(disk.get("readKBPS"))
    writes = as_list(disk.get("writeKBPS"))
    bad_sectors = as_list(disk.get("badSectorCount"))
    count = max(len(temperatures), len(reads), len(writes), len(bad_sectors))

    def at(series: list[Any], index: int) -> Any:
        return series[index] if index < len(series) else None

    samples: list[DiskStatsSample] = []
    with_data = 0
    for index in range(count):
        values = (at(temperatures, index), at(reads, index), at(writes, index), at(bad_sectors, index))
        if any(number(value) is not None for value in values):
            with_data += 1
        bucket = start + index * interval if start is not None and interval else None
        samples.append(
            DiskStatsSample(
                time=_iso(bucket),
                temperature_c=_rounded(values[0]),
                read_kbps=_rounded(values[1]),
                write_kbps=_rounded(values[2]),
                bad_sector_count=_int(values[3]),
            )
        )

    present_reads = _present(reads)
    present_writes = _present(writes)
    present_temps = _present(temperatures)
    present_bad = [int(value) for value in _present(bad_sectors)]
    slot = disk.get("slotId")
    return DiskActivity(
        slot_id=str(slot) if isinstance(slot, (str, int)) and not isinstance(slot, bool) and str(slot) else None,
        bay_type=bay_type,
        type=text(disk.get("type")),
        samples_with_data=with_data,
        read_kbps_avg=_avg(present_reads),
        read_kbps_max=_max(present_reads),
        write_kbps_avg=_avg(present_writes),
        write_kbps_max=_max(present_writes),
        temperature_c_latest=present_temps[-1] if present_temps else None,
        temperature_c_max=_max(present_temps),
        bad_sector_count_latest=present_bad[-1] if present_bad else None,
        bad_sector_count_increase=present_bad[-1] - present_bad[0] if present_bad else None,
        samples=samples,
    )


def disk_stats_from_api(raw: Any) -> DiskStats:
    """Build :class:`DiskStats` from a ``GET .../systems/disk-stats`` body."""
    body = as_dict(raw)
    series = as_dict(body.get("series"))
    window = as_dict(body.get("window"))
    start = number(window.get("start"))
    interval = _int(window.get("interval"))
    end = number(window.get("end"))
    disks = [
        _disk_activity(disk, bay_type="disk", start=start, interval=interval)
        for disk in as_list(series.get("disks"))
        if isinstance(disk, dict)
    ]
    disks += [
        _disk_activity(disk, bay_type="cache", start=start, interval=interval)
        for disk in as_list(series.get("cacheSlots"))
        if isinstance(disk, dict)
    ]
    return DiskStats(
        window_start=_iso(start),
        window_end=_iso(end),
        interval_seconds=interval,
        sample_count=_int(window.get("samples")),
        disks=disks,
    )
