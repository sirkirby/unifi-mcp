"""Drive managers against sanitized captured responses, including the NFS read-modify-write."""

import asyncio

import pytest
from unifi_core.drive.managers.connection_manager import (
    DriveConnectionManager,
    DriveWriteNotSent,
    DriveWriteOutcomeUnknown,
)
from unifi_core.drive.managers.file_service_manager import FileServiceManager
from unifi_core.drive.managers.performance_manager import PerformanceManager, disk_stats_interval
from unifi_core.drive.managers.shared_drive_manager import SharedDriveManager
from unifi_core.drive.managers.storage_manager import StorageManager
from unifi_core.drive.managers.system_manager import DriveSystemManager
from unifi_core.drive.models.services import (
    MUTABLE_FIELDS,
    READ_ONLY_FIELDS,
    NfsConnection,
    NfsConnectionInput,
    NfsSharedDriveAccess,
    connection_to_controller,
    is_world_client,
    nfs_connection_from_api,
)
from unifi_core.exceptions import (
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiValidationError,
)
from unifi_core.operation_gate import GateSettings, OperationGate

from tests.drive import fixtures as fx
from tests.drive.conftest import HOST, PASSWORD, USERNAME

V1 = "/proxy/drive/api/v1/services"
NFS_ADVANCED = f"{V1}/nfs/advanced-settings"
TEST_HOSTNAMES = f"{V1}/nfs/test-hostnames"
DRIVES = "/proxy/drive/api/v2/drives"
SYSTEMS = "/proxy/drive/api/v2/systems"


RSYNC = "/proxy/drive/api/v2/services/rsync/settings"
SYSTEMS_INFO = "/proxy/drive/api/v1/systems/info"


@pytest.fixture
def files(connection):
    return FileServiceManager(connection, SharedDriveManager(connection))


def _script_services(console, *, smb=True, nfs=True, time_machine=True):
    console.reply("GET", f"{V1}/smb/settings", fx.service(smb), always=True)
    console.reply("GET", f"{V1}/nfs/settings", fx.service(nfs), always=True)
    console.reply("GET", f"{V1}/time-machine/settings", fx.service(time_machine), always=True)
    console.reply("GET", f"{V1}/settings", fx.services_settings(), always=True)


# --- reads -------------------------------------------------------------------


async def test_system_info_keeps_only_listed_fields(connection, console):
    console.reply("GET", "/api/system", fx.system())

    info = (await DriveSystemManager(connection).get_system_info()).model_dump(exclude_none=True)

    assert info["shortname"] == "UNASPRO8" and info["firmware_version"] == "5.0.12"
    assert info["firmware_update_available"] == "5.0.17+3f9b9ea"
    assert (info["drive_version"], info["drive_update_available"]) == ("4.4.31", "4.5.7")
    assert info["memory_total_kb"] == 16639296
    dumped = str(info)
    assert "198.51.100.1" not in dumped and "synthetic location" not in dumped and "synthetic-owner" not in dumped


