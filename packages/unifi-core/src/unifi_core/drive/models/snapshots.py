"""Snapshot settings and snapshots from UniFi Drive's v1 snapshot endpoints.

``GET /proxy/drive/api/v1/systems/snapshot`` reports every drive's snapshot
settings and state, split into ``personal`` and ``shared`` lists. A drive whose
snapshots were never set up is still listed, with a zero limit and the schedule
off. ``GET /proxy/drive/api/v1/snapshots/shared/<name>`` lists one shared
drive's snapshots; Drive addresses that list by the shared drive's name, not
its id.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.drive.models._coerce import as_dict, as_list, flag, number, text

# Drive writes ``*`` for "every day" and day numbers 0 (Sunday) to 6.
_EVERY_DAY = "*"
_WEEKDAYS = frozenset(str(day) for day in range(7))


class SnapshotSchedule(BaseModel):
    """When Drive takes scheduled snapshots of one drive."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = Field(default=None, description="Whether scheduled snapshots are on")
    frequency: str | None = Field(
        default=None,
        description="daily, weekly or monthly; absent when the schedule is off and has no days set",
    )
    weekdays: list[int] = Field(
        default_factory=list, description="Days of a weekly schedule, 0 (Sunday) to 6; empty otherwise"
    )
    monthdays: list[str] = Field(
        default_factory=list,
        description="Days of a monthly schedule, 1 to 28, or L for the last day of the month; empty otherwise",
    )
    interval_minutes: int | None = Field(
        default=None, description="Minutes between snapshots inside the daily window; absent when unset"
    )
    start_time: str | None = Field(
        default=None, description="Start of the daily window as H:MM, in the NAS console's local time"
    )
    end_time: str | None = Field(
        default=None, description="End of the daily window as H:MM, in the NAS console's local time"
    )


class DriveSnapshotStatus(BaseModel):
    """One drive's snapshot settings and state."""

    model_config = ConfigDict(extra="ignore")

    drive_type: str = Field(description="shared or personal")
    shared_drive_id: str | None = Field(
        default=None,
        description=(
            "Shared drive id, the same id drive_list_shared_drives returns. These IDs are scoped to the "
            "UniFi Drive tool family."
        ),
    )
    shared_drive_name: str | None = Field(
        default=None, description="Shared drive name; pass it to drive_list_snapshots as shared_drive_name"
    )
    shared_drive_status: str | None = Field(default=None, description="Shared drive status, such as active")
    user_id: str | None = Field(
        default=None,
        description=(
            "User id of a personal drive's owner. These IDs are scoped to UniFi Drive users; do not pass "
            "them as shared drive ids."
        ),
    )
    configured: bool | None = Field(
        default=None, description="Whether snapshot settings were ever saved for this drive"
    )
    snapshot_limit: int | None = Field(
        default=None, description="Most snapshots Drive keeps for the drive; 0 when snapshots are not set up"
    )
    snapshot_count: int | None = Field(default=None, description="Snapshots the drive has now")
    locked_count: int | None = Field(
        default=None, description="Locked snapshots, which Drive never removes to make room for new ones"
    )
    pending_deletion_count: int | None = Field(default=None, description="Snapshots queued for deletion")
    coverage_bytes: int | None = Field(default=None, description="Space the drive's snapshots hold, in bytes")
    last_snapshot_time: str | None = Field(default=None, description="When the last snapshot was taken")
    next_snapshot_time: str | None = Field(default=None, description="When the next scheduled snapshot is due")
    paused: bool | None = Field(default=None, description="Whether Drive has paused snapshots of this drive")
    pause_reason: str | None = Field(
        default=None,
        description=(
            "Why snapshots are paused, such as ErrSnapshotStorageLow, ErrSnapshotDeletionQueueFull or "
            "ErrSnapshotDeletionQueueStuck"
        ),
    )
    restoring: bool | None = Field(default=None, description="Whether the drive is being restored from a snapshot")
    encryption_status: str | None = Field(default=None, description="Encryption status, when Drive reports one")
    schedule: SnapshotSchedule | None = Field(default=None, description="Snapshot schedule")


