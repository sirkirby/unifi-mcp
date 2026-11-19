"""Storage pools, RAID groups and disk slots from ``GET /proxy/drive/api/v2/storage``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.drive.models._coerce import as_dict, as_list, flag, number, text

EMPTY_DISK_STATE = "empty"


class RaidGroup(BaseModel):
    """One RAID group inside a storage pool.

    ``current_level`` differs from ``config_level`` while the pool has fewer
    disks than its configured level needs, or while a migration between levels
    runs. ``progress`` and ``estimate`` are Drive's own rebuild/expansion figures.
    """

    model_config = ConfigDict(extra="ignore")

    number: int | None = Field(default=None, description="RAID group number within the pool")
    id: str | None = Field(default=None, description="RAID group id")
    current_level: str | None = Field(default=None, description="RAID level in effect now, such as raid1")
    config_level: str | None = Field(default=None, description="RAID level the pool is configured for, such as raid5")
    current_protection: int | None = Field(default=None, description="Disk failures the group survives now")
    expected_protection: int | None = Field(
        default=None, description="Disk failures it survives at its configured level"
    )
    recommended_disk_size: int | None = Field(default=None, description="Recommended size in bytes for an added disk")
    progress: float | None = Field(default=None, description="Rebuild or expansion progress, as reported by Drive")
    estimate: float | None = Field(
        default=None, description="Estimated time remaining for that work, as reported by Drive"
    )
    is_ssd_cache: bool | None = Field(default=None, description="Whether this group is an SSD cache")
    remnant_reason: str | None = Field(default=None, description="Why the group is a remnant, if it is one")


class StoragePool(BaseModel):
    """A storage pool and its RAID groups."""

    model_config = ConfigDict(extra="ignore")

    number: int | None = Field(default=None, description="Pool number")
    id: str | None = Field(default=None, description="Storage pool id; shared drives name it as storage_pool_id")
    status: str | None = Field(default=None, description="Pool status, such as healthy or noDataProtectionYet")
    prefer_level: str | None = Field(default=None, description="RAID level chosen for the pool")
    type: str | None = Field(default=None, description="Volume type, such as lvm")
    capacity_bytes: int | None = Field(default=None, description="Usable capacity in bytes")
    used_bytes: int | None = Field(default=None, description="Used space in bytes")
    used_percent: float | None = Field(default=None, description="Used space as a percentage of capacity")
    initializing_status: str | None = Field(default=None, description="Initialization status, such as successful")
    active_raid_group_id: str | None = Field(default=None, description="RAID group currently receiving writes")
    raid_groups: list[RaidGroup] = Field(default_factory=list, description="RAID groups in the pool")


class DiskSlot(BaseModel):
    """A drive bay (HDD) or cache slot (SSD) and the disk in it, with its SMART counters."""

    model_config = ConfigDict(extra="ignore")

    slot_id: str | None = Field(default=None, description="Bay number as printed on the NAS")
    bay_type: str = Field(description="'disk' for a drive bay, 'cache' for an SSD cache slot")
    state: str | None = Field(default=None, description="Disk state, such as optimal, or 'empty' for an empty bay")
    pool_id: str | None = Field(default=None, description="Storage pool the disk belongs to")
    raid_group_id: str | None = Field(default=None, description="RAID group the disk belongs to")
    is_global_hot_spare: bool | None = Field(default=None, description="Whether the disk is a global hot spare")
    is_local_hot_spare: bool | None = Field(default=None, description="Whether the disk is a hot spare for its pool")
    type: str | None = Field(default=None, description="Disk type, such as HDD or SSD")
    model: str | None = Field(default=None, description="Disk model")
    serial: str | None = Field(default=None, description="Disk serial number")
    firmware: str | None = Field(default=None, description="Disk firmware")
    size_bytes: int | None = Field(default=None, description="Raw disk size in bytes")
    rpm: int | None = Field(default=None, description="Spindle speed; absent for SSDs")
    interface: str | None = Field(default=None, description="SATA revision, such as SATA 3.3")
    ata_standard: str | None = Field(default=None, description="ATA command set, such as ACS-4")
    nvme_version: str | None = Field(default=None, description="NVMe version, for NVMe disks")
    sector_format: str | None = Field(default=None, description="Sector format, such as 512E")
    temperature_c: float | None = Field(default=None, description="Disk temperature in degrees Celsius")
    power_on_hours: int | None = Field(default=None, description="SMART power-on hours")
    bad_sector_count: int | None = Field(default=None, description="SMART bad (reallocated) sector count")
    uncorrectable_sector_count: int | None = Field(default=None, description="SMART uncorrectable sector count")
    read_error_rate: int | None = Field(default=None, description="SMART read error rate")
    smart_read_error_count: int | None = Field(default=None, description="SMART read error count")
    risk_reasons: list[Any] = Field(default_factory=list, description="Why Drive flags the disk as at risk, if it does")
    incompatible_reasons: list[Any] = Field(
        default_factory=list, description="Why Drive considers the disk incompatible, if it does"
    )


def _int(value: Any) -> int | None:
    found = number(value)
    return int(found) if found is not None else None


def raid_group_from_api(raw: Any) -> RaidGroup:
    group = as_dict(raw)
    return RaidGroup(
        number=_int(group.get("number")),
        id=text(group.get("id")),
        current_level=text(group.get("currentLevel")),
        config_level=text(group.get("configLevel")),
        current_protection=_int(group.get("currentProtection")),
        expected_protection=_int(group.get("expectedProtection")),
        recommended_disk_size=_int(group.get("recommendedDiskSize")),
        progress=number(group.get("progress")),
        estimate=number(group.get("estimate")),
        is_ssd_cache=flag(group.get("isSSDCache")),
        remnant_reason=text(group.get("remnantReason")),
    )


def storage_pool_from_api(raw: Any) -> StoragePool:
    pool = as_dict(raw)
    capacity = _int(pool.get("capacity"))
    used = _int(pool.get("usage"))
    used_percent = round(used * 100 / capacity, 2) if capacity and used is not None else None
    return StoragePool(
        number=_int(pool.get("number")),
        id=text(pool.get("id")),
        status=text(pool.get("status")),
        prefer_level=text(pool.get("preferLevel")),
        type=text(pool.get("type")),
        capacity_bytes=capacity,
        used_bytes=used,
        used_percent=used_percent,
        initializing_status=text(pool.get("initializingStatus")),
        active_raid_group_id=text(pool.get("activeRaidGroupId")),
        raid_groups=[
            raid_group_from_api(group) for group in as_list(pool.get("raidGroups")) if isinstance(group, dict)
        ],
    )


def disk_slot_from_api(raw: Any, *, bay_type: str = "disk") -> DiskSlot:
    disk = as_dict(raw)
    slot = disk.get("slotId")
    empty = disk.get("state") == EMPTY_DISK_STATE

    def present(value: Any) -> Any:
        # An empty bay reports zeros and empty strings for every field.
        return None if empty else value

    return DiskSlot(
        slot_id=str(slot) if isinstance(slot, (str, int)) and not isinstance(slot, bool) and str(slot) else None,
        bay_type=bay_type,
        state=text(disk.get("state")),
        pool_id=text(disk.get("poolId")),
        raid_group_id=text(disk.get("raidGroupId")),
        is_global_hot_spare=present(flag(disk.get("isGlobalHotSpare"))),
        is_local_hot_spare=present(flag(disk.get("isLocalHotSpare"))),
        type=text(disk.get("type")),
        model=text(disk.get("model")),
        serial=text(disk.get("serial")),
        firmware=text(disk.get("firmware")),
        size_bytes=present(_int(disk.get("size"))),
        rpm=_int(disk.get("rpm")) or None,
        interface=text(disk.get("sata")),
        ata_standard=text(disk.get("ata")),
        nvme_version=text(disk.get("nvmeVersion")),
        sector_format=text(disk.get("sectorFormat")),
        temperature_c=present(number(disk.get("temperature"))),
        power_on_hours=present(_int(disk.get("powerOnHours"))),
        bad_sector_count=present(_int(disk.get("badSectorCount"))),
        uncorrectable_sector_count=present(_int(disk.get("uncorrectableSectorCount"))),
        read_error_rate=present(_int(disk.get("readErrorRate"))),
        smart_read_error_count=present(_int(disk.get("smartReadErrorCount"))),
        risk_reasons=as_list(disk.get("riskReasons")),
        incompatible_reasons=as_list(disk.get("incompatibleReasons")),
    )
