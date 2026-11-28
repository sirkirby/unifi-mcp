"""UniFi Drive storage pools, their RAID groups, what their used space is used by, and the disks in the bays."""

from __future__ import annotations

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.scalars import BigInt
from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class DriveRaidGroup(Projection):
    number: int | None = strawberry.field(description="RAID group number within the pool")
    id: str | None = strawberry.field(description="RAID group id")
    current_level: str | None = strawberry.field(description="RAID level in effect now, such as raid1")
    config_level: str | None = strawberry.field(description="RAID level the pool is configured for, such as raid5")
    current_protection: int | None = strawberry.field(description="Disk failures the group survives now")
    expected_protection: int | None = strawberry.field(description="Disk failures it survives at its configured level")
    recommended_disk_size: BigInt | None = strawberry.field(description="Recommended size in bytes for an added disk")
    progress: float | None = strawberry.field(description="Rebuild or expansion progress, as reported by Drive")
    estimate: float | None = strawberry.field(
        description="Estimated time remaining for that work, as reported by Drive"
    )
    is_ssd_cache: bool | None = strawberry.field(description="Whether this group is an SSD cache")
    remnant_reason: str | None = strawberry.field(description="Why the group is a remnant, if it is one")


@strawberry.type(description=DESCRIPTION)
class DriveStoragePool(Projection):
    number: int | None = strawberry.field(description="Pool number")
    id: str | None = strawberry.field(description="Storage pool id; shared drives name it as storage_pool_id")
    status: str | None = strawberry.field(description="Pool status, such as healthy or noDataProtectionYet")
    prefer_level: str | None = strawberry.field(description="RAID level chosen for the pool")
    type: str | None = strawberry.field(description="Volume type, such as lvm")
    capacity_bytes: BigInt | None = strawberry.field(description="Usable capacity in bytes")
    used_bytes: BigInt | None = strawberry.field(description="Used space in bytes")
    used_percent: float | None = strawberry.field(description="Used space as a percentage of capacity")
    initializing_status: str | None = strawberry.field(description="Initialization status, such as successful")
    active_raid_group_id: str | None = strawberry.field(description="RAID group currently receiving writes")
    raid_groups: list[DriveRaidGroup] | None = strawberry.field(description="RAID groups in the pool")

    _nested = {"raid_groups": (DriveRaidGroup, True)}
    _identity = "id"
    _columns = ["number", "status", "prefer_level", "used_percent"]


@strawberry.type(description=DESCRIPTION)
class DriveDisk(Projection):
    slot_id: str | None = strawberry.field(description="Bay number as printed on the NAS")
    bay_type: str = strawberry.field(description="'disk' for a drive bay, 'cache' for an SSD cache slot")
    state: str | None = strawberry.field(description="Disk state, such as optimal, or 'empty' for an empty bay")
    pool_id: str | None = strawberry.field(description="Storage pool the disk belongs to")
    raid_group_id: str | None = strawberry.field(description="RAID group the disk belongs to")
    is_global_hot_spare: bool | None = strawberry.field(description="Whether the disk is a global hot spare")
    is_local_hot_spare: bool | None = strawberry.field(description="Whether the disk is a hot spare for its pool")
    type: str | None = strawberry.field(description="Disk type, such as HDD or SSD")
    model: str | None = strawberry.field(description="Disk model")
    serial: str | None = strawberry.field(description="Disk serial number")
    firmware: str | None = strawberry.field(description="Disk firmware")
    size_bytes: BigInt | None = strawberry.field(description="Raw disk size in bytes")
    rpm: int | None = strawberry.field(description="Spindle speed; absent for SSDs")
    interface: str | None = strawberry.field(description="SATA revision, such as SATA 3.3")
    ata_standard: str | None = strawberry.field(description="ATA command set, such as ACS-4")
    nvme_version: str | None = strawberry.field(description="NVMe version, for NVMe disks")
    sector_format: str | None = strawberry.field(description="Sector format, such as 512E")
    temperature_c: float | None = strawberry.field(description="Disk temperature in degrees Celsius")
    power_on_hours: BigInt | None = strawberry.field(description="SMART power-on hours")
    bad_sector_count: BigInt | None = strawberry.field(description="SMART bad (reallocated) sector count")
    uncorrectable_sector_count: BigInt | None = strawberry.field(description="SMART uncorrectable sector count")
    read_error_rate: BigInt | None = strawberry.field(description="SMART read error rate")
    smart_read_error_count: BigInt | None = strawberry.field(description="SMART read error count")
    risk_reasons: JSON | None = strawberry.field(description="Why Drive flags the disk as at risk, if it does")
    incompatible_reasons: JSON | None = strawberry.field(
        description="Why Drive considers the disk incompatible, if it does"
    )

    _columns = ["slot_id", "bay_type", "state", "model", "temperature_c"]


@strawberry.type(description=DESCRIPTION)
class DriveStoragePoolUsage(Projection):
    pool_id: str | None = strawberry.field(description="Storage pool id, the same id the storage pool list reports")
    capacity_bytes: BigInt | None = strawberry.field(description="Usable capacity in bytes")
    used_bytes: BigInt | None = strawberry.field(description="Used space in bytes")
    available_bytes: BigInt | None = strawberry.field(description="Free space in bytes")
    used_percent: float | None = strawberry.field(description="Used space as a percentage of capacity")
    personal_drives_bytes: BigInt | None = strawberry.field(description="Used by personal drives")
    shared_drives_bytes: BigInt | None = strawberry.field(description="Used by shared drives")
    snapshots_bytes: BigInt | None = strawberry.field(description="Used by snapshots, when Drive reports it")
    m365_bytes: BigInt | None = strawberry.field(description="Used by Microsoft 365 backups, when Drive reports it")
    system_bytes: BigInt | None = strawberry.field(
        description=(
            "Used by everything else (system and other data): used space minus the parts above, as the Drive UI "
            "shows it. Absent when the pool has iSCSI or deduplication data, which Drive counts differently."
        )
    )

    _identity = "pool_id"
    _columns = ["pool_id", "used_percent", "available_bytes", "shared_drives_bytes", "system_bytes"]