class SnapshotOverview(BaseModel):
    """Snapshot settings and state of every drive."""

    model_config = ConfigDict(extra="ignore")

    shared_drives: list[DriveSnapshotStatus] = Field(default_factory=list, description="Shared drives")
    personal_drives: list[DriveSnapshotStatus] = Field(default_factory=list, description="Personal drives")


class Snapshot(BaseModel):
    """One snapshot of a shared drive."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(
        default=None,
        description="Snapshot id. These IDs are scoped to one shared drive's snapshots in the UniFi Drive tool family.",
    )
    name: str | None = Field(default=None, description="Snapshot name; Drive leaves it empty unless one was given")
    created_at: str | None = Field(default=None, description="When the snapshot was taken")
    locked: bool | None = Field(
        default=None, description="Whether the snapshot is locked, so Drive never removes it to make room"
    )


def _count(value: Any) -> int | None:
    found = number(value)
    return int(found) if found is not None else None


def _days(value: Any) -> list[str]:
    raw = text(value)
    return [day.strip() for day in raw.split(",") if day.strip()] if raw else []


def snapshot_schedule_from_api(raw: Any) -> SnapshotSchedule:
    """Read a ``schedule`` object the way Drive's own settings panel does."""
    schedule = as_dict(raw)
    weekdays = _days(schedule.get("weekdays"))
    monthdays = _days(schedule.get("monthdays"))
    frequency: str | None = None
    if monthdays:
        frequency = "monthly"
    elif weekdays and weekdays != [_EVERY_DAY]:
        frequency = "weekly"
    elif weekdays == [_EVERY_DAY]:
        frequency = "daily"
    interval = _count(schedule.get("interval"))
    return SnapshotSchedule(
        enabled=flag(schedule.get("enable")),
        frequency=frequency,
        weekdays=sorted(int(day) for day in weekdays if day in _WEEKDAYS) if frequency == "weekly" else [],
        monthdays=monthdays,
        interval_minutes=interval if interval else None,
        start_time=text(schedule.get("firstRunTime")),
        end_time=text(schedule.get("lastRunTime")),
    )


def drive_snapshot_status_from_api(raw: Any, drive_type: str) -> DriveSnapshotStatus:
    """One entry of ``systems/snapshot``'s ``shared`` or ``personal`` list."""
    entry = as_dict(raw)
    shared = as_dict(entry.get("sharedDrive"))
    user = as_dict(entry.get("user"))
    schedule = entry.get("schedule")
    return DriveSnapshotStatus(
        drive_type=drive_type,
        shared_drive_id=text(shared.get("id")),
        shared_drive_name=text(shared.get("name")),
        shared_drive_status=text(shared.get("status")),
        user_id=text(user.get("id")),
        # Drive reports a drive whose settings were never saved with a null settingId.
        configured=entry.get("settingId") is not None if "settingId" in entry else None,
        snapshot_limit=_count(entry.get("maxCount")),
        snapshot_count=_count(entry.get("totalCount")),
        locked_count=_count(entry.get("lockedCount")),
        pending_deletion_count=_count(entry.get("deletionCount")),
        coverage_bytes=_count(entry.get("coverageSize")),
        last_snapshot_time=text(entry.get("lastSnapshotTime")),
        next_snapshot_time=text(entry.get("nextSnapshotTime")),
        paused=flag(entry.get("paused")),
        pause_reason=text(entry.get("pauseReason")),
        restoring=flag(entry.get("restoringDrive")),
        encryption_status=text(entry.get("encryptionStatus")),
        schedule=snapshot_schedule_from_api(schedule) if isinstance(schedule, dict) else None,
    )


def snapshot_overview_from_api(raw: Any) -> SnapshotOverview:
    body = as_dict(raw)
    return SnapshotOverview(
        shared_drives=[
            drive_snapshot_status_from_api(entry, "shared")
            for entry in as_list(body.get("shared"))
            if isinstance(entry, dict)
        ],
        personal_drives=[
            drive_snapshot_status_from_api(entry, "personal")
            for entry in as_list(body.get("personal"))
            if isinstance(entry, dict)
        ],
    )


def snapshot_from_api(raw: Any) -> Snapshot:
    snapshot = as_dict(raw)
    return Snapshot(
        id=text(snapshot.get("id")),
        name=text(snapshot.get("name")),
        created_at=text(snapshot.get("createdAt")),
        locked=flag(snapshot.get("locked")),
    )
