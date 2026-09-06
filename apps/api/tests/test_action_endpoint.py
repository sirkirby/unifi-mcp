"""Action endpoint tests (with mocked dispatcher)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig, PolicyConfig, ResponsePolicyConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, AuditLog, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path: Path, *, redact_sensitive_fields: bool = True) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
        policy=PolicyConfig(response=ResponsePolicyConfig(redact_sensitive_fields=redact_sensitive_fields)),
    )


async def _bootstrap(
    tmp_path: Path,
    *,
    redact_sensitive_fields: bool = True,
    product_kinds: str = "network",
    scopes: str = "write",
):
    config = _cfg(tmp_path, redact_sensitive_fields=redact_sensitive_fields)
    app = create_app(config)
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    creds = cipher.encrypt(b'{"username":"u","password":"p","api_token":null}')
    material = generate_key()
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes=scopes,
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://x",
                product_kinds=product_kinds,
                credentials_blob=creds,
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


class _FakeClient:
    """Stand-in for an aiounifi.Client with a `.raw` dict attribute."""

    def __init__(self, raw: dict) -> None:
        self.raw = raw


@pytest.mark.asyncio
async def test_action_endpoint_enforces_confirmation_before_manager_interaction(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, product_kinds="access")

    manager = MagicMock()
    manager.list_doors = AsyncMock(return_value=[])
    manager.apply_unlock_door = AsyncMock(return_value=True)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        read_response = await client.post(
            "/v1/actions/access_list_doors",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )
        assert read_response.status_code == 200
        assert read_response.json()["success"] is True
        manager.list_doors.assert_awaited_once_with()

        factory.get_domain_manager.reset_mock()
        unconfirmed_response = await client.post(
            "/v1/actions/access_unlock_door",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "args": {"door_id": "door-1", "duration": 2},
                "confirm": False,
            },
        )
        assert unconfirmed_response.status_code == 200
        preview = unconfirmed_response.json()
        assert preview["success"] is True
        assert preview["requires_confirmation"] is True
        assert preview["tool"] == "access_unlock_door"
        assert preview["product"] == "access"
        assert preview["action"] == "update"
        assert preview["resource_id"] == "door-1"
        assert preview["preview"]["proposed"] == {"door_id": "door-1", "duration": 2}
        factory.get_domain_manager.assert_not_awaited()
        manager.apply_unlock_door.assert_not_awaited()

        confirmed_response = await client.post(
            "/v1/actions/access_unlock_door",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "args": {"door_id": "door-1", "duration": 2},
                "confirm": True,
            },
        )
        assert confirmed_response.status_code == 200
        assert confirmed_response.json()["success"] is True
        manager.apply_unlock_door.assert_awaited_once_with(door_id="door-1", duration=2)


@pytest.mark.asyncio
async def test_action_endpoint_unwraps_alarm_profile_facade_tuple(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, product_kinds="protect", scopes="admin")

    manager = MagicMock()
    manager.list_profiles = AsyncMock(
        return_value=(
            [
                {
                    "id": "01a06cca-1111-4222-8333-444444444444",
                    "name": "Away",
                    "state": "armed",
                    "state_set_at": "2026-09-04T12:00:00Z",
                    "id_family": "alarm_manager_v2",
                    "arm_compatible": False,
                }
            ],
            True,
        )
    )
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/actions/protect_alarm_list_profiles",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == {
        "profiles": [
            {
                "id": "01a06cca-1111-4222-8333-444444444444",
                "name": "Away",
                "state": "armed",
                "state_set_at": "2026-09-04T12:00:00Z",
                "id_family": "alarm_manager_v2",
                "arm_compatible": False,
            }
        ],
        "count": 1,
    }
    assert "result" not in body["data"]
    manager.list_profiles.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_action_endpoint_preserves_incomplete_alarm_profile_coverage(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, product_kinds="protect", scopes="admin")

    manager = MagicMock()
    manager.list_profiles = AsyncMock(return_value=([], False))
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/actions/protect_alarm_list_profiles",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["profiles"] == []
    assert data["count"] == 0
    assert data["_meta"]["com.github.sirkirby.unifi-mcp/alarm-coverage"]["complete"] is False


@pytest.mark.parametrize(
    ("product", "tool_name", "args", "manager_method"),
    [
        ("network", "unifi_reboot_device", {"mac_address": "aa:bb:cc:dd:ee:ff"}, "reboot_device"),
        ("protect", "protect_reboot_camera", {"camera_id": "camera-1"}, "apply_reboot_camera"),
    ],
)
@pytest.mark.asyncio
async def test_action_endpoint_previews_network_and_protect_without_manager_interaction(
    tmp_path,
    monkeypatch,
    product,
    tool_name,
    args,
    manager_method,
) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, product_kinds=product)
    manager = MagicMock()
    setattr(manager, manager_method, AsyncMock(return_value=True))
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/actions/{tool_name}",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": args, "confirm": False},
        )

    assert response.status_code == 200
    preview = response.json()
    assert preview["success"] is True
    assert preview["requires_confirmation"] is True
    assert preview["tool"] == tool_name
    assert preview["product"] == product
    assert preview["preview"]["proposed"] == args
    if product == "network":
        assert preview["resource_id"] == args["mac_address"]
    factory.get_domain_manager.assert_not_awaited()
    getattr(manager, manager_method).assert_not_awaited()


@pytest.mark.asyncio
async def test_action_endpoint_redacts_sensitive_preview_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock()
    app.state.manager_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/actions/unifi_create_wlan",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "args": {
                    "wlan_data": {
                        "name": "Preview only",
                        "security": "wpa2-psk",
                        "x_passphrase": "do-not-return-this",
                    }
                },
                "confirm": False,
            },
        )

    assert response.status_code == 200
    preview = response.json()
    assert preview["success"] is True
    assert preview["requires_confirmation"] is True
    assert preview["preview"]["will_create"]["wlan_data"]["x_passphrase"] == "***REDACTED***"
    assert "do-not-return-this" not in response.text
    factory.get_domain_manager.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_endpoint_dispatches_and_audits(tmp_path, monkeypatch) -> None:
    """Happy path: known tool, valid controller, audit log entry written."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    # Mock dispatcher to return a RAW list of manager-style objects (mirrors
    # what ClientManager.get_clients() actually returns: list[aiounifi.Client]).
    # The action endpoint now runs the result through ClientSerializer.
    from unifi_api.services import actions as actions_svc

    fake_dispatch = AsyncMock(return_value=[_FakeClient({"mac": "aa:bb", "is_online": True})])
    monkeypatch.setattr(actions_svc, "dispatch_action", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/unifi_list_clients",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"include_offline": True}, "confirm": False},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["data"] == [
        {
            "mac": "aa:bb",
            "ip": None,
            "hostname": None,
            "name": None,
            "is_wired": False,
            "is_guest": False,
            "status": "online",
            "last_seen": None,
            "first_seen": None,
            "note": None,
            "usergroup_id": None,
        }
    ]
    assert body["render_hint"]["kind"] == "list"
    assert body["render_hint"]["primary_key"] == "mac"

    # Audit log row
    sm = app.state.sessionmaker
    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        # Note: there's also the auth-success path which doesn't write audit
        # (only denials do). So we expect exactly 1 row from the action.
        action_rows = [r for r in rows if r.target == "unifi_list_clients"]
        assert len(action_rows) == 1
        assert action_rows[0].outcome == "success"


