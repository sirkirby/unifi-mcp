"""Snapshot tools: response shape and error reporting. Fixtures are synthetic."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from unifi_core.drive.models.snapshots import snapshot_from_api, snapshot_overview_from_api
from unifi_core.exceptions import UniFiNotFoundError, UniFiPermissionError, UniFiValidationError
from unifi_drive_mcp.tools import snapshots

DRIVE_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def manager(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(snapshots, "snapshot_manager", fake)
    return fake


async def test_overview_lists_shared_and_personal_drives(manager):
    manager.get_snapshot_overview.return_value = snapshot_overview_from_api(
        {
            "personal": [],
            "shared": [
                {
                    "sharedDrive": {"id": DRIVE_ID, "name": "Media", "status": "active"},
                    "settingId": None,
                    "maxCount": 0,
                    "totalCount": 0,
                    "paused": True,
                    "pauseReason": "ErrSnapshotStorageLow",
                    "schedule": {"interval": 60, "weekdays": "*", "monthdays": "", "enable": True},
                }
            ],
        }
    )

    result = await snapshots.drive_get_snapshot_overview()

    assert result == {
        "success": True,
        "data": {
            "shared_drives": [
                {
                    "drive_type": "shared",
                    "shared_drive_id": DRIVE_ID,
                    "shared_drive_name": "Media",
                    "shared_drive_status": "active",
                    "configured": False,
                    "snapshot_limit": 0,
                    "snapshot_count": 0,
                    "paused": True,
                    "pause_reason": "ErrSnapshotStorageLow",
                    "schedule": {
                        "enabled": True,
                        "frequency": "daily",
                        "weekdays": [],
                        "monthdays": [],
                        "interval_minutes": 60,
                    },
                }
            ],
            "personal_drives": [],
        },
    }


async def test_overview_refused_by_the_nas_names_the_operation(manager):
    manager.get_snapshot_overview.side_effect = UniFiPermissionError("UniFi Drive refused GET /x (403).")

    result = await snapshots.drive_get_snapshot_overview()

    assert result == {"success": False, "error": "Failed to get snapshot overview: UniFi Drive refused GET /x (403)."}


async def test_list_snapshots_passes_the_name(manager):
    manager.list_snapshots.return_value = [
        snapshot_from_api({"id": "snap-1", "name": "", "createdAt": "2026-01-02T03:00:00Z", "locked": True})
    ]

    result = await snapshots.drive_list_snapshots("Media")

    manager.list_snapshots.assert_awaited_once_with("Media")
    assert result == {
        "success": True,
        "data": {"snapshots": [{"id": "snap-1", "created_at": "2026-01-02T03:00:00Z", "locked": True}], "count": 1},
    }


async def test_list_snapshots_keeps_drives_label(manager):
    manager.list_snapshots.return_value = [
        snapshot_from_api(
            {
                "id": "snap-2",
                "name": "",
                "description": "Scheduled Snapshot",
                "createdAt": "2026-01-03T03:00:00Z",
                "locked": False,
            }
        )
    ]

    result = await snapshots.drive_list_snapshots("Media")

    assert result["data"]["snapshots"] == [
        {"id": "snap-2", "description": "Scheduled Snapshot", "created_at": "2026-01-03T03:00:00Z", "locked": False}
    ]


async def test_a_drive_without_snapshots_is_an_empty_list(manager):
    manager.list_snapshots.return_value = []

    result = await snapshots.drive_list_snapshots("Media")

    assert result == {"success": True, "data": {"snapshots": [], "count": 0}}


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (UniFiNotFoundError("Shared drive", "Missing"), "Failed to list snapshots: Shared drive 'Missing' not found"),
        (UniFiValidationError("Invalid shared drive name"), "Failed to list snapshots: Invalid shared drive name"),
        (RuntimeError("https://192.0.2.10/detail"), "Failed to list snapshots: unexpected RuntimeError"),
    ],
)
async def test_list_snapshots_errors(manager, error, message):
    manager.list_snapshots.side_effect = error

    result = await snapshots.drive_list_snapshots("Missing")

    assert result == {"success": False, "error": message}