async def test_storage_pools_report_degraded_raid(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/storage", fx.storage())

    (pool,) = await StorageManager(connection).list_pools()

    assert pool.id == fx.POOL_ID and pool.status == "noDataProtectionYet"
    assert pool.used_percent == pytest.approx(0.92, abs=0.01)
    (group,) = pool.raid_groups
    assert (group.current_level, group.config_level) == ("raid1", "raid5")
    assert (group.current_protection, group.expected_protection) == (0, 1)


async def test_storage_usage_splits_each_pool(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/storage/usage", fx.storage_usage())

    first, second = await StorageManager(connection).get_usage()

    assert first.model_dump(exclude_none=True) == {
        "pool_id": fx.POOL_ID,
        "capacity_bytes": 15992168120320,
        "used_bytes": 10826060070912,
        "available_bytes": 5166108049408,
        "used_percent": 67.7,
        "personal_drives_bytes": 0,
        "shared_drives_bytes": 10825012379648,
        "m365_bytes": 0,
        "system_bytes": 1047691264,
    }
    assert second.pool_id == fx.OTHER_POOL_ID and second.used_percent == pytest.approx(95.22)
    assert second.system_bytes == 11418377715712 - 1073741824 - 11400000000000


async def test_storage_usage_pool_ids_match_the_pool_list(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/storage", fx.storage())
    usage = fx.storage_usage()
    del usage[fx.OTHER_POOL_ID]
    console.reply("GET", "/proxy/drive/api/v2/storage/usage", usage)
    manager = StorageManager(connection)

    (pool,) = await manager.list_pools()
    (pool_usage,) = await manager.get_usage()

    assert pool_usage.pool_id == pool.id


async def test_storage_usage_reads_optional_parts_and_skips_a_split_it_cannot_make(connection, console):
    usage = fx.storage_usage()
    usage[fx.POOL_ID].update({"usedBySnapshots": 1000})
    del usage[fx.OTHER_POOL_ID]["poolId"]
    usage[fx.OTHER_POOL_ID]["iscsiInfo"] = {"usedByIscsiThin": 1, "reservedByIscsiThick": 2, "usedByIscsiThick": 3}
    usage["not-a-pool"] = "garbage"
    console.reply("GET", "/proxy/drive/api/v2/storage/usage", usage)

    first, second = await StorageManager(connection).get_usage()

    assert first.snapshots_bytes == 1000 and first.system_bytes == 1047691264 - 1000
    assert second.pool_id == fx.OTHER_POOL_ID and second.system_bytes is None


async def test_storage_usage_without_pools_is_empty(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/storage/usage", {})

    assert await StorageManager(connection).get_usage() == []


@pytest.mark.parametrize("body", [None, [], "x"])
async def test_unreadable_storage_usage_is_an_error(connection, console, body):
    console.reply("GET", "/proxy/drive/api/v2/storage/usage", body)

    with pytest.raises(UniFiMalformedResponseError):
        await StorageManager(connection).get_usage()


async def test_storage_usage_missing_endpoint_is_an_error(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/storage/usage", {"err": {"msg": "not found"}}, status=404)

    with pytest.raises(UniFiOperationError, match="no endpoint"):
        await StorageManager(connection).get_usage()


async def test_disks_skip_empty_bays_unless_asked(connection, console):
    console.reply("GET", "/proxy/drive/api/v2/storage", fx.storage(), always=True)
    manager = StorageManager(connection)

    (disk,) = await manager.list_disks()
    everything = await manager.list_disks(include_empty=True)
    bays_only = await manager.list_disks(include_empty=True, include_cache=False)

    assert disk.slot_id == "1" and disk.serial == "FAKESERIAL1" and disk.power_on_hours == 15592
    assert disk.bad_sector_count == 0 and disk.temperature_c == 33
    assert len(everything) == 10 and len(bays_only) == 8
    empty = everything[-1]
    assert empty.bay_type == "cache" and empty.state == "empty"
    assert empty.temperature_c is None and empty.power_on_hours is None and empty.rpm is None


async def test_shared_drives_read_quota_and_protections(connection, console):
    console.reply("GET", DRIVES, fx.drives())

    first, second = await SharedDriveManager(connection).list_shared_drives()

    assert first.quota_bytes is None and first.member_count == 2 and first.snapshot_enabled is False
    assert second.quota_bytes == 1099511627776 and second.snapshot_enabled is True


async def test_get_shared_drive_refuses_a_path_like_id(connection, console):
    with pytest.raises(UniFiValidationError):
        await SharedDriveManager(connection).get_shared_drive("../storage")
    assert console.requests == []


async def test_get_shared_drive_with_a_non_uuid_id_is_not_found_without_a_request(connection, console):
    # Drive answers 500, not 404, for an id that isn't a UUID.
    with pytest.raises(UniFiNotFoundError, match="not-a-drive"):
        await SharedDriveManager(connection).get_shared_drive("not-a-drive")
    assert console.requests == []


async def test_system_info_without_a_drive_app_entry_leaves_its_version_unset(connection, console):
    system = fx.system()
    del system["apps"]
    console.reply("GET", "/api/system", system)

    info = await DriveSystemManager(connection).get_system_info()

    assert info.drive_version is None and info.drive_update_available is None
    assert info.firmware_version == "5.0.12"


async def test_get_shared_drive_not_found(connection, console):
    console.reply("GET", f"{DRIVES}/{fx.DRIVE_ID}", {"err": {"msg": "drive not found"}}, status=404)

    with pytest.raises(UniFiNotFoundError):
        await SharedDriveManager(connection).get_shared_drive(fx.DRIVE_ID)


async def test_file_services_and_interfaces(files, console):
    _script_services(console, nfs=False)

    services = await files.get_file_services()

    assert (services.smb_enabled, services.nfs_enabled, services.time_machine_enabled) == (True, False, True)
    assert services.network_interfaces[0].address == "192.0.2.10"
    assert services.network_interfaces[1].connected is False


async def test_nfs_connections_carry_export_paths(files, console):
    console.reply("GET", NFS_ADVANCED, fx.nfs_advanced())

    (connection,) = await files.list_nfs_connections()

    assert connection.client == fx.CLIENT and connection.async_writes is False
    assert connection.shared_drives[0].export_path == "/var/nfs/shared/Shared_Drive"


# --- performance --------------------------------------------------------------


async def test_network_throughput_is_rounded_as_the_dashboard_shows_it(connection, console):
    console.reply("GET", f"{SYSTEMS}/network-io", fx.network_io())

    throughput = await PerformanceManager(connection).get_network_throughput()

    assert (throughput.receive_kbps, throughput.transmit_kbps) == (6.32, 17.45)
    assert throughput.timestamp == "2026-01-02T03:04:05.123456789-05:00"


async def test_fan_profile_carries_the_web_app_labels(connection, console):
    console.reply("GET", f"{SYSTEMS}/fan-control", fx.fan_control())

    fan = (await PerformanceManager(connection).get_fan_profile()).model_dump()

    assert (fan["current_profile"], fan["current_label"]) == ("default", "Balanced")
    assert [(p["profile"], p["label"]) for p in fan["available_profiles"]] == [
        ("cooling", "Cooling"),
        ("default", "Balanced"),
        ("quiet", "Quiet"),
    ]
    assert not console.writes


async def test_fan_profile_unknown_to_the_web_app_has_no_label(connection, console):
    console.reply("GET", f"{SYSTEMS}/fan-control", {"availableProfiles": ["turbo"], "currentProfile": "turbo"})

    fan = await PerformanceManager(connection).get_fan_profile()

    assert fan.current_profile == "turbo" and fan.current_label is None
    assert fan.available_profiles[0].label is None


@pytest.mark.parametrize("path", ["network-io", "fan-control"])
async def test_unreadable_performance_answer_is_an_error(connection, console, path):
    console.reply("GET", f"{SYSTEMS}/{path}", ["not", "an", "object"])
    manager = PerformanceManager(connection)
    read = manager.get_network_throughput if path == "network-io" else manager.get_fan_profile

    with pytest.raises(UniFiMalformedResponseError):
        await read()


async def test_disk_stats_asks_for_the_window_and_summarizes_each_disk(connection, console):
    console.reply("GET", f"{SYSTEMS}/disk-stats", fx.disk_stats())

    stats = await PerformanceManager(connection).get_disk_stats(hours=24)

    query = console.calls("GET", f"{SYSTEMS}/disk-stats")[0].query
    assert int(query["end"]) - int(query["start"]) == 24 * 3600
    assert query["interval"] == "900"
    assert (stats.interval_seconds, stats.sample_count) == (900, 2)
    assert stats.window_start == "2026-01-01T00:00:00+00:00"
    assert stats.window_end == "2026-01-01T00:30:00+00:00"

    first, second, cache = stats.disks
    assert (first.slot_id, first.bay_type, first.type) == ("1", "disk", "HDD")
    assert first.samples_with_data == 2
    assert (first.read_kbps_avg, first.read_kbps_max) == (200.38, 300.25)
    assert (first.write_kbps_avg, first.write_kbps_max) == (25.0, 50)
    assert (first.temperature_c_latest, first.temperature_c_max) == (36, 36)
    assert (first.bad_sector_count_latest, first.bad_sector_count_increase) == (2, 2)
    assert [s.time for s in first.samples] == ["2026-01-01T00:00:00+00:00", "2026-01-01T00:15:00+00:00"]

    # A bucket without data is kept as nulls and left out of the summary.
    assert second.samples_with_data == 1 and second.temperature_c_latest == 37
    assert second.samples[1].read_kbps is None

    assert (cache.bay_type, cache.samples_with_data, cache.read_kbps_avg) == ("cache", 0, None)
    assert "SYNTHETIC-SERIAL" not in str(stats.model_dump())


@pytest.mark.parametrize(
    ("hours", "interval"),
    [(1, 900), (167, 900), (168, 3600), (719, 3600), (720, 21600), (2160, 21600)],
)
def test_disk_stats_interval_follows_the_dashboard_steps(hours, interval):
    assert disk_stats_interval(hours) == interval
    # Drive refuses about a thousand buckets or more in one answer.
    assert hours * 3600 // interval <= 1000


@pytest.mark.parametrize("hours", [0, -1, 2161, True, 1.5])
async def test_disk_stats_refuses_a_bad_window_without_a_request(connection, console, hours):
    with pytest.raises(UniFiValidationError):
        await PerformanceManager(connection).get_disk_stats(hours=hours)

    assert not console.requests


@pytest.mark.parametrize(
    "body",
    [
        {"window": {"start": 1767225600, "interval": 900}},
        {"series": {"disks": []}, "window": {"interval": 900}},
        {"series": {"disks": []}, "window": {"start": 1767225600, "interval": 0}},
        {"series": {}, "window": {"start": 1767225600, "interval": 900}},
        {"series": {"disks": None}, "window": {"start": 1767225600, "interval": 900}},
    ],
)
async def test_unreadable_disk_stats_are_an_error(connection, console, body):
    console.reply("GET", f"{SYSTEMS}/disk-stats", body)

    with pytest.raises(UniFiMalformedResponseError):
        await PerformanceManager(connection).get_disk_stats(hours=1)


async def test_smb_advanced_settings(files, console):
    console.reply("GET", f"{V1}/smb/advanced-settings", fx.smb_advanced(status="migrateFirstFailed"))

    settings = await files.get_smb_advanced_settings()

    assert settings.personal_drive_recycle_enabled is True
    assert settings.personal_drive_recycle_status == "migrateFirstFailed"
    assert not console.writes


async def test_rsync_settings_without_an_account(files, console):
    console.reply("GET", RSYNC, fx.rsync_settings())
    console.reply("GET", SYSTEMS_INFO, fx.systems_info(ssh_enabled=False))

    settings = (await files.get_rsync_settings()).model_dump()

    assert settings == {
        "enabled": False,
        "account_configured": False,
        "account_username": None,
        "ssh_enabled": False,
    }
    assert not console.writes


async def test_rsync_account_keeps_only_its_username(files, console):
    account = {"username": "synthetic-rsync", "password": "synthetic-secret-0123", "passwordHash": "x"}
    console.reply("GET", RSYNC, fx.rsync_settings(enabled=True, account=account))
    console.reply("GET", SYSTEMS_INFO, fx.systems_info(ssh_enabled=True))

    settings = await files.get_rsync_settings()

    assert (settings.enabled, settings.ssh_enabled) == (True, True)
    assert (settings.account_configured, settings.account_username) == (True, "synthetic-rsync")
    assert "synthetic-secret" not in str(settings.model_dump()) and "passwordHash" not in str(settings.model_dump())


async def test_rsync_answer_without_the_account_key_leaves_it_unknown(files, console):
    console.reply("GET", RSYNC, {"enable": True})
    console.reply("GET", SYSTEMS_INFO, fx.systems_info())

    settings = await files.get_rsync_settings()

    assert settings.account_configured is None


@pytest.mark.parametrize("path", ["smb", "rsync", "systems"])
async def test_unreadable_service_settings_are_an_error(files, console, path):
    console.reply("GET", f"{V1}/smb/advanced-settings", {"err": None, "type": "single", "data": "nope"})
    console.reply("GET", RSYNC, ["nope"] if path == "rsync" else fx.rsync_settings())
    console.reply(
        "GET", SYSTEMS_INFO, {"err": None, "type": "single", "data": None} if path == "systems" else fx.systems_info()
    )

    with pytest.raises(UniFiMalformedResponseError):
        if path == "smb":
            await files.get_smb_advanced_settings()
        else:
            await files.get_rsync_settings()


async def test_rsync_settings_missing_on_older_firmware_is_an_error(files, console):
    console.reply("GET", RSYNC, {"err": {"msg": "not found"}}, status=404)
    console.reply("GET", SYSTEMS_INFO, fx.systems_info())

    with pytest.raises(UniFiOperationError, match="no endpoint"):
        await files.get_rsync_settings()


# --- file service toggles -----------------------------------------------------


async def test_plan_does_not_write(files, console):
    _script_services(console)
    console.reply("GET", NFS_ADVANCED, fx.nfs_advanced())

    change = await files.plan_set_file_service("nfs", False)

    assert change.enabled_before is True and change.enabled_after is False
    assert any("connection(s) are kept" in w for w in change.warnings)
    assert console.writes == []


async def test_turning_smb_off_warns_that_time_machine_stays_off(files, console):
    _script_services(console)

    change = await files.plan_set_file_service("smb", False)

    assert any("turning SMB back on leaves it off" in w for w in change.warnings)


async def test_turning_smb_on_says_time_machine_is_still_off(files, console):
    _script_services(console, smb=False, time_machine=False)

    change = await files.plan_set_file_service("smb", True)

    assert any("Time Machine stays off" in w for w in change.warnings)


async def test_time_machine_needs_smb(files, console):
    _script_services(console, smb=False, time_machine=False)

    with pytest.raises(UniFiValidationError, match="Enable SMB first"):
        await files.plan_set_file_service("time_machine", True)


async def test_apply_toggle_writes_and_verifies(files, console):
    _script_services(console)
    change = await files.plan_set_file_service("smb", False)
    console.reply("PUT", f"{V1}/smb/settings", fx.service(False))
    console.reply("GET", f"{V1}/smb/settings", fx.service(False))

    assert await files.apply_set_file_service(change) is False

    (put,) = console.writes
    assert put.body == {"enable": False}


async def test_confirmed_toggle_plans_from_fresh_state_and_writes(files, console):
    _script_services(console)
    # The plan reads SMB as on; the read-back after the PUT reads it as off.
    console.reply("GET", f"{V1}/smb/settings", fx.service(True))
    console.reply("PUT", f"{V1}/smb/settings", fx.service(False))
    console.reply("GET", f"{V1}/smb/settings", fx.service(False))

    change, after = await files.set_file_service("smb", False)

    assert change.enabled_before is True and after is False
    (put,) = console.writes
    assert put.body == {"enable": False}


async def test_confirmed_toggle_already_in_state_sends_nothing(files, console):
    _script_services(console)

    change, after = await files.set_file_service("smb", True)

    assert change.changes_anything is False and after is True
    assert console.writes == []


async def test_apply_toggle_reports_a_change_that_did_not_stick(files, console):
    _script_services(console)
    change = await files.plan_set_file_service("smb", False)
    console.reply("PUT", f"{V1}/smb/settings", fx.service(False))

    with pytest.raises(UniFiOperationError, match="reading it back"):
        await files.apply_set_file_service(change)


# --- NFS read-modify-write ------------------------------------------------------


def _existing():
    return fx.nfs_advanced(
        fx.nfs_connection(fx.CLIENT, (fx.DRIVE_ID, "Shared_Drive", "rw")),
        {**fx.nfs_connection(fx.OTHER_CLIENT, (fx.OTHER_DRIVE_ID, "Media", "ro")), "futureOption": "kept"},
    )


async def test_add_keeps_every_other_client_and_drops_read_only_keys(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("GET", DRIVES, fx.drives())
    console.reply("GET", f"{V1}/nfs/settings", fx.service(True))
    new = NfsConnectionInput(
        client="nas-client.lan", shared_drives=[NfsSharedDriveAccess(id=fx.OTHER_DRIVE_ID, permission="ro")]
    )

    change = await files.plan_add_nfs_connection(new)

    assert console.writes == []
    assert change.unchanged_clients == [fx.CLIENT, fx.OTHER_CLIENT]
    assert change.after.shared_drives[0].export_path == "/var/nfs/shared/Media"
    first, second, added = change.connections
    assert first == {"client": fx.CLIENT, "async": False, "sharedDrives": [{"id": fx.DRIVE_ID, "permission": "rw"}]}
    assert second["futureOption"] == "kept" and "errorCodes" not in second
    assert added == {
        "client": "nas-client.lan",
        "async": False,
        "sharedDrives": [{"id": fx.OTHER_DRIVE_ID, "permission": "ro"}],
    }

    console.reply(
        "POST", TEST_HOSTNAMES, {"err": None, "type": "single", "data": {"hostnames": [{"hostname": "nas-client.lan"}]}}
    )
    console.reply("GET", NFS_ADVANCED, _existing())  # re-read just before the PATCH
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}})
    after = _existing()
    after["data"]["connections"].append(fx.nfs_connection("nas-client.lan", (fx.OTHER_DRIVE_ID, "Media", "ro")))
    console.reply("GET", NFS_ADVANCED, after)

    saved = await files.apply_nfs_change(change)

    assert saved.client == "nas-client.lan"
    check, put = console.writes
    assert check.body == {"hostnames": ["nas-client.lan"]}
    assert put.body == {"connections": change.connections}


async def test_add_refuses_a_duplicate_client(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    new = NfsConnectionInput(client=fx.CLIENT.upper(), shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])

    with pytest.raises(UniFiValidationError, match="already has a connection"):
        await files.plan_add_nfs_connection(new)


async def test_add_refuses_an_unknown_shared_drive(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("GET", DRIVES, fx.drives())
    new = NfsConnectionInput(client="192.0.2.99", shared_drives=[NfsSharedDriveAccess(id="no-such-drive")])

    with pytest.raises(UniFiValidationError, match="Unknown shared drive"):
        await files.plan_add_nfs_connection(new)


async def test_flagged_hostname_stops_the_write(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("GET", DRIVES, fx.drives())
    console.reply("GET", f"{V1}/nfs/settings", fx.service(True))
    change = await files.plan_add_nfs_connection(
        NfsConnectionInput(client="unknown.lan", shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])
    )
    console.reply(
        "POST",
        TEST_HOSTNAMES,
        {
            "err": None,
            "type": "single",
            "data": {"hostnames": [{"hostname": "unknown.lan", "errorCode": "UNRESOLVABLE"}]},
        },
    )

    with pytest.raises(UniFiValidationError, match="UNRESOLVABLE"):
        await files.apply_nfs_change(change)

    assert [w.path for w in console.writes] == [TEST_HOSTNAMES]


async def test_update_merges_only_the_passed_fields(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("GET", DRIVES, fx.drives())
    console.reply("GET", f"{V1}/nfs/settings", fx.service(True))

    change = await files.plan_update_nfs_connection(fx.OTHER_CLIENT, async_writes=True)

    edited = change.connections[1]
    assert edited == {
        "client": fx.OTHER_CLIENT,
        "async": True,
        "sharedDrives": [{"id": fx.OTHER_DRIVE_ID, "permission": "ro"}],
        "futureOption": "kept",
    }
    assert change.connections[0]["client"] == fx.CLIENT
    assert any("power loss" in w for w in change.warnings)
    assert console.writes == []


async def test_update_requires_a_field_and_an_existing_client(files, console):
    with pytest.raises(UniFiValidationError, match="Nothing to update"):
        await files.plan_update_nfs_connection(fx.CLIENT)

    console.reply("GET", NFS_ADVANCED, _existing())
    with pytest.raises(UniFiNotFoundError):
        await files.plan_update_nfs_connection("192.0.2.200", async_writes=True)


async def test_update_refuses_an_empty_drive_list(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())

    with pytest.raises(UniFiValidationError, match="shared_drives"):
        await files.plan_update_nfs_connection(fx.CLIENT, shared_drives=[])


async def test_remove_sends_the_others_and_verifies_it_is_gone(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())

    change = await files.plan_remove_nfs_connection(fx.CLIENT)

    assert [c["client"] for c in change.connections] == [fx.OTHER_CLIENT]
    assert "/var/nfs/shared/Shared_Drive" in change.warnings[0]

    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}})
    console.reply(
        "GET", NFS_ADVANCED, fx.nfs_advanced(fx.nfs_connection(fx.OTHER_CLIENT, (fx.OTHER_DRIVE_ID, "Media", "ro")))
    )

    assert await files.apply_nfs_change(change) is None
    # Removal does not run the hostname check.
    assert [w.path for w in console.writes] == [NFS_ADVANCED]


async def test_write_that_drops_another_client_is_reported(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    change = await files.plan_remove_nfs_connection(fx.CLIENT)
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}})
    console.reply("GET", NFS_ADVANCED, fx.nfs_advanced(fx.nfs_connection("192.0.2.1")))

    with pytest.raises(UniFiOperationError, match=fx.OTHER_CLIENT):
        await files.apply_nfs_change(change)