@pytest.mark.asyncio
async def test_action_endpoint_preserves_shared_read_view_metadata(tmp_path, monkeypatch) -> None:
    """Shared read views keep the typed action envelope and expose their metadata."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc
    from unifi_api.services.action_results import ShapedReadResult

    shaped = ShapedReadResult(
        payload={
            "success": True,
            "site": "default",
            "filter_type": "wired",
            "fields": "mac,connection_type",
            "total_count": 2,
            "returned_count": 1,
            "limit": 1,
            "clients": [{"mac": "aa:bb", "connection_type": "Wired"}],
        },
        data_key="clients",
        render_hint={
            "primary_key": "mac",
            "display_columns": ["name", "connection_type"],
            "sort_default": "name:asc",
        },
    )
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=shaped))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/v1/actions/unifi_list_clients",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "args": {"filter_type": "wired", "limit": 1, "fields": "mac,connection_type"},
                "confirm": False,
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["data"] == [{"mac": "aa:bb", "connection_type": "Wired"}]
    assert body["render_hint"] == {
        "kind": "list",
        "primary_key": "mac",
        "display_columns": ["connection_type"],
    }
    assert body["meta"] == {
        "site": "default",
        "filter_type": "wired",
        "fields": "mac,connection_type",
        "total_count": 2,
        "returned_count": 1,
        "limit": 1,
    }


@pytest.mark.asyncio
async def test_action_endpoint_rejects_malformed_shared_read_shape(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc
    from unifi_api.services.action_results import ShapedReadResult

    monkeypatch.setattr(
        actions_svc,
        "dispatch_action",
        AsyncMock(
            return_value=ShapedReadResult(
                payload={"success": True, "clients": {"mac": "aa:bb"}},
                data_key="clients",
                render_hint={"primary_key": "mac"},
            )
        ),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/v1/actions/unifi_list_clients",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )

    assert response.status_code == 500
    assert response.json()["detail"]["kind"] == "serializer_contract_error"
    assert response.json()["detail"]["detail"] == (
        "Failed to serialize action result. Contact the server administrator."
    )


@pytest.mark.asyncio
async def test_action_endpoint_serializer_contract_error(tmp_path, monkeypatch) -> None:
    """When manager returns wrong type for declared kind, endpoint returns 500."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    # unifi_list_clients is declared kind=LIST; returning a dict should trip
    # SerializerContractError and surface as 500 with structured detail.
    from unifi_api.services import actions as actions_svc

    fake_dispatch = AsyncMock(return_value={"single": "object"})
    monkeypatch.setattr(actions_svc, "dispatch_action", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/unifi_list_clients",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )
    assert r.status_code == 500, r.text
    body = r.json()
    assert body["detail"]["kind"] == "serializer_contract_error"
    assert body["detail"]["tool"] == "unifi_list_clients"

    # Audit row should record the contract error
    sm = app.state.sessionmaker
    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        action_rows = [r for r in rows if r.target == "unifi_list_clients"]
        assert len(action_rows) == 1
        assert action_rows[0].outcome == "error"
        assert action_rows[0].error_kind == "serializer_contract"


@pytest.mark.asyncio
async def test_action_endpoint_update_ack_tuple_success(tmp_path, monkeypatch) -> None:
    """Fetch-merge-put update managers return a (ok, error) ack tuple. A success
    tuple must surface as a clean {"success": true} envelope (not a stringified
    tuple) and audit as success."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=(True, None)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/unifi_update_network",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"network_id": "n1"}, "confirm": True},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"success": True}

    sm = app.state.sessionmaker
    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        action_rows = [row for row in rows if row.target == "unifi_update_network"]
        assert len(action_rows) == 1
        assert action_rows[0].outcome == "success"


@pytest.mark.asyncio
async def test_action_endpoint_snmp_update_accepts_v3_fields_without_enabled(tmp_path, monkeypatch) -> None:
    """The regenerated catalog no longer requires ``enabled`` and knows the v3 fields."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=(True, None)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/unifi_update_snmp_settings",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "args": {"enabled_v3": True, "username": "monitor", "x_password": "p"},
                "confirm": True,
            },
        )

    assert r.status_code == 200, r.text
    assert r.json() == {"success": True}


