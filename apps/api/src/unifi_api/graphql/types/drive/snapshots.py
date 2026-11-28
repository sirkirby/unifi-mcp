"""UniFi Drive snapshot settings and state per drive, and one shared drive's snapshots."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.scalars import BigInt
from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class DriveSnapshotSchedule(Projection):
    enabled: bool | None = strawberry.field(description="Whether scheduled snapshots are on")
    frequency: str | None = strawberry.field(
        description="daily, weekly or monthly; absent when the schedule is off and has no days set"
    )
    weekdays: list[int] | None = strawberry.field(
        description="Days of a weekly schedule, 0 (Sunday) to 6; empty otherwise"
    )
    monthdays: list[str] | None = strawberry.field(
        description="Days of a monthly schedule, 1 to 28, or L for the last day of the month; empty otherwise"
    )
    interval_minutes: int | None = strawberry.field(
        description="Minutes between snapshots inside the daily window; absent when unset"
    )
    start_time: str | None = strawberry.field(
        description="Start of the daily window as H:MM, in the NAS console's local time"
    )
    end_time: str | None = strawberry.field(
        description="End of the daily window as H:MM, in the NAS console's local time"
    )


@strawberry.type(description=DESCRIPTION)
class DriveSnapshotStatus(Projection):
    drive_type: str = strawberry.field(description="shared or personal")
    shared_drive_id: str | None = strawberry.field(
        description=(
            "Shared drive id, the same id drive_list_shared_drives returns. These IDs are scoped to the "
            "UniFi Drive tool family."
        )
    )
    shared_drive_name: str | None = strawberry.field(
        description="Shared drive name; pass it to drive_list_snapshots as shared_drive_name"
    )
    shared_drive_status: str | None = strawberry.field(description="Shared drive status, such as active")
    user_id: str | None = strawberry.field(
        description=(
            "User id of a personal drive's owner. These IDs are scoped to UniFi Drive users; do not pass "
            "them as shared drive ids."
        )
    )
    configured: bool | None = strawberry.field(description="Whether snapshot settings were ever saved for this drive")
    snapshot_limit: int | None = strawberry.field(
        description="Most snapshots Drive keeps for the drive; 0 when snapshots are not set up"
    )
    snapshot_count: int | None = strawberry.field(description="Snapshots the drive has now")
    locked_count: int | None = strawberry.field(
        description="Locked snapshots, which Drive never removes to make room for new ones"
    )
    pending_deletion_count: int | None = strawberry.field(description="Snapshots queued for deletion")
    coverage_bytes: BigInt | None = strawberry.field(description="Space the drive's snapshots hold, in bytes")
    last_snapshot_time: str | None = strawberry.field(description="When the last snapshot was taken")
    next_snapshot_time: str | None = strawberry.field(description="When the next scheduled snapshot is due")
    paused: bool | None = strawberry.field(description="Whether Drive has paused snapshots of this drive")
    pause_reason: str | None = strawberry.field(
        description=(
            "Why snapshots are paused, such as ErrSnapshotStorageLow, ErrSnapshotDeletionQueueFull or "
            "ErrSnapshotDeletionQueueStuck"
        )
    )
    restoring: bool | None = strawberry.field(description="Whether the drive is being restored from a snapshot")
    encryption_status: str | None = strawberry.field(description="Encryption status, when Drive reports one")
    schedule: DriveSnapshotSchedule | None = strawberry.field(description="Snapshot schedule")

    _nested = {"schedule": (DriveSnapshotSchedule, False)}
    _columns = ["drive_type", "shared_drive_name", "snapshot_count", "snapshot_limit", "paused"]


@strawberry.type(description=DESCRIPTION)
class DriveSnapshotOverview(Projection):
    shared_drives: list[DriveSnapshotStatus] | None = strawberry.field(description="Shared drives")
    personal_drives: list[DriveSnapshotStatus] | None = strawberry.field(description="Personal drives")

    _nested = {"shared_drives": (DriveSnapshotStatus, True), "personal_drives": (DriveSnapshotStatus, True)}


@strawberry.type(description=DESCRIPTION)
class DriveSnapshot(Projection):
    id: str | None = strawberry.field(
        description=(
            "Snapshot id. These IDs are scoped to one shared drive's snapshots in the UniFi Drive tool family."
        )
    )
    name: str | None = strawberry.field(description="Snapshot name; Drive leaves it empty unless one was given")
    description: str | None = strawberry.field(
        description="Drive's label for the snapshot, e.g. Scheduled Snapshot for one the schedule took"
    )
    created_at: str | None = strawberry.field(description="When the snapshot was taken")
    locked: bool | None = strawberry.field(
        description="Whether the snapshot is locked, so Drive never removes it to make room"
    )

    _identity = "id"
    _columns = ["name", "description", "created_at", "locked"]
