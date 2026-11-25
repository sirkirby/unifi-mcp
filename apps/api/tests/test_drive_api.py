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
from unifi_core.drive.managers.connection_manager import DriveConnectionManager

from tests.drive_data import (
    BIG_CAPACITY,
    CLIENT,
    DRIVE_ID,
    HOSTNAME_CHECK,
    MISSING_DRIVE_ID,
    NAS_HOST,
    NEW_CLIENT,
    NFS_SETTINGS,
    OTHER_CLIENT,
    OTHER_DRIVE_ID,
    PERSONAL_DRIVE_ID,
    POOL_ID,
    V1,
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


# ---------------------------------------------------------------------------
# Actions: reads, previews and confirmed writes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_actions_use_the_read_projections(tmp_path):
    app, headers, _key, cid = await _app(tmp_path, FakeDrive())

    pools = await _action(app, headers, cid, "drive_list_storage_pools", {})
    disks = await _action(app, headers, cid, "drive_list_disks", {"include_cache": False})

    assert pools["success"] is True
    assert pools["data"][0]["capacity_bytes"] == BIG_CAPACITY
    assert pools["render_hint"]["kind"] == "list"
    assert [d["bay_type"] for d in disks["data"]] == ["disk"]


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