@pytest.mark.asyncio
async def test_action_endpoint_update_ack_tuple_failure(tmp_path, monkeypatch) -> None:
    """Regression: a FAILED update ack tuple must report success=false with the
    error message — not top-level success=true with the failure stringified into
    data.result — and must audit as error."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    err = "Controller accepted the request but did not persist field(s): upnp_enabled."
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=(False, err)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/unifi_update_network",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"network_id": "n1"}, "confirm": True},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is False
    assert body["error"] == err
    assert "result" not in body.get("data", {})

    sm = app.state.sessionmaker
    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        action_rows = [row for row in rows if row.target == "unifi_update_network"]
        assert len(action_rows) == 1
        assert action_rows[0].outcome == "error"


@pytest.mark.parametrize(
    ("tool_name", "items_key", "item"),
    [
        ("protect_list_known_faces", "faces", {"id": "face-1", "name": "P", "matched_name": "Person One"}),
        (
            "protect_list_known_license_plates",
            "license_plates",
            {"id": "plate-1", "name": "Vehicle", "matched_name": "ABC1234"},
        ),
    ],
)
@pytest.mark.asyncio
async def test_action_endpoint_unwraps_recognition_list_envelope(
    tmp_path, monkeypatch, tool_name, items_key, item
) -> None:
    """Recognition list tools return a ``{items_key: [...], count, links}`` dict
    envelope (not a bare list); the action path must unwrap it rather than 500
    with a serializer contract error."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    envelope = {items_key: [item], "count": 1, "links": {}}
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=envelope))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/v1/actions/{tool_name}",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["render_hint"]["kind"] == "list"
    assert isinstance(body["data"], list)
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == item["id"]
    assert body["data"][0]["matched_name"] == item["matched_name"]


