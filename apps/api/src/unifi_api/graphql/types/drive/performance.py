"""UniFi Drive NAS throughput, fan profile and per-disk activity history."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.scalars import BigInt
from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class DriveNetworkThroughput(Projection):
    receive_kbps: float | None = strawberry.field(description="Data the NAS is receiving, in KB/s")
    transmit_kbps: float | None = strawberry.field(description="Data the NAS is sending, in KB/s")
    timestamp: str | None = strawberry.field(
        description="When Drive took the sample, ISO 8601 with the console's UTC offset"
    )

    _columns = ["receive_kbps", "transmit_kbps", "timestamp"]


@strawberry.type(description=DESCRIPTION)
class DriveFanProfileOption(Projection):
    profile: str = strawberry.field(description="Profile name as Drive reports it, such as default")
    label: str | None = strawberry.field(
        description=(
            "Name the Drive web app shows: Cooling (maximum cooling, more noise), Balanced (even cooling and "
            "noise) or Quiet (minimum noise, higher drive temperatures)"
        )
    )


@strawberry.type(description=DESCRIPTION)
class DriveFanProfile(Projection):
    current_profile: str | None = strawberry.field(description="Profile in effect, as Drive reports it")
    current_label: str | None = strawberry.field(description="Web app name of that profile, such as Balanced")
    available_profiles: list[DriveFanProfileOption] | None = strawberry.field(description="Profiles the NAS offers")

    _nested = {"available_profiles": (DriveFanProfileOption, True)}
    _columns = ["current_profile", "current_label"]


@strawberry.type(description=DESCRIPTION)
class DriveDiskStatsSample(Projection):
    time: str | None = strawberry.field(description="Start of the bucket, ISO 8601 in UTC")
    temperature_c: float | None = strawberry.field(description="Disk temperature in degrees Celsius")
    read_kbps: float | None = strawberry.field(description="Average read throughput over the bucket, in KB/s")
    write_kbps: float | None = strawberry.field(description="Average write throughput over the bucket, in KB/s")
    bad_sector_count: BigInt | None = strawberry.field(description="SMART bad sector count")


@strawberry.type(description=DESCRIPTION)
class DriveDiskActivity(Projection):
    slot_id: str | None = strawberry.field(description="Bay or cache slot number, as drive_list_disks reports it")
    bay_type: str = strawberry.field(description="'disk' for a drive bay, 'cache' for an SSD cache slot")
    type: str | None = strawberry.field(description="Disk type, such as HDD or SSD")
    samples_with_data: int = strawberry.field(
        description="Buckets in the window for which Drive has data for this disk"
    )
    read_kbps_avg: float | None = strawberry.field(description="Mean read throughput over those buckets, KB/s")
    read_kbps_max: float | None = strawberry.field(description="Highest bucket read throughput, KB/s")
    write_kbps_avg: float | None = strawberry.field(description="Mean write throughput over those buckets, KB/s")
    write_kbps_max: float | None = strawberry.field(description="Highest bucket write throughput, KB/s")
    temperature_c_latest: float | None = strawberry.field(description="Most recent temperature, degrees Celsius")
    temperature_c_max: float | None = strawberry.field(description="Highest temperature in the window")
    bad_sector_count_latest: BigInt | None = strawberry.field(description="Most recent SMART bad sector count")
    bad_sector_count_increase: BigInt | None = strawberry.field(
        description=(
            "Change in the bad sector count from the first to the last bucket with data; "
            "negative when the counter reset or the disk in the bay was replaced"
        )
    )
    samples: list[DriveDiskStatsSample] | None = strawberry.field(
        description=(
            "Per-bucket values, oldest first. The REST route and the action return them only with "
            "include_samples: they add about 12 KB per disk per day at 15-minute buckets"
        )
    )

    _nested = {"samples": (DriveDiskStatsSample, True)}
    _columns = ["slot_id", "bay_type", "temperature_c_max", "read_kbps_avg", "write_kbps_avg"]


@strawberry.type(description=DESCRIPTION)
class DriveDiskStats(Projection):
    window_start: str | None = strawberry.field(description="Start of the first bucket, ISO 8601 in UTC")
    window_end: str | None = strawberry.field(description="End of the last bucket, ISO 8601 in UTC")
    interval_seconds: int | None = strawberry.field(description="Length of each bucket in seconds")
    sample_count: int | None = strawberry.field(description="Buckets in the window")
    disks: list[DriveDiskActivity] | None = strawberry.field(description="One entry per disk and cache SSD")

    _nested = {"disks": (DriveDiskActivity, True)}
    _columns = ["window_start", "window_end", "interval_seconds", "sample_count"]
