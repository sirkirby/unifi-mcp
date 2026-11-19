"""Tool wrappers: argument validation, preview/confirm, response shape and error reporting."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from unifi_core.drive.managers.file_service_manager import NfsChange, ServiceChange
from unifi_core.drive.models.drives import shared_drive_from_api
from unifi_core.drive.models.services import NfsConnectionInput, nfs_connection_from_api
from unifi_core.drive.models.storage import disk_slot_from_api, storage_pool_from_api
from unifi_core.drive.models.system import system_info_from_api
from unifi_core.exceptions import UniFiConnectionError, UniFiNotFoundError, UniFiValidationError
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


def _nfs_change(action: str, *, after=CONNECTION, before=None) -> NfsChange:
    return NfsChange(
        action=action,
        client=CLIENT,
        before=before,
        after=after,
        connections=[{"client": "192.0.2.77", "async": False, "sharedDrives": []}],
        unchanged_clients=["192.0.2.77"],
        based_on=[{"client": "192.0.2.77", "async": False, "sharedDrives": []}],
        warnings=["a warning"],
    )


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


# --- file service toggle -----------------------------------------------------------


async def test_set_file_service_previews_without_writing(files):
    files.plan_set_file_service.return_value = ServiceChange("nfs", True, False, ["NFS clients lose their mounts."])

    result = await file_services.drive_set_file_service("nfs", False)

    assert result["requires_confirmation"] is True
    assert result["preview"] == {"current": {"enabled": True}, "proposed": {"enabled": False}}
    assert result["warnings"] == ["NFS clients lose their mounts."]
    files.apply_set_file_service.assert_not_awaited()


async def test_set_file_service_confirmed_applies(files):
    change = ServiceChange("smb", False, True)
    files.plan_set_file_service.return_value = change
    files.apply_set_file_service.return_value = True

    result = await file_services.drive_set_file_service("smb", True, confirm=True)

    files.apply_set_file_service.assert_awaited_once_with(change)
    assert result == {"success": True, "data": {"service": "smb", "enabled": True, "changed": True}}


async def test_set_file_service_already_in_state_is_a_no_op(files):
    files.plan_set_file_service.return_value = ServiceChange("smb", True, True)

    result = await file_services.drive_set_file_service("smb", True, confirm=True)

    assert result["data"]["changed"] is False
    files.apply_set_file_service.assert_not_awaited()


# --- NFS connections ---------------------------------------------------------------


async def test_add_validates_before_any_request(files):
    result = await nfs.drive_add_nfs_connection("* (rw,no_root_squash)", [{"id": DRIVE_ID}])

    assert result["success"] is False and result["error"].startswith("Invalid input (client)")
    files.plan_add_nfs_connection.assert_not_awaited()


@pytest.mark.parametrize(
    "grants",
    [[], [{"id": DRIVE_ID, "permission": "full"}], [{"id": DRIVE_ID, "squash": "all"}], [{"id": DRIVE_ID}] * 2],
)
async def test_add_refuses_bad_grants(files, grants):
    result = await nfs.drive_add_nfs_connection(CLIENT, grants)

    assert result["success"] is False and result["error"].startswith("Invalid input")
    files.plan_add_nfs_connection.assert_not_awaited()


async def test_add_previews_the_new_client_and_the_ones_kept(files):
    files.plan_add_nfs_connection.return_value = _nfs_change("add")

    result = await nfs.drive_add_nfs_connection(CLIENT, [{"id": DRIVE_ID, "permission": "rw"}])

    (planned,) = files.plan_add_nfs_connection.await_args.args
    assert isinstance(planned, NfsConnectionInput) and planned.shared_drives[0].permission == "rw"
    assert result["requires_confirmation"] is True
    assert result["preview"]["will_create"]["client"] == CLIENT
    assert result["preview"]["unchanged_connections"] == ["192.0.2.77"]
    assert result["warnings"] == ["a warning"]
    files.add_nfs_connection.assert_not_awaited()


async def test_add_confirmed_writes_under_the_lock_and_returns_the_saved_connection(files):
    files.add_nfs_connection.return_value = (_nfs_change("add"), CONNECTION)

    result = await nfs.drive_add_nfs_connection(CLIENT, [{"id": DRIVE_ID}], confirm=True)

    (planned,) = files.add_nfs_connection.await_args.args
    assert planned.client == CLIENT
    # The confirmed write plans inside the manager's locked method, not from a separate plan.
    files.plan_add_nfs_connection.assert_not_awaited()
    assert result["data"]["connection"]["client"] == CLIENT


async def test_add_listed_grant_round_trips(files):
    files.plan_add_nfs_connection.return_value = _nfs_change("add")
    listed = CONNECTION.model_dump(exclude_none=True)["shared_drives"]

    result = await nfs.drive_add_nfs_connection("192.0.2.80", listed)

    assert result["success"] is True


async def test_add_validation_error_from_the_manager(files):
    files.plan_add_nfs_connection.side_effect = UniFiValidationError("Unknown shared drive id(s): nope.")

    result = await nfs.drive_add_nfs_connection(CLIENT, [{"id": "nope"}])

    assert result == {"success": False, "error": "Failed to add NFS connection: Unknown shared drive id(s): nope."}


async def test_update_passes_only_given_fields(files):
    files.plan_update_nfs_connection.return_value = _nfs_change("update", before=CONNECTION)

    result = await nfs.drive_update_nfs_connection(CLIENT, async_writes=True)

    files.plan_update_nfs_connection.assert_awaited_once_with(CLIENT, shared_drives=None, async_writes=True)
    assert result["requires_confirmation"] is True and result["action"] == "update"
    files.update_nfs_connection.assert_not_awaited()


async def test_update_confirmed_writes_under_the_lock(files):
    files.update_nfs_connection.return_value = (_nfs_change("update", before=CONNECTION), CONNECTION)

    result = await nfs.drive_update_nfs_connection(CLIENT, shared_drives=[{"id": DRIVE_ID}], confirm=True)

    args = files.update_nfs_connection.await_args
    assert args.args == (CLIENT,) and args.kwargs["async_writes"] is None
    (grant,) = args.kwargs["shared_drives"]
    # Permission left out stays unset, so the manager can keep the drive's current one.
    assert grant.id == DRIVE_ID and "permission" not in grant.model_fields_set
    assert result["data"]["connection"]["client"] == CLIENT


async def test_update_unknown_client(files):
    files.update_nfs_connection.side_effect = UniFiNotFoundError("NFS connection", "192.0.2.9")

    result = await nfs.drive_update_nfs_connection("192.0.2.9", async_writes=True, confirm=True)

    assert result == {
        "success": False,
        "error": "Failed to update NFS connection: NFS connection '192.0.2.9' not found",
    }


async def test_remove_previews_then_applies(files):
    change = _nfs_change("remove", after=None, before=CONNECTION)
    files.plan_remove_nfs_connection.return_value = change
    files.remove_nfs_connection.return_value = change

    preview = await nfs.drive_remove_nfs_connection(CLIENT)
    files.remove_nfs_connection.assert_not_awaited()
    done = await nfs.drive_remove_nfs_connection(CLIENT, confirm=True)

    assert preview["action"] == "delete" and preview["preview"]["will_delete"]["client"] == CLIENT
    assert done == {"success": True, "data": {"removed": CLIENT}}
    files.remove_nfs_connection.assert_awaited_once_with(CLIENT)