@pytest.mark.asyncio
async def test_action_endpoint_redacts_by_default(tmp_path, monkeypatch) -> None:
    """The API action response path redacts secrets by default."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    wlan = _FakeClient({"_id": "wl-1", "name": "HomeNet", "x_passphrase": "wifi-secret"})
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=wlan))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/v1/actions/unifi_get_wlan_details",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"wlan_id": "wl-1"}, "confirm": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["x_passphrase"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_action_endpoint_policy_disabled_returns_raw_sensitive_fields(tmp_path, monkeypatch) -> None:
    """Operator policy can disable action response redaction for the API surface."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, redact_sensitive_fields=False)

    from unifi_api.services import actions as actions_svc

    wlan = _FakeClient({"_id": "wl-1", "name": "HomeNet", "x_passphrase": "wifi-secret"})
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=wlan))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/v1/actions/unifi_get_wlan_details",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"wlan_id": "wl-1"}, "confirm": False},
        )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["x_passphrase"] == "wifi-secret"


@pytest.mark.asyncio
async def test_action_endpoint_redacts_protect_camera_stream_urls_by_default(tmp_path, monkeypatch) -> None:
    """Typed action responses also honor response redaction policy."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    streams = {
        "camera_id": "cam-1",
        "camera_name": "Door",
        "channels": {
            "high": {
                "rtsp_alias": "abc123",
                "rtsps_url": "rtsps://nvr.local/abc123",
                "rtsp_url": "rtsp://nvr.local/abc123",
            }
        },
        "rtsps_streams": {"high": "rtsps://nvr.local/abc123"},
    }
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=streams))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/v1/actions/protect_get_camera_streams",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"camera_id": "cam-1"}, "confirm": False},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["channels"]["high"]["rtsp_alias"] == "***REDACTED***"
    assert data["channels"]["high"]["rtsps_url"] == "***REDACTED***"
    assert data["channels"]["high"]["rtsp_url"] == "***REDACTED***"
    assert data["rtsps_streams"] == "***REDACTED***"


@pytest.mark.asyncio
async def test_action_endpoint_policy_disabled_returns_raw_protect_camera_stream_urls(tmp_path, monkeypatch) -> None:
    """Typed action responses return raw stream URLs when API redaction policy is disabled."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, redact_sensitive_fields=False)

    from unifi_api.services import actions as actions_svc

    streams = {
        "camera_id": "cam-1",
        "camera_name": "Door",
        "channels": {
            "high": {
                "rtsp_alias": "abc123",
                "rtsps_url": "rtsps://nvr.local/abc123",
                "rtsp_url": "rtsp://nvr.local/abc123",
            }
        },
        "rtsps_streams": {"high": "rtsps://nvr.local/abc123"},
    }
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(return_value=streams))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            "/v1/actions/protect_get_camera_streams",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"camera_id": "cam-1"}, "confirm": False},
        )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["channels"]["high"]["rtsp_alias"] == "abc123"
    assert data["channels"]["high"]["rtsps_url"] == "rtsps://nvr.local/abc123"
    assert data["channels"]["high"]["rtsp_url"] == "rtsp://nvr.local/abc123"
    assert data["rtsps_streams"]["high"] == "rtsps://nvr.local/abc123"