@pytest.mark.parametrize(
    "client",
    ["", " ", "* (rw,no_root_squash)", "host,other", "a" * 254, "host\nother", ":: (rw)", "fe80::1%eth0", "-o"],
)
def test_client_values_that_could_carry_export_options_are_refused(client):
    with pytest.raises(ValueError):
        NfsConnectionInput(client=client, shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])


@pytest.mark.parametrize(
    "client", ["192.0.2.5", "192.0.2.0/24", "nas-client.lan", "*.lan", "2001:db8::1", "::1", "::ffff:192.0.2.5"]
)
def test_ordinary_client_values_are_accepted(client):
    assert NfsConnectionInput(client=client, shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)]).client == client


def test_listed_grant_round_trips_into_an_input():
    grant = NfsSharedDriveAccess(
        id=fx.DRIVE_ID, permission="ro", name="Shared_Drive", status="active", export_path="/var/nfs/shared/x"
    )
    assert grant.to_controller() == {"id": fx.DRIVE_ID, "permission": "ro"}
    with pytest.raises(ValueError):
        NfsSharedDriveAccess(id=fx.DRIVE_ID, permission="rw", squash="all")


@pytest.mark.parametrize(
    ("client", "world"),
    [
        ("*", True),
        ("*.*", True),
        ("0.0.0.0/0", True),
        ("::/0", True),
        ("0/0", True),
        ("192.0.2.1/00", True),
        ("*.lan", False),
        ("192.0.2.0/24", False),
        ("10/8", False),
    ],
)
def test_world_clients_are_recognized(client, world):
    assert is_world_client(client) is world


