"""UniFi Drive on the API: REST reads, GraphQL, catalog actions and preview-first writes.

The NAS is a stand-in behind the real ``DriveConnectionManager`` (see
``tests/drive_data.py``), so the core managers, their read-backs and the
write-outcome errors all run. A preview never reaches a manager; a confirmed
write reports ``mutation_applied`` false when nothing was sent and null when
the change was sent without an answer, never a success.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from unifi_api.db.models import AuditLog
from unifi_api.services.managers import ControllerInitializationFailed
from unifi_core.drive.managers.connection_manager import DriveConnectionManager
from unifi_core.exceptions import UniFiConnectionError

from tests.drive_data import (
    BIG_CAPACITY,
    CLIENT,
    DRIVE_ID,
    GROUP_ID,
    HOSTNAME_CHECK,
    LOG_CURSOR,
    MISSING_DRIVE_ID,
    NAS_HOST,
    NEW_CLIENT,
    NFS_SETTINGS,
    OTHER_CLIENT,
    OTHER_DRIVE_ID,
    PERSONAL_DRIVE_ID,
    POOL_ID,
    RSYNC_PASSWORD,
    USER_ID,
    V1,
    V2,
    FakeDrive,
    bootstrap,
    drive_cm,
    install,
    transport_failure,
)
from tests.innerspace_data import client, credentials, graphql

BASE = "/v1/sites/default/drive"


@pytest.fixture(autouse=True)
def _db_key(monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    monkeypatch.delenv("UNIFI_DRIVE_READ_ONLY", raising=False)
    monkeypatch.delenv("UNIFI_READ_ONLY", raising=False)


async def _app(tmp_path, nas: FakeDrive | None = None, **kwargs):
    app, key, cid = await bootstrap(tmp_path, **kwargs)
    if nas is not None:
        install(app, cid, drive_cm(nas))
    return app, {"Authorization": f"Bearer {key}"}, key, cid


async def _get(app, headers, path, **params):
    async with client(app) as c:
        return await c.get(path, headers=headers, params=params)


async def _action(app, headers, cid, tool, args, *, confirm=False, status=200):
    async with client(app) as c:
        response = await c.post(
            f"/v1/actions/{tool}",
            headers=headers,
            json={"site": "default", "controller": cid, "args": args, "confirm": confirm},
        )
    assert response.status_code == status, response.text
    return response.json()


async def _audit(app) -> list[AuditLog]:
    async with app.state.sessionmaker() as session:
        return list((await session.execute(select(AuditLog))).scalars().all())


# ---------------------------------------------------------------------------
# REST reads, one per tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rest_system_info_keeps_only_the_declared_fields(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    response = await _get(app, headers, f"{BASE}/system")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["model"] == "UniFi Network Attached Storage Pro 8"
    assert data["firmware_update_available"] == "5.0.17"
    # The Drive application's own version, apart from UniFi OS's.
    assert (data["drive_version"], data["drive_update_available"]) == ("4.4.31", "4.5.7")
    assert data["memory_total_kb"] == 16639296
    # /api/system's public IP is not a declared field and never leaves the API.
    assert "198.51.100.1" not in response.text


@pytest.mark.asyncio
async def test_rest_storage_pools_and_disks(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    pools = await _get(app, headers, f"{BASE}/storage-pools")
    disks = await _get(app, headers, f"{BASE}/disks")
    every_bay = await _get(app, headers, f"{BASE}/disks", include_empty="true", include_cache="false")

    assert pools.status_code == 200, pools.text
    [pool] = pools.json()["items"]
    assert (pool["id"], pool["capacity_bytes"]) == (POOL_ID, BIG_CAPACITY)
    assert pool["raid_groups"][0]["current_level"] == "raid1"
    assert pools.json()["render_hint"]["kind"] == "list"
    assert [(d["slot_id"], d["bay_type"]) for d in disks.json()["items"]] == [("1", "disk")]
    assert [(d["slot_id"], d["bay_type"]) for d in every_bay.json()["items"]] == [("1", "disk"), ("2", "disk")]


@pytest.mark.asyncio
async def test_rest_shared_drives_and_one_drive_ignore_the_path_site(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    listed = await _get(app, headers, "/v1/sites/not-a-drive-site/drive/shared-drives")
    one = await _get(app, headers, f"{BASE}/shared-drives/{DRIVE_ID}")

    assert listed.status_code == 200, listed.text
    assert [d["id"] for d in listed.json()["items"]] == [DRIVE_ID, OTHER_DRIVE_ID, PERSONAL_DRIVE_ID]
    assert one.status_code == 200, one.text
    assert one.json()["data"]["name"] == "Shared_Drive"
    assert one.json()["data"]["member_count"] is None


@pytest.mark.asyncio
async def test_rest_file_services_and_nfs_connections(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    services = await _get(app, headers, f"{BASE}/file-services")
    nfs = await _get(app, headers, f"{BASE}/nfs-connections")

    assert services.status_code == 200, services.text
    data = services.json()["data"]
    assert (data["smb_enabled"], data["nfs_enabled"], data["time_machine_enabled"]) == (True, True, False)
    assert data["network_interfaces"][0]["name"] == "enp0s0"
    assert nfs.status_code == 200, nfs.text
    first = nfs.json()["items"][0]
    assert first["client"] == CLIENT
    assert first["shared_drives"][0]["export_path"] == "/var/nfs/shared/Shared_Drive"


@pytest.mark.asyncio
async def test_rest_missing_shared_drive_is_a_fixed_text_404(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    response = await _get(app, headers, f"{BASE}/shared-drives/{MISSING_DRIVE_ID}")

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == {
        "kind": "drive_not_found",
        "message": "Failed to get Drive shared drive: not found.",
    }
    assert MISSING_DRIVE_ID not in response.text


@pytest.mark.asyncio
async def test_rest_rejected_login_is_a_502_without_the_nas_address(tmp_path):
    nas = FakeDrive(login_status=401)
    app, headers, _key, _cid = await _app(tmp_path, nas)

    response = await _get(app, headers, f"{BASE}/system")

    assert response.status_code == 502, response.text
    assert response.json()["detail"]["kind"] == "drive_upstream_error"
    assert "rejected the configured username/password" in response.json()["detail"]["message"]
    assert NAS_HOST not in response.text


@pytest.mark.asyncio
async def test_rest_forbidden_is_403(tmp_path):
    nas = FakeDrive(faults={("GET", "/proxy/drive/api/v2/storage"): 403})
    app, headers, _key, _cid = await _app(tmp_path, nas)

    response = await _get(app, headers, f"{BASE}/storage-pools")

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["kind"] == "drive_forbidden"


@pytest.mark.asyncio
async def test_rest_controller_without_drive_is_a_capability_mismatch(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, products="network")

    response = await _get(app, headers, f"{BASE}/system")

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["missing_product"] == "drive"


def _sent(nas: FakeDrive, prefix: str) -> list[str]:
    return [path for method, path, _body in nas.requests if method == "GET" and path.startswith(prefix)]


@pytest.mark.asyncio
async def test_rest_logs_are_one_page_with_a_cursor_and_the_filters_reach_drive(tmp_path):
    nas = FakeDrive()
    app, headers, _key, _cid = await _app(tmp_path, nas)

    first = await _get(
        app, headers, f"{BASE}/logs", category="storage", severities=["very_high", "low"], keyword="Bay", limit=2
    )
    cursor = first.json()["data"]["next_cursor"]
    last = await _get(app, headers, f"{BASE}/logs", category="storage", cursor=cursor)

    assert first.status_code == 200, first.text
    page = first.json()["data"]
    assert [entry["title"] for entry in page["entries"]] == ["Storage Pool Array at Risk", "Drive Inserted"]
    assert page["entries"][0]["message"] == "Storage Pool 1 is degraded. Bay 3 is showing pre-failure indicators."
    # The cursor is named next_cursor: a key holding "token" would be masked by redaction and break paging.
    assert cursor == LOG_CURSOR
    assert first.json()["render_hint"]["kind"] == "detail"
    assert last.json()["data"]["next_cursor"] is None
    sent_first, sent_last = _sent(nas, f"{V2}/systems/logs")
    # The category becomes its types; the cursor goes back as Drive's nextToken.
    assert "types=storagePool%2Cdrive" in sent_first and "severities=very_high%2Clow" in sent_first
    assert "keywords=Bay" in sent_first and "limit=2" in sent_first
    assert f"nextToken={LOG_CURSOR}" in sent_last


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "reaches_drive"),
    [
        ({"category": "no-such-category"}, True),
        ({"types": ["no-such-type"]}, True),
        ({"scope": "everything"}, False),
        ({"limit": 501}, False),
        ({"after": "yesterday"}, False),
        ({"after": "2026-11-20T00:00:00Z", "before": "2026-11-19T00:00:00Z"}, False),
    ],
)
async def test_rest_invalid_log_filters_are_a_fixed_text_422(tmp_path, params, reaches_drive):
    nas = FakeDrive()
    app, headers, _key, _cid = await _app(tmp_path, nas)

    response = await _get(app, headers, f"{BASE}/logs", **params)

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == {
        "kind": "invalid_drive_request",
        "message": "Failed to list Drive system log entries: invalid arguments.",
    }
    for value in params.values():
        assert str(value) not in response.text
    # A filter the query refuses is never sent; a category or type is checked against Drive's own definitions.
    assert _sent(nas, f"{V2}/systems/logs") == []
    assert bool(_sent(nas, f"{V2}/systems/log-definitions")) is reaches_drive


@pytest.mark.asyncio
async def test_rest_storage_usage_splits_the_used_space(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    response = await _get(app, headers, f"{BASE}/storage-usage")

    assert response.status_code == 200, response.text
    [pool] = response.json()["items"]
    assert (pool["pool_id"], pool["capacity_bytes"]) == (POOL_ID, BIG_CAPACITY)
    assert pool["shared_drives_bytes"] == 10825012379648
    # Used space minus the parts Drive names: system and other data.
    assert pool["system_bytes"] == 10826060070912 - 10825012379648
    assert response.json()["render_hint"]["primary_key"] == "pool_id"


@pytest.mark.asyncio
async def test_rest_throughput_and_fan_profile(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    throughput = await _get(app, headers, f"{BASE}/network-throughput")
    fan = await _get(app, headers, f"{BASE}/fan-profile")

    assert throughput.status_code == 200, throughput.text
    assert throughput.json()["data"] == {
        "receive_kbps": 6.32,
        "transmit_kbps": 17.45,
        "timestamp": "2026-01-02T03:04:05.123456789-05:00",
    }
    assert fan.status_code == 200, fan.text
    assert (fan.json()["data"]["current_profile"], fan.json()["data"]["current_label"]) == ("default", "Balanced")
    assert fan.json()["data"]["available_profiles"][0] == {"profile": "cooling", "label": "Cooling"}


@pytest.mark.asyncio
async def test_rest_disk_stats_leave_the_samples_out_unless_asked(tmp_path):
    nas = FakeDrive()
    app, headers, _key, _cid = await _app(tmp_path, nas)

    summary = await _get(app, headers, f"{BASE}/disk-stats", hours=6)
    with_samples = await _get(app, headers, f"{BASE}/disk-stats", include_samples="true")

    assert summary.status_code == 200, summary.text
    data = summary.json()["data"]
    assert (data["interval_seconds"], data["sample_count"]) == (900, 2)
    bay, cache = data["disks"]
    assert (bay["slot_id"], bay["bay_type"], bay["read_kbps_avg"], bay["temperature_c_max"]) == (
        "1",
        "disk",
        200.38,
        36,
    )
    assert bay["bad_sector_count_increase"] == 2
    assert (cache["bay_type"], cache["samples_with_data"]) == ("cache", 0)
    assert bay["samples"] is None and cache["samples"] is None
    assert [sample["write_kbps"] for sample in with_samples.json()["data"]["disks"][0]["samples"]] == [0, 50]
    # The window is the last six hours, in 15-minute buckets.
    start, end = (int(part.split("=")[1]) for part in _sent(nas, f"{V2}/systems/disk-stats")[0].split("&")[:2])
    assert end - start == 6 * 3600


@pytest.mark.asyncio
@pytest.mark.parametrize("hours", [0, 2161])
async def test_rest_disk_stats_window_out_of_range_is_a_422_before_any_request(tmp_path, hours):
    nas = FakeDrive()
    app, headers, _key, _cid = await _app(tmp_path, nas)

    response = await _get(app, headers, f"{BASE}/disk-stats", hours=hours)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["message"] == "Failed to get Drive disk stats: invalid arguments."
    assert _sent(nas, f"{V2}/systems/disk-stats") == []


@pytest.mark.asyncio
async def test_rest_snapshot_overview_and_one_shared_drives_snapshots(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    overview = await _get(app, headers, f"{BASE}/snapshot-overview")
    listed = await _get(app, headers, f"{BASE}/snapshots/shared/Media")
    none = await _get(app, headers, f"{BASE}/snapshots/shared/Shared_Drive")

    assert overview.status_code == 200, overview.text
    [shared] = overview.json()["data"]["shared_drives"]
    assert (shared["shared_drive_id"], shared["shared_drive_name"]) == (OTHER_DRIVE_ID, "Media")
    assert (shared["configured"], shared["snapshot_limit"], shared["paused"]) == (False, 0, True)
    [personal] = overview.json()["data"]["personal_drives"]
    assert (personal["user_id"], personal["coverage_bytes"], personal["locked_count"]) == (USER_ID, BIG_CAPACITY, 1)
    # The owner's name is not a declared field.
    assert "Synthetic" not in overview.text
    assert listed.status_code == 200, listed.text
    assert [(snap["id"], snap["locked"]) for snap in listed.json()["items"]] == [("snap-2", True), ("snap-1", False)]
    assert listed.json()["render_hint"]["primary_key"] == "id"
    assert none.json()["items"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "status", "message"),
    [
        ("Missing", 404, "Failed to list Drive snapshots: not found."),
        ("a..b", 422, "Failed to list Drive snapshots: invalid arguments."),
    ],
)
async def test_rest_snapshots_of_a_missing_or_invalid_name_are_fixed_text(tmp_path, name, status, message):
    nas = FakeDrive()
    app, headers, _key, _cid = await _app(tmp_path, nas)

    response = await _get(app, headers, f"{BASE}/snapshots/shared/{name}")

    assert response.status_code == status, response.text
    assert response.json()["detail"]["message"] == message
    assert name not in response.text
    if status == 422:
        assert _sent(nas, f"{V1}/snapshots") == []


@pytest.mark.asyncio
async def test_rest_smb_advanced_and_rsync_settings_never_carry_the_rsync_password(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    smb = await _get(app, headers, f"{BASE}/smb-advanced-settings")
    rsync = await _get(app, headers, f"{BASE}/rsync-settings")

    assert smb.status_code == 200, smb.text
    assert smb.json()["data"] == {"personal_drive_recycle_enabled": True, "personal_drive_recycle_status": "optimal"}
    assert rsync.status_code == 200, rsync.text
    assert rsync.json()["data"] == {
        "enabled": True,
        "account_configured": True,
        "account_username": "backup",
        "ssh_enabled": False,
    }
    assert RSYNC_PASSWORD not in rsync.text


@pytest.mark.asyncio
async def test_rest_users_and_groups(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path, FakeDrive())

    users = await _get(app, headers, f"{BASE}/users")
    groups = await _get(app, headers, f"{BASE}/groups")

    assert users.status_code == 200, users.text
    owner, member = users.json()["items"]
    assert (owner["id"], owner["access_level"], owner["roles"], owner["email"]) == (
        USER_ID,
        "owner",
        ["owner"],
        "owner@example.com",
    )
    assert (member["access_level"], member["status"], member["email"], member["last_login"]) == (
        "user",
        "deactivated",
        None,
        None,
    )
    # Avatar URLs and SSO identifiers are not declared fields.
    assert "avatar" not in users.text and "sso-synthetic" not in users.text
    assert groups.status_code == 200, groups.text
    assert groups.json()["items"] == [{"id": GROUP_ID, "name": "Family"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/logs",
        "/storage-usage",
        "/network-throughput",
        "/fan-profile",
        "/disk-stats",
        "/snapshot-overview",
        "/snapshots/shared/Media",
        "/smb-advanced-settings",
        "/rsync-settings",
        "/users",
        "/groups",
    ],
)
async def test_rest_new_reads_need_a_drive_controller_and_map_a_rejected_login(tmp_path, path):
    network_app, network_headers, _key, _cid = await _app(tmp_path / "network", products="network")
    refused_app, refused_headers, _key, _cid = await _app(tmp_path / "refused", FakeDrive(login_status=401))

    mismatch = await _get(network_app, network_headers, f"{BASE}{path}")
    refused = await _get(refused_app, refused_headers, f"{BASE}{path}")

    assert mismatch.status_code == 409, mismatch.text
    assert mismatch.json()["detail"]["missing_product"] == "drive"
    assert refused.status_code == 502, refused.text
    assert refused.json()["detail"]["kind"] == "drive_upstream_error"
    assert NAS_HOST not in refused.text


@pytest.mark.asyncio
async def test_rest_refused_user_list_is_403(tmp_path):
    nas = FakeDrive(faults={("GET", f"{V1}/users?type=detail"): 403})
    app, headers, _key, _cid = await _app(tmp_path, nas)

    response = await _get(app, headers, f"{BASE}/users")

    assert response.status_code == 403, response.text
    assert response.json()["detail"]["kind"] == "drive_forbidden"


# ---------------------------------------------------------------------------
# GraphQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graphql_maps_a_missing_drive_to_not_found(tmp_path):
    app, _headers, key, cid = await _app(tmp_path, FakeDrive())

    body = await graphql(
        app, key, f'{{ drive {{ sharedDrive(controller: "{cid}", driveId: "{MISSING_DRIVE_ID}") {{ name }} }} }}'
    )

    assert body["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    assert MISSING_DRIVE_ID not in json.dumps(body)


@pytest.mark.asyncio
async def test_graphql_maps_a_missing_snapshot_drive_and_an_invalid_log_filter(tmp_path):
    app, _headers, key, cid = await _app(tmp_path, FakeDrive())

    missing = await graphql(
        app, key, f'{{ drive {{ snapshots(controller: "{cid}", sharedDriveName: "Missing") {{ id }} }} }}'
    )
    invalid = await graphql(
        app, key, f'{{ drive {{ logs(controller: "{cid}", scope: "everything") {{ nextCursor }} }} }}'
    )
    window = await graphql(app, key, f'{{ drive {{ diskStats(controller: "{cid}", hours: 0) {{ sampleCount }} }} }}')

    assert missing["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    assert "Missing" not in json.dumps(missing)
    assert invalid["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
    assert "everything" not in json.dumps(invalid)
    assert window["errors"][0]["extensions"]["code"] == "BAD_REQUEST"


# ---------------------------------------------------------------------------
# Actions: reads, previews and confirmed writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_actions_use_the_read_projections(tmp_path):
    app, headers, _key, cid = await _app(tmp_path, FakeDrive())

    system = await _action(app, headers, cid, "drive_get_system_info", {})
    pools = await _action(app, headers, cid, "drive_list_storage_pools", {})
    disks = await _action(app, headers, cid, "drive_list_disks", {"include_cache": False})

    assert (system["data"]["drive_version"], system["data"]["drive_update_available"]) == ("4.4.31", "4.5.7")
    assert system["data"]["firmware_version"] == "5.0.12"
    assert pools["success"] is True
    assert pools["data"][0]["capacity_bytes"] == BIG_CAPACITY
    assert pools["render_hint"]["kind"] == "list"
    assert [d["bay_type"] for d in disks["data"]] == ["disk"]


@pytest.mark.asyncio
async def test_new_read_actions_answer_as_their_routes_do(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    logs = await _action(app, headers, cid, "drive_list_logs", {"types": ["drive"], "limit": 5})
    summary = await _action(app, headers, cid, "drive_get_disk_stats", {"hours": 6})
    samples = await _action(app, headers, cid, "drive_get_disk_stats", {"include_samples": True})
    snapshots = await _action(app, headers, cid, "drive_list_snapshots", {"shared_drive_name": "Media"})
    usage = await _action(app, headers, cid, "drive_get_storage_usage", {})
    fan = await _action(app, headers, cid, "drive_get_fan_profile", {})
    overview = await _action(app, headers, cid, "drive_get_snapshot_overview", {})
    rsync = await _action(app, headers, cid, "drive_get_rsync_settings", {})
    users = await _action(app, headers, cid, "drive_list_users", {})
    groups = await _action(app, headers, cid, "drive_list_groups", {})

    assert logs["success"] is True, logs
    assert logs["data"]["next_cursor"] == LOG_CURSOR
    assert logs["data"]["entries"][0]["event"] == "StoragePoolArrayAtRiskSingle"
    assert "types=drive" in _sent(nas, f"{V2}/systems/logs")[0]
    # Samples only when asked for, as the route and the Drive MCP tool answer.
    assert all(disk["samples"] is None for disk in summary["data"]["disks"])
    assert len(samples["data"]["disks"][0]["samples"]) == 2
    first_window, default_window = _sent(nas, f"{V2}/systems/disk-stats")
    assert "interval=900" in first_window and "interval=900" in default_window
    assert [snap["id"] for snap in snapshots["data"]] == ["snap-2", "snap-1"]
    assert snapshots["render_hint"]["primary_key"] == "id"
    assert usage["data"][0]["capacity_bytes"] == BIG_CAPACITY
    assert fan["data"]["current_label"] == "Balanced"
    assert overview["data"]["shared_drives"][0]["shared_drive_name"] == "Media"
    assert rsync["data"]["account_username"] == "backup"
    assert RSYNC_PASSWORD not in json.dumps(rsync)
    assert [user["id"] for user in users["data"]][0] == USER_ID
    assert groups["data"] == [{"id": GROUP_ID, "name": "Family"}]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            ControllerInitializationFailed("Failed to initialize drive controller connection: no login set."),
            "Failed to list Drive disks: no login set.",
        ),
        (
            ControllerInitializationFailed("Failed to initialize drive controller connection"),
            "Failed to list Drive disks: the controller connection did not initialize.",
        ),
        (UniFiConnectionError("list Drive disks: timed out"), "Failed to list Drive disks: timed out"),
        (
            UniFiConnectionError("UniFi Drive request timed out."),
            "Failed to list Drive disks: UniFi Drive request timed out.",
        ),
    ],
)
def test_upstream_failures_name_the_failed_action_once(error, message):
    from unifi_api.services.drive import map_drive_error

    mapped = map_drive_error(error, "list Drive disks")

    assert (mapped.status, mapped.message) == (502, message)


def test_log_and_disk_stats_translators_pass_the_manager_only_what_it_takes():
    from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS
    from unifi_core.drive.models.logs import DriveLogQuery

    _, logs = DISPATCH_ARG_TRANSLATORS["drive_list_logs"]({"types": ["drive"], "scope": "audit", "limit": 5})
    _, windowed = DISPATCH_ARG_TRANSLATORS["drive_get_disk_stats"]({"hours": 6, "include_samples": True})
    _, default = DISPATCH_ARG_TRANSLATORS["drive_get_disk_stats"]({"include_samples": False})

    assert logs == {"query": DriveLogQuery(types=["drive"], scope="audit", limit=5)}
    # include_samples shapes the result; the manager reads the window only.
    assert (windowed, default) == ({"hours": 6}, {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("drive_list_logs", {"after": "2026-11-20T00:00:00Z", "before": "2026-11-19T00:00:00Z"}),
        ("drive_list_logs", {"category": "no-such-category"}),
        ("drive_list_snapshots", {"shared_drive_name": "Missing"}),
    ],
)
async def test_new_read_actions_fail_without_echoing_the_value(tmp_path, tool, args):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(app, headers, cid, tool, args)

    assert result["success"] is False
    for value in args.values():
        assert value not in result["error"]
    assert nas.changes == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("drive_set_file_service", {"service": "smb", "enabled": False}),
        ("drive_add_nfs_connection", {"client": NEW_CLIENT, "shared_drives": [{"id": DRIVE_ID}]}),
        ("drive_update_nfs_connection", {"client": CLIENT, "async_writes": True}),
        ("drive_remove_nfs_connection", {"client": CLIENT}),
    ],
)
async def test_a_preview_sends_nothing(tmp_path, tool, args):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    preview = await _action(app, headers, cid, tool, args)

    assert preview["requires_confirmation"] is True
    assert preview["tool"] == tool
    assert nas.requests == []


@pytest.mark.asyncio
async def test_add_preview_refuses_an_invalid_permission_before_any_request(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app,
        headers,
        cid,
        "drive_add_nfs_connection",
        {"client": NEW_CLIENT, "shared_drives": [{"id": DRIVE_ID, "permission": "write-everything"}]},
        confirm=True,
    )

    assert result["success"] is False
    assert "write-everything" not in result["error"]
    assert nas.requests == []


@pytest.mark.asyncio
async def test_confirmed_file_service_toggle_reads_the_state_back(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app, headers, cid, "drive_set_file_service", {"service": "smb", "enabled": False}, confirm=True
    )

    assert result == {
        "success": True,
        "data": {"service": "smb", "enabled": False, "changed": True},
        "render_hint": {"kind": "detail"},
    }
    assert nas.changes == [("PUT", f"{V1}/services/smb/settings", {"enable": False})]


@pytest.mark.asyncio
async def test_confirmed_toggle_that_changes_nothing_sends_nothing(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app, headers, cid, "drive_set_file_service", {"service": "nfs", "enabled": True}, confirm=True
    )

    assert result["data"] == {"service": "nfs", "enabled": True, "changed": False}
    assert nas.changes == []


@pytest.mark.asyncio
async def test_confirmed_add_keeps_every_other_client(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app,
        headers,
        cid,
        "drive_add_nfs_connection",
        {"client": NEW_CLIENT, "shared_drives": [{"id": DRIVE_ID, "permission": "ro"}]},
        confirm=True,
    )

    assert result["success"] is True, result
    assert result["data"]["connection"]["client"] == NEW_CLIENT
    assert result["data"]["connection"]["shared_drives"][0]["permission"] == "ro"
    [(method, path, body)] = nas.changes
    assert (method, path) == ("PATCH", NFS_SETTINGS)
    assert [entry["client"] for entry in body["connections"]] == [CLIENT, OTHER_CLIENT, NEW_CLIENT]


@pytest.mark.asyncio
async def test_confirmed_add_refuses_a_personal_drive_and_sends_nothing(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app,
        headers,
        cid,
        "drive_add_nfs_connection",
        {"client": NEW_CLIENT, "shared_drives": [{"id": PERSONAL_DRIVE_ID}]},
        confirm=True,
    )

    assert result["success"] is False
    assert "mutation_applied" not in result
    assert nas.changes == []


@pytest.mark.asyncio
async def test_confirmed_update_keeps_a_grant_permission_left_out(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app,
        headers,
        cid,
        "drive_update_nfs_connection",
        {"client": OTHER_CLIENT, "shared_drives": [{"id": OTHER_DRIVE_ID}, {"id": DRIVE_ID}]},
        confirm=True,
    )

    assert result["success"] is True, result
    grants = {grant["id"]: grant["permission"] for grant in result["data"]["connection"]["shared_drives"]}
    # Media kept its read-only grant; the newly granted drive defaults to read-write.
    assert grants == {OTHER_DRIVE_ID: "ro", DRIVE_ID: "rw"}
    [(_method, _path, body)] = nas.changes
    assert body["connections"][0]["client"] == CLIENT


@pytest.mark.asyncio
async def test_confirmed_remove(tmp_path):
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(app, headers, cid, "drive_remove_nfs_connection", {"client": CLIENT}, confirm=True)

    assert result["data"] == {"removed": CLIENT}
    assert [entry["client"] for entry in nas.connections] == [OTHER_CLIENT]


@pytest.mark.asyncio
async def test_write_sent_without_an_answer_is_unknown_never_success(tmp_path):
    nas = FakeDrive(faults={("PATCH", NFS_SETTINGS): transport_failure("PATCH", NFS_SETTINGS)})
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(app, headers, cid, "drive_remove_nfs_connection", {"client": CLIENT}, confirm=True)

    assert result["success"] is False
    assert result["mutation_applied"] is None
    assert "whether it was applied is unknown" in result["error"]
    assert NAS_HOST not in result["error"]
    assert (await _audit(app))[-1].error_kind == "write_outcome_unknown"


@pytest.mark.asyncio
async def test_write_stopped_before_the_change_is_not_applied(tmp_path):
    # The hostname check is answered by nothing, so the PATCH is never sent.
    nas = FakeDrive(faults={("POST", HOSTNAME_CHECK): transport_failure("POST", HOSTNAME_CHECK)})
    app, headers, _key, cid = await _app(tmp_path, nas)

    result = await _action(
        app,
        headers,
        cid,
        "drive_add_nfs_connection",
        {"client": NEW_CLIENT, "shared_drives": [{"id": DRIVE_ID}]},
        confirm=True,
    )

    assert result["success"] is False
    assert result["mutation_applied"] is False
    assert nas.changes == []
    assert (await _audit(app))[-1].error_kind == "write_not_sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("variable", ["UNIFI_DRIVE_READ_ONLY", "UNIFI_READ_ONLY"])
@pytest.mark.parametrize("confirm", [False, True])
async def test_read_only_mode_refuses_previews_and_writes(tmp_path, monkeypatch, variable, confirm):
    monkeypatch.setenv(variable, "true")
    nas = FakeDrive()
    app, headers, _key, cid = await _app(tmp_path, nas)

    await _action(
        app, headers, cid, "drive_set_file_service", {"service": "smb", "enabled": False}, confirm=confirm, status=403
    )
    reads = await _action(app, headers, cid, "drive_list_nfs_connections", {})

    assert reads["success"] is True
    assert nas.changes == []


@pytest.mark.asyncio
async def test_catalog_lists_drive_writes_with_their_serializer_hint(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path)

    async with client(app) as c:
        response = await c.get("/v1/catalog/tools", headers=headers)

    assert response.status_code == 200, response.text
    hints = {item["name"]: item["render_hint"] for item in response.json()["items"] if item["product"] == "drive"}
    assert hints["drive_set_file_service"] == {"kind": "detail"}
    assert hints["drive_list_nfs_connections"]["primary_key"] == "client"


# ---------------------------------------------------------------------------
# Controllers and the manager factory
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drive_controller_needs_a_username_and_password(tmp_path):
    app, headers, _key, _cid = await _app(tmp_path)

    async with client(app) as c:
        token_only = await c.post(
            "/v1/controllers",
            headers=headers,
            json={
                "name": "nas",
                "base_url": f"https://{NAS_HOST}",
                "product_kinds": ["drive"],
                "api_token": "synthetic-key-material",
            },
        )

    assert token_only.status_code == 422, token_only.text
    assert "Drive requires username and password" in token_only.text


@pytest.mark.asyncio
async def test_factory_builds_a_session_client_that_logs_in_on_first_use(tmp_path):
    app, _headers, _key, cid = await _app(tmp_path)
    factory = app.state.manager_factory

    async with app.state.sessionmaker() as session:
        cm = await factory.get_connection_manager(session, cid, "drive")
        manager = await factory.get_domain_manager(session, cid, "drive", "file_service_manager")

    assert isinstance(cm, DriveConnectionManager)
    assert (cm.host, cm.username, cm.password) == ("192.0.2.10", "u", "p")
    assert cm.is_connected is False
    assert manager._connection is cm
    await factory.invalidate_controller(cid)


@pytest.mark.asyncio
async def test_probe_logs_in_through_one_system_read(tmp_path, monkeypatch):
    nas = FakeDrive()
    app, _headers, _key, cid = await _app(tmp_path)
    original = DriveConnectionManager.__init__

    def _init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self._send = nas.send

    monkeypatch.setattr(DriveConnectionManager, "__init__", _init)

    result = await app.state.manager_factory.probe_controller(cid)

    assert result["products"]["drive"]["ok"] is True, result
    assert [(method, path) for method, path, _body in nas.requests][:2] == [
        ("POST", "/api/auth/login"),
        ("GET", "/api/system"),
    ]


@pytest.mark.asyncio
async def test_capabilities_list_drive_as_not_probed(tmp_path):
    from unifi_api.db.models import Controller
    from unifi_api.services.controllers import probe_capabilities

    controller = Controller(
        id="c",
        name="nas",
        base_url="https://127.0.0.1:9",
        product_kinds="drive",
        credentials_blob=credentials(username="u", password="p"),
        verify_tls=False,
    )

    payload = await probe_capabilities(controller)

    assert payload["not_probed"] == ["drive"]
    assert payload["products"] == []


@pytest.mark.asyncio
async def test_a_stored_drive_controller_without_a_login_fails_with_api_text(tmp_path):
    from unifi_api.db.models import Controller

    app, headers, _key, cid = await _app(tmp_path)
    async with app.state.sessionmaker() as session:
        row = await session.get(Controller, cid)
        row.credentials_blob = credentials(api_token="synthetic-key-material")
        await session.commit()

    response = await _get(app, headers, f"{BASE}/system")
    probe = await app.state.manager_factory.probe_controller(cid)

    assert response.status_code == 502, response.text
    # One failed action, then the API's own fixed reason: never "Failed to ...: Failed to initialize ...".
    assert response.json()["detail"] == {
        "kind": "drive_upstream_error",
        "message": (
            "Failed to get Drive system info: the controller has no username and password. "
            "UniFi Drive needs a local UniFi OS account on the NAS; update the controller with one."
        ),
    }
    # Never the MCP server's setup text, which names settings the API does not read.
    assert "UNIFI_DRIVE" not in response.text
    assert probe["products"]["drive"]["ok"] is False
    assert "has no username and password" in probe["products"]["drive"]["error"]


@pytest.mark.asyncio
async def test_a_successful_probe_heals_a_cached_client_whose_login_is_paused(tmp_path, monkeypatch):
    refused = FakeDrive(login_status=401)
    app, headers, _key, cid = await _app(tmp_path, refused)
    factory = app.state.manager_factory
    key = (cid, "drive", None)
    blocked = factory._connection_cache[key]

    first = await _get(app, headers, f"{BASE}/system")
    paused = await _get(app, headers, f"{BASE}/system")
    assert (first.status_code, paused.status_code) == (502, 502)
    assert "paused" in paused.json()["detail"]["message"]
    assert blocked.reconnect_blocked is True

    # A probe that still fails keeps the paused client.
    original = DriveConnectionManager.__init__
    probe_nas = FakeDrive(login_status=401)

    def _init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        self._send = probe_nas.send

    monkeypatch.setattr(DriveConnectionManager, "__init__", _init)
    assert (await factory.probe_controller(cid))["products"]["drive"]["ok"] is False
    assert factory._connection_cache[key] is blocked

    # Once the probe logs in, the paused client is dropped and the next read builds a fresh one.
    probe_nas.login_status = 200
    assert (await factory.probe_controller(cid))["products"]["drive"]["ok"] is True
    assert key not in factory._connection_cache

    healthy = FakeDrive()
    monkeypatch.setattr(probe_nas, "send", healthy.send)
    recovered = await _get(app, headers, f"{BASE}/system")
    assert recovered.status_code == 200, recovered.text
    assert factory._connection_cache[key] is not blocked
