"""Every Drive query field, resolved through the real core managers.

# tool: drive_get_system_info
# tool: drive_list_storage_pools
# tool: drive_list_disks
# tool: drive_list_shared_drives
# tool: drive_get_shared_drive
# tool: drive_get_file_services
# tool: drive_list_nfs_connections
# tool: drive_list_logs
# tool: drive_get_storage_usage
# tool: drive_get_network_throughput
# tool: drive_get_fan_profile
# tool: drive_get_disk_stats
# tool: drive_get_snapshot_overview
# tool: drive_list_snapshots
# tool: drive_get_smb_advanced_settings
# tool: drive_get_rsync_settings
# tool: drive_list_users
# tool: drive_list_groups
"""

from __future__ import annotations

import pytest

from tests.drive_data import (
    BIG_CAPACITY,
    DRIVE_ID,
    GROUP_ID,
    LOG_CURSOR,
    POOL_ID,
    RSYNC_PASSWORD,
    USER_ID,
    FakeDrive,
    bootstrap,
    drive_cm,
    install,
)
from tests.innerspace_data import graphql


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")


async def _app(tmp_path, nas):
    app, key, cid = await bootstrap(tmp_path)
    install(app, cid, drive_cm(nas))
    return app, None, key, cid


@pytest.mark.asyncio
async def test_graphql_drive_namespace_reads_every_resource(tmp_path):
    app, _headers, key, cid = await _app(tmp_path, FakeDrive())
    query = f"""{{ drive {{
        systemInfo(controller: "{cid}") {{ model memoryTotalKb driveVersion driveUpdateAvailable }}
        storagePools(controller: "{cid}") {{ id capacityBytes raidGroups {{ currentLevel }} }}
        disks(controller: "{cid}", includeEmpty: true) {{ slotId bayType riskReasons }}
        sharedDrives(controller: "{cid}") {{ id name }}
        sharedDrive(controller: "{cid}", driveId: "{DRIVE_ID}") {{ name }}
        fileServices(controller: "{cid}") {{ smbEnabled networkInterfaces {{ name }} }}
        nfsConnections(controller: "{cid}") {{ client sharedDrives {{ id permission exportPath }} }}
    }} }}"""

    body = await graphql(app, key, query)

    assert "errors" not in body, body
    drive = body["data"]["drive"]
    assert drive["systemInfo"]["model"] == "UniFi Network Attached Storage Pro 8"
    assert (drive["systemInfo"]["driveVersion"], drive["systemInfo"]["driveUpdateAvailable"]) == ("4.4.31", "4.5.7")
    assert drive["storagePools"][0]["capacityBytes"] == BIG_CAPACITY
    assert drive["storagePools"][0]["raidGroups"] == [{"currentLevel": "raid1"}]
    assert [d["slotId"] for d in drive["disks"]] == ["1", "2", "1"]
    assert drive["sharedDrive"] == {"name": "Shared_Drive"}
    assert drive["fileServices"]["networkInterfaces"] == [{"name": "enp0s0"}]
    assert drive["nfsConnections"][1]["sharedDrives"][0]["permission"] == "ro"


@pytest.mark.asyncio
async def test_graphql_drive_namespace_reads_logs_performance_snapshots_settings_and_users(tmp_path):
    app, _headers, key, cid = await _app(tmp_path, FakeDrive())
    query = f"""{{ drive {{
        logs(controller: "{cid}", category: "storage", severities: ["very_high", "low"]) {{
            entries {{ time severity type event title message }}
            nextCursor
        }}
        storageUsage(controller: "{cid}") {{ poolId capacityBytes systemBytes }}
        networkThroughput(controller: "{cid}") {{ receiveKbps transmitKbps }}
        fanProfile(controller: "{cid}") {{ currentLabel availableProfiles {{ profile label }} }}
        diskStats(controller: "{cid}", hours: 6) {{
            intervalSeconds sampleCount
            disks {{ slotId bayType samplesWithData temperatureCMax badSectorCountIncrease samples {{ readKbps }} }}
        }}
        snapshotOverview(controller: "{cid}") {{
            sharedDrives {{ sharedDriveName paused pauseReason schedule {{ enabled frequency }} }}
            personalDrives {{ userId coverageBytes schedule {{ frequency monthdays }} }}
        }}
        snapshots(controller: "{cid}", sharedDriveName: "Media") {{ id name description locked }}
        smbAdvancedSettings(controller: "{cid}") {{ personalDriveRecycleEnabled personalDriveRecycleStatus }}
        rsyncSettings(controller: "{cid}") {{ enabled accountConfigured accountUsername sshEnabled }}
        users(controller: "{cid}") {{ id username accessLevel roles personalDriveEnabled lastLogin }}
        groups(controller: "{cid}") {{ id name }}
    }} }}"""

    body = await graphql(app, key, query)

    assert "errors" not in body, body
    drive = body["data"]["drive"]
    assert [entry["event"] for entry in drive["logs"]["entries"]] == ["StoragePoolArrayAtRiskSingle", "DriveInserted"]
    assert drive["logs"]["entries"][1]["message"] == "Bay 1 was inserted and is ready to use."
    assert drive["logs"]["nextCursor"] == LOG_CURSOR
    [usage] = drive["storageUsage"]
    assert (usage["poolId"], usage["capacityBytes"], usage["systemBytes"]) == (POOL_ID, BIG_CAPACITY, 1047691264)
    assert drive["networkThroughput"] == {"receiveKbps": 6.32, "transmitKbps": 17.45}
    assert drive["fanProfile"]["currentLabel"] == "Balanced"
    assert [option["label"] for option in drive["fanProfile"]["availableProfiles"]] == ["Cooling", "Balanced", "Quiet"]
    stats = drive["diskStats"]
    assert (stats["intervalSeconds"], stats["sampleCount"]) == (900, 2)
    bay, cache = stats["disks"]
    assert (bay["bayType"], bay["temperatureCMax"], bay["badSectorCountIncrease"]) == ("disk", 36, 2)
    # GraphQL returns the samples a query selects.
    assert [sample["readKbps"] for sample in bay["samples"]] == [100.5, 300.25]
    assert (cache["bayType"], cache["samplesWithData"]) == ("cache", 0)
    [shared] = drive["snapshotOverview"]["sharedDrives"]
    assert shared == {
        "sharedDriveName": "Media",
        "paused": True,
        "pauseReason": "ErrSnapshotStorageLow",
        "schedule": {"enabled": False, "frequency": None},
    }
    [personal] = drive["snapshotOverview"]["personalDrives"]
    assert (personal["userId"], personal["coverageBytes"]) == (USER_ID, BIG_CAPACITY)
    assert personal["schedule"] == {"frequency": "monthly", "monthdays": ["1", "15", "L"]}
    assert drive["snapshots"][0] == {"id": "snap-2", "name": None, "description": "Scheduled Snapshot", "locked": True}
    assert drive["smbAdvancedSettings"] == {
        "personalDriveRecycleEnabled": True,
        "personalDriveRecycleStatus": "optimal",
    }
    assert drive["rsyncSettings"] == {
        "enabled": True,
        "accountConfigured": True,
        "accountUsername": "backup",
        "sshEnabled": False,
    }
    assert RSYNC_PASSWORD not in str(body)
    owner, member = drive["users"]
    assert (owner["id"], owner["accessLevel"], owner["roles"], owner["personalDriveEnabled"]) == (
        USER_ID,
        "owner",
        ["owner"],
        True,
    )
    assert (member["accessLevel"], member["lastLogin"]) == ("user", None)
    assert drive["groups"] == [{"id": GROUP_ID, "name": "Family"}]
