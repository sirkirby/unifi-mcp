"""Snapshot overview and per-drive snapshot list.

The overview's shared entries keep the shape captured from a UNAS Pro 8
(UniFi OS 6.0.18, Drive 4.4.31) with synthetic ids and names. That NAS had no
personal drives and no snapshots, so personal entries, scheduled settings and
snapshot entries are synthetic, modelled on the fields Drive's web UI reads.
"""

import copy

import pytest
from unifi_core.drive.managers.shared_drive_manager import SharedDriveManager
from unifi_core.drive.managers.snapshot_manager import SnapshotManager
from unifi_core.drive.models.snapshots import snapshot_schedule_from_api
from unifi_core.exceptions import (
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiValidationError,
)

from tests.drive import fixtures as fx

OVERVIEW = "/proxy/drive/api/v1/systems/snapshot"
SNAPSHOTS = "/proxy/drive/api/v1/snapshots/shared"
DRIVES = "/proxy/drive/api/v2/drives"
USER_ID = "44444444-4444-4444-8444-444444444444"


def _v1(data):
    return {"err": None, "type": "single", "data": data}


def _unset_schedule():
    return {"interval": 0, "weekdays": "", "monthdays": "", "firstRunTime": "", "lastRunTime": "", "enable": False}


def _shared_entry(drive_id, name, **extra):
    entry = {
        "coverageSize": 0,
        "deletionCount": 0,
        "lastSnapshotTime": None,
        "lockedCount": 0,
        "maxCount": 0,
        "nextSnapshotTime": None,
        "paused": False,
        "restoreTriggerDisabled": False,
        "restoringDrive": False,
        "schedule": _unset_schedule(),
        "settingId": None,
        "sharedDrive": {"id": drive_id, "name": name, "status": "active"},
        "totalCount": 0,
    }
    entry.update(extra)
    return entry


def _overview():
    return {
        "personal": [
            {
                "coverageSize": 2048,
                "deletionCount": 0,
                "lastSnapshotTime": "2026-01-02T03:00:00Z",
                "lockedCount": 0,
                "maxCount": 10,
                "nextSnapshotTime": "2026-01-03T03:00:00Z",
                "paused": False,
                "restoringDrive": False,
                "schedule": {
                    "interval": 60,
                    "weekdays": "",
                    "monthdays": "1,15,L",
                    "firstRunTime": "3:00",
                    "lastRunTime": "3:00",
                    "enable": True,
                },
                "settingId": "setting-personal-1",
                "user": {"id": USER_ID, "firstName": "Synthetic", "lastName": "Person"},
                "storageProfile": {"id": "profile-1", "enable": True},
                "encryptionStatus": "unencrypted",
                "totalCount": 3,
            }
        ],
        "shared": [
            _shared_entry(fx.DRIVE_ID, "Media"),
            _shared_entry(fx.OTHER_DRIVE_ID, "Backups", paused=True, pauseReason="ErrSnapshotStorageLow"),
        ],
    }


@pytest.fixture
def snapshots(connection):
    return SnapshotManager(connection, SharedDriveManager(connection))


async def test_overview_reads_shared_and_personal_drives(snapshots, console):
    console.reply("GET", OVERVIEW, _v1(_overview()))

    overview = await snapshots.get_snapshot_overview()

    assert len(overview.shared_drives) == 2 and len(overview.personal_drives) == 1
    media, backups = overview.shared_drives
    assert (media.drive_type, media.shared_drive_id, media.shared_drive_name) == ("shared", fx.DRIVE_ID, "Media")
    assert media.configured is False and media.snapshot_limit == 0 and media.snapshot_count == 0
    assert media.paused is False and media.pause_reason is None and media.restoring is False
    assert media.schedule.enabled is False and media.schedule.frequency is None
    assert media.schedule.interval_minutes is None and media.schedule.start_time is None
    assert backups.paused is True and backups.pause_reason == "ErrSnapshotStorageLow"
    (personal,) = overview.personal_drives
    assert personal.drive_type == "personal" and personal.user_id == USER_ID and personal.shared_drive_id is None
    assert personal.configured is True and (personal.snapshot_limit, personal.snapshot_count) == (10, 3)
    assert personal.coverage_bytes == 2048 and personal.encryption_status == "unencrypted"
    assert personal.schedule.frequency == "monthly" and personal.schedule.monthdays == ["1", "15", "L"]
    assert personal.schedule.interval_minutes == 60 and personal.schedule.start_time == "3:00"


