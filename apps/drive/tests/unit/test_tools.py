"""Tool wrappers: response shape and error reporting."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from unifi_core.drive.models.drives import shared_drive_from_api
from unifi_core.drive.models.services import nfs_connection_from_api
from unifi_core.drive.models.storage import disk_slot_from_api, storage_pool_from_api
from unifi_core.drive.models.system import system_info_from_api
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError
from unifi_drive_mcp.tools import file_services, nfs, shared_drives, storage, system

DRIVE_ID = "22222222-2222-4222-8222-222222222222"
CLIENT = "192.0.2.76"
CONNECTION = nfs_connection_from_api(
    {"client": CLIENT, "async": False, "sharedDrives": [{"id": DRIVE_ID, "name": "Shared_Drive", "permission": "rw"}]}
)


@pytest.fixture
def files(monkeypatch):
    manager = AsyncMock()
    monkeypatch.setattr(file_services, "file_service_manager", manager)
    monkeypatch.setattr(nfs, "file_service_manager", manager)
    return manager


# --- reads -------------------------------------------------------------------


async def test_system_info(monkeypatch):
    manager = AsyncMock()
    manager.get_system_info.return_value = system_info_from_api({"name": "NAS", "hardware": {"shortname": "UNASPRO8"}})
    monkeypatch.setattr(system, "system_manager", manager)

    result = await system.drive_get_system_info()

    assert result == {"success": True, "data": {"name": "NAS", "shortname": "UNASPRO8"}}


async def test_storage_tools_pass_filters(monkeypatch):
    manager = AsyncMock()
    manager.list_pools.return_value = [storage_pool_from_api({"id": "p1", "capacity": 200, "usage": 50})]
    manager.list_disks.return_value = [disk_slot_from_api({"slotId": "1", "state": "optimal", "temperature": 30})]
    monkeypatch.setattr(storage, "storage_manager", manager)

    pools = await storage.drive_list_storage_pools()
    disks = await storage.drive_list_disks(include_empty=True, include_cache=False)

    assert pools["data"]["pools"][0]["used_percent"] == 25.0 and pools["data"]["count"] == 1
    manager.list_disks.assert_awaited_once_with(include_empty=True, include_cache=False)
    assert disks["data"]["disks"][0]["temperature_c"] == 30


async def test_shared_drive_not_found_is_a_plain_error(monkeypatch):
    manager = AsyncMock()
    manager.get_shared_drive.side_effect = UniFiNotFoundError("Shared drive", "x")
    monkeypatch.setattr(shared_drives, "shared_drive_manager", manager)

    result = await shared_drives.drive_get_shared_drive("x")

    assert result == {"success": False, "error": "Failed to get shared drive: Shared drive 'x' not found"}


async def test_list_shared_drives(monkeypatch):
    manager = AsyncMock()
    manager.list_shared_drives.return_value = [shared_drive_from_api({"id": DRIVE_ID, "name": "Shared_Drive"})]
    monkeypatch.setattr(shared_drives, "shared_drive_manager", manager)

    result = await shared_drives.drive_list_shared_drives()

    assert result["data"] == {"drives": [{"id": DRIVE_ID, "name": "Shared_Drive"}], "count": 1}


async def test_read_failure_names_the_operation(files):
    files.get_file_services.side_effect = UniFiConnectionError("UniFi Drive request GET /x timed out.")

    result = await file_services.drive_get_file_services()

    assert result == {"success": False, "error": "Failed to get file services: UniFi Drive request GET /x timed out."}


async def test_unexpected_exception_returns_only_its_class(files):
    files.list_nfs_connections.side_effect = RuntimeError("https://192.0.2.10/secret detail")

    result = await nfs.drive_list_nfs_connections()

    assert result == {"success": False, "error": "Failed to list NFS connections: unexpected RuntimeError"}


async def test_list_nfs_connections(files):
    files.list_nfs_connections.return_value = [CONNECTION]

    result = await nfs.drive_list_nfs_connections()

    grant = result["data"]["connections"][0]["shared_drives"][0]
    assert grant["export_path"] == "/var/nfs/shared/Shared_Drive" and result["data"]["count"] == 1