def test_mutable_fields_are_the_input_fields():
    assert MUTABLE_FIELDS | READ_ONLY_FIELDS == set(NfsConnectionInput.model_fields)
    assert MUTABLE_FIELDS | READ_ONLY_FIELDS == set(NfsConnection.model_fields)
    assert not MUTABLE_FIELDS & READ_ONLY_FIELDS


# --- review follow-ups: warnings, merges, and write paths -----------------------


def _script_add_lookups(console):
    console.reply("GET", DRIVES, fx.drives(), always=True)
    console.reply("GET", f"{V1}/nfs/settings", fx.service(True), always=True)
    console.reply("POST", TEST_HOSTNAMES, {"err": None, "type": "single", "data": {"hostnames": []}}, always=True)


async def test_world_mountable_client_is_warned_about(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    _script_add_lookups(console)

    change = await files.plan_add_nfs_connection(
        NfsConnectionInput(client="*", shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])
    )

    assert any("matches every host" in w for w in change.warnings)


async def test_enabling_nfs_lists_the_clients_that_can_mount_again(files, console):
    _script_services(console, nfs=False)
    console.reply("GET", NFS_ADVANCED, _existing())

    change = await files.plan_set_file_service("nfs", True)

    (regain,) = [w for w in change.warnings if "can mount again" in w]
    assert f"{fx.CLIENT} (Shared_Drive rw)" in regain and f"{fx.OTHER_CLIENT} (Media ro)" in regain
    assert console.writes == []