async def test_overview_drops_owner_names(snapshots, console):
    console.reply("GET", OVERVIEW, _v1(_overview()))

    overview = await snapshots.get_snapshot_overview()

    dumped = str([drive.model_dump() for drive in overview.personal_drives])
    assert "Synthetic" not in dumped and "Person" not in dumped and "profile-1" not in dumped


@pytest.mark.parametrize(
    ("weekdays", "monthdays", "frequency", "days"),
    [
        ("*", "", "daily", []),
        ("1,3,5", "", "weekly", [1, 3, 5]),
        ("", "1,L", "monthly", []),
        ("", "", None, []),
    ],
)
def test_schedule_frequency_follows_the_days_set(weekdays, monthdays, frequency, days):
    schedule = snapshot_schedule_from_api(
        {"interval": 15, "weekdays": weekdays, "monthdays": monthdays, "enable": True}
    )

    assert schedule.frequency == frequency and schedule.weekdays == days


async def test_overview_that_is_not_a_drive_split_is_malformed(snapshots, console):
    console.reply("GET", OVERVIEW, _v1([]))

    with pytest.raises(UniFiMalformedResponseError):
        await snapshots.get_snapshot_overview()


async def test_list_snapshots_by_name(snapshots, console):
    listed = [
        {"id": "snap-2", "name": "", "createdAt": "2026-01-02T03:00:00Z", "locked": True},
        {"id": "snap-1", "name": "before upgrade", "createdAt": "2026-01-01T03:00:00Z", "locked": False},
    ]
    console.reply("GET", f"{SNAPSHOTS}/Media", _v1(copy.deepcopy(listed)))

    newest, oldest = await snapshots.list_snapshots("Media")

    assert newest.model_dump() == {"id": "snap-2", "name": None, "created_at": "2026-01-02T03:00:00Z", "locked": True}
    assert (oldest.id, oldest.name, oldest.locked) == ("snap-1", "before upgrade", False)
    assert console.writes == []


async def test_a_drive_without_snapshots_lists_none(snapshots, console):
    console.reply("GET", f"{SNAPSHOTS}/Media", _v1([]))

    assert await snapshots.list_snapshots("Media") == []


async def test_a_name_with_a_single_dot_is_one_segment(snapshots, console):
    console.reply("GET", f"{SNAPSHOTS}/team.docs", _v1([]))

    assert await snapshots.list_snapshots("team.docs") == []


@pytest.mark.parametrize("name", ["", "..", ".hidden", "a..b", "../storage", "a/b", "a b", "a%2e", "a?b", "a#b", 7])
async def test_a_name_that_is_not_one_segment_is_refused_without_a_request(snapshots, console, name):
    with pytest.raises(UniFiValidationError, match="Invalid shared drive name"):
        await snapshots.list_snapshots(name)
    assert console.requests == []


async def test_an_unknown_name_is_not_found(snapshots, console):
    # Drive answers 403 for a name no shared drive has.
    console.reply(
        "GET", f"{SNAPSHOTS}/Missing", {"err": {"msg": "Forbidden"}, "type": "single", "data": []}, status=403
    )
    console.reply("GET", DRIVES, fx.drives())

    with pytest.raises(UniFiNotFoundError, match="Missing"):
        await snapshots.list_snapshots("Missing")


async def test_a_refusal_for_a_listed_drive_stays_a_permission_error(snapshots, console):
    name = fx.drives()["drives"][0]["name"]
    console.reply("GET", f"{SNAPSHOTS}/{name}", {"err": {"msg": "Forbidden"}, "type": "single", "data": []}, status=403)
    console.reply("GET", DRIVES, fx.drives())

    with pytest.raises(UniFiPermissionError):
        await snapshots.list_snapshots(name)


async def test_a_snapshot_list_that_is_not_a_list_is_malformed(snapshots, console):
    console.reply("GET", f"{SNAPSHOTS}/Media", _v1({"snapshots": []}))

    with pytest.raises(UniFiMalformedResponseError):
        await snapshots.list_snapshots("Media")
