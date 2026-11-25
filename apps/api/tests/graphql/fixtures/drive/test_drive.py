"""Every Drive query field, resolved through the real core managers.

# tool: drive_get_system_info
# tool: drive_list_storage_pools
# tool: drive_list_disks
# tool: drive_list_shared_drives
# tool: drive_get_shared_drive
# tool: drive_get_file_services
# tool: drive_list_nfs_connections
"""

from __future__ import annotations

import pytest

from tests.drive_data import BIG_CAPACITY, DRIVE_ID, FakeDrive, bootstrap, drive_cm, install
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