async def test_update_keeps_the_permission_when_omitted(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    _script_add_lookups(console)

    change = await files.plan_update_nfs_connection(
        fx.OTHER_CLIENT,
        shared_drives=[NfsSharedDriveAccess(id=fx.OTHER_DRIVE_ID), NfsSharedDriveAccess(id=fx.DRIVE_ID)],
    )

    # The drive it already had stays ro; only the newly granted one defaults to rw.
    assert change.connections[1]["sharedDrives"] == [
        {"id": fx.OTHER_DRIVE_ID, "permission": "ro"},
        {"id": fx.DRIVE_ID, "permission": "rw"},
    ]
    assert not any("power loss" in w for w in change.warnings)


async def test_update_keeps_unknown_grant_keys_on_the_edited_client(files, console):
    existing = _existing()
    existing["data"]["connections"][1]["sharedDrives"][0]["futureGrantOption"] = "kept"
    console.reply("GET", NFS_ADVANCED, existing)
    _script_add_lookups(console)

    change = await files.plan_update_nfs_connection(fx.OTHER_CLIENT, async_writes=True)

    assert change.connections[1]["sharedDrives"] == [
        {"id": fx.OTHER_DRIVE_ID, "permission": "ro", "futureGrantOption": "kept"}
    ]


def _with_other_async(async_writes):
    return fx.nfs_advanced(
        fx.nfs_connection(fx.CLIENT, (fx.DRIVE_ID, "Shared_Drive", "rw")),
        {
            **fx.nfs_connection(fx.OTHER_CLIENT, (fx.OTHER_DRIVE_ID, "Media", "ro"), async_writes=async_writes),
            "futureOption": "kept",
        },
    )


def _as_current_firmware_reads_it(body):
    """An ``nfs/advanced-settings`` body as Drive 4.6 answers it: other settings, and error codes per grant."""
    body["data"].update({"domainName": "", "maxProtocolVersion": "3", "security": "AUTH_SYS"})
    for connection in body["data"]["connections"]:
        for grant in connection["sharedDrives"]:
            grant["errorCodes"] = []
    return body


async def test_an_nfs_change_is_a_patch_of_the_list_alone(files, console):
    _script_add_lookups(console)
    console.reply("GET", NFS_ADVANCED, _as_current_firmware_reads_it(_existing()))  # plan
    console.reply("GET", NFS_ADVANCED, _as_current_firmware_reads_it(_existing()))  # re-read before the PATCH
    console.reply("PATCH", NFS_ADVANCED, "OK")
    after = _existing()
    after["data"]["connections"].append(fx.nfs_connection("192.0.2.101", (fx.DRIVE_ID, "Shared_Drive", "ro")))
    console.reply("GET", NFS_ADVANCED, _as_current_firmware_reads_it(after))

    _, saved = await files.add_nfs_connection(
        NfsConnectionInput(client="192.0.2.101", shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID, permission="ro")])
    )

    assert saved.client == "192.0.2.101"
    assert console.calls("PUT") == []
    (patch,) = console.calls("PATCH", NFS_ADVANCED)
    # Only the list, each grant as id and permission: Drive keeps domainName, maxProtocolVersion
    # and security, and the read-only keys it adds on read are not sent back.
    assert patch.body == {
        "connections": [
            {"client": fx.CLIENT, "async": False, "sharedDrives": [{"id": fx.DRIVE_ID, "permission": "rw"}]},
            {
                "client": fx.OTHER_CLIENT,
                "async": False,
                "sharedDrives": [{"id": fx.OTHER_DRIVE_ID, "permission": "ro"}],
                "futureOption": "kept",
            },
            {"client": "192.0.2.101", "async": False, "sharedDrives": [{"id": fx.DRIVE_ID, "permission": "ro"}]},
        ]
    }