@pytest.mark.asyncio
async def test_action_endpoint_rejects_include_sensitive_before_dispatch(tmp_path, monkeypatch) -> None:
    """Request args cannot override sensitive-field redaction per call."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    from unifi_api.services import actions as actions_svc

    fake_dispatch = AsyncMock(return_value=_FakeClient({"_id": "wl-1"}))
    monkeypatch.setattr(actions_svc, "dispatch_action", fake_dispatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        opted_out = await c.post(
            "/v1/actions/unifi_get_wlan_details",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "site": "default",
                "controller": cid,
                "args": {"wlan_id": "wl-1", "include_sensitive": True},
                "confirm": False,
            },
        )

    assert opted_out.status_code == 200, opted_out.text
    body = opted_out.json()
    assert body["success"] is False
    assert "include_sensitive is not supported" in body["error"]
    fake_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_endpoint_unknown_tool(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    # Don't mock dispatch_action — real one will raise ToolNotFound for fake tool name
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/totally_made_up_tool",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "unknown" in body["error"].lower()


@pytest.mark.asyncio
async def test_action_endpoint_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    # Real dispatch_action will raise CapabilityMismatch because controller is
    # network-only and the tool is protect_*
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/protect_list_cameras",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )
    body = r.json()
    assert body["success"] is False
    assert (
        "support" in body["error"].lower()
        or "capability" in body["error"].lower()
        or "mismatch" in body["error"].lower()
    )


@pytest.mark.asyncio
async def test_action_endpoint_unknown_controller(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, _ = await _bootstrap(tmp_path)

    fake_cid = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/actions/unifi_list_clients",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": fake_cid, "args": {}, "confirm": False},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", ["unexpected", "capability", "contract", "registry"])
async def test_action_exception_details_are_not_exposed(tmp_path, monkeypatch, error_type) -> None:
    """Arbitrary exception messages must not reach action clients, even on opt-out."""
    from unifi_api.serializers._base import SerializerContractError
    from unifi_api.serializers._registry import SerializerRegistryError
    from unifi_api.services import actions as actions_svc

    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, redact_sensitive_fields=False)
    private = "Traceback /private/server.py password=do-not-expose"
    errors = {
        "unexpected": RuntimeError(private),
        "capability": actions_svc.CapabilityMismatch(private),
        "contract": SerializerContractError(private),
        "registry": SerializerRegistryError(private),
    }
    monkeypatch.setattr(actions_svc, "dispatch_action", AsyncMock(side_effect=errors[error_type]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/actions/unifi_list_clients",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {}, "confirm": False},
        )
    assert response.status_code == (500 if error_type in {"contract", "registry"} else 200)
    for marker in ("Traceback", "/private/server.py", "do-not-expose", "RuntimeError"):
        assert marker not in response.text
    body = response.json()
    if response.status_code == 500:
        assert body["detail"]["tool"] == "unifi_list_clients"
        assert body["detail"]["kind"] in {"serializer_contract_error", "serializer_missing"}
    else:
        assert body["success"] is False
        assert "Failed to execute action" in body["error"]
    async with app.state.sessionmaker() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        actions = [row for row in rows if row.target == "unifi_list_clients"]
        assert len(actions) == 1
        assert actions[0].outcome == "error"
        assert actions[0].error_kind