async def test_a_personal_drive_cannot_be_granted_over_nfs(files, console):
    personal = fx.drives()
    personal["drives"][0]["type"] = "personal"
    console.reply("GET", DRIVES, personal, always=True)
    console.reply("GET", NFS_ADVANCED, _existing())

    with pytest.raises(UniFiValidationError, match="only export shared drives"):
        await files.plan_add_nfs_connection(
            NfsConnectionInput(client="192.0.2.101", shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])
        )

    assert console.writes == []


async def test_update_writes_and_reads_back(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())  # plan
    _script_add_lookups(console)
    console.reply("GET", NFS_ADVANCED, _existing())  # re-read before the PATCH
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}})
    console.reply("GET", NFS_ADVANCED, _with_other_async(True))  # read back

    change, saved = await files.update_nfs_connection(fx.OTHER_CLIENT, async_writes=True)

    assert saved.client == fx.OTHER_CLIENT and saved.async_writes is True
    put = console.calls("PATCH", NFS_ADVANCED)[0]
    assert put.body == {"connections": change.connections}
    assert put.body["connections"][1]["async"] is True


async def test_update_that_reads_back_differently_is_reported(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    _script_add_lookups(console)
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}})
    console.reply("GET", NFS_ADVANCED, _with_other_async(False))

    with pytest.raises(UniFiOperationError, match="does not match"):
        await files.update_nfs_connection(fx.OTHER_CLIENT, async_writes=True)


async def test_removed_client_still_listed_is_reported(files, console):
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("GET", NFS_ADVANCED, _existing())
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}})
    console.reply("GET", NFS_ADVANCED, _existing())

    with pytest.raises(UniFiOperationError, match="still listed"):
        await files.remove_nfs_connection(fx.CLIENT)


async def test_concurrent_adds_through_the_operation_gate_both_land(files, console):
    _script_add_lookups(console)
    first = fx.nfs_connection("192.0.2.101", (fx.DRIVE_ID, "Shared_Drive", "rw"))
    second = fx.nfs_connection("192.0.2.102", (fx.DRIVE_ID, "Shared_Drive", "rw"))
    with_first = _existing()
    with_first["data"]["connections"].append(first)
    with_both = _existing()
    with_both["data"]["connections"].extend([first, second])
    # The operation gate runs the two writes one after the other, so the replies are in order:
    # plan, re-read and read back for the first add, then the same for the second.
    for body in (_existing(), _existing(), with_first, with_first, with_first, with_both):
        console.reply("GET", NFS_ADVANCED, body)
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}}, always=True)

    gate = OperationGate(GateSettings(), name="drive-test")

    async def add(client: str):
        async with gate.write():
            return await files.add_nfs_connection(
                NfsConnectionInput(client=client, shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])
            )

    results = await asyncio.gather(add("192.0.2.101"), add("192.0.2.102"))

    assert [saved.client for _, saved in results] == ["192.0.2.101", "192.0.2.102"]
    first_put, second_put = console.calls("PATCH", NFS_ADVANCED)
    assert [c["client"] for c in first_put.body["connections"]] == [fx.CLIENT, fx.OTHER_CLIENT, "192.0.2.101"]
    assert [c["client"] for c in second_put.body["connections"]] == [
        fx.CLIENT,
        fx.OTHER_CLIENT,
        "192.0.2.101",
        "192.0.2.102",
    ]


@pytest.fixture
async def impatient_files(console):
    """File services on a client whose own request timeout is far shorter than the console's slow replies."""
    connection = DriveConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url, timeout_seconds=0.2)
    yield FileServiceManager(connection, SharedDriveManager(connection))
    await connection.close()


def _add_client():
    return NfsConnectionInput(client="192.0.2.101", shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])


async def test_an_unanswered_hostname_check_means_nothing_was_changed(impatient_files, console):
    console.reply("GET", DRIVES, fx.drives(), always=True)
    console.reply("GET", f"{V1}/nfs/settings", fx.service(True), always=True)
    console.reply("GET", NFS_ADVANCED, _existing(), always=True)
    console.reply("POST", TEST_HOSTNAMES, {"err": None, "type": "single", "data": {"hostnames": []}}, delay=1)

    with pytest.raises(DriveWriteNotSent, match="nothing was changed"):
        await impatient_files.add_nfs_connection(_add_client())

    assert console.calls("PATCH", NFS_ADVANCED) == []


async def test_an_unanswered_nfs_put_has_an_unknown_outcome(impatient_files, console):
    _script_add_lookups(console)
    console.reply("GET", NFS_ADVANCED, _existing(), always=True)
    console.reply("PATCH", NFS_ADVANCED, {"err": None, "type": "single", "data": {}}, delay=1)

    with pytest.raises(DriveWriteOutcomeUnknown, match="whether it was applied is unknown"):
        await impatient_files.add_nfs_connection(_add_client())

    assert len(console.calls("PATCH", NFS_ADVANCED)) == 1


async def test_plan_from_a_list_that_changed_is_not_written(files, console):
    _script_add_lookups(console)
    console.reply("GET", NFS_ADVANCED, _existing())
    change = await files.plan_add_nfs_connection(
        NfsConnectionInput(client="192.0.2.101", shared_drives=[NfsSharedDriveAccess(id=fx.DRIVE_ID)])
    )
    # Someone else added a client between the plan and the write.
    changed = _existing()
    changed["data"]["connections"].append(fx.nfs_connection("192.0.2.150", (fx.DRIVE_ID, "Shared_Drive", "ro")))
    console.reply("GET", NFS_ADVANCED, changed)

    with pytest.raises(UniFiOperationError, match="changed since this change was planned"):
        await files.apply_nfs_change(change)

    assert console.calls("PATCH", NFS_ADVANCED) == []


def test_listed_connection_round_trips_into_an_input():
    listed = nfs_connection_from_api(
        {**fx.nfs_connection(fx.CLIENT, (fx.DRIVE_ID, "Shared_Drive", "ro")), "errorCodes": ["UNRESOLVABLE"]}
    ).model_dump(exclude_none=True)

    connection = NfsConnectionInput(**listed)

    assert connection_to_controller(connection) == {
        "client": fx.CLIENT,
        "async": False,
        "sharedDrives": [{"id": fx.DRIVE_ID, "permission": "ro"}],
    }
