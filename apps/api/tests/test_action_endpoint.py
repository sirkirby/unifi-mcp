"""Action endpoint tests (with mocked dispatcher)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

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


async def _bootstrap(tmp_path: Path, *, redact_sensitive_fields: bool = True):
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
                scopes="write",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://x",
                product_kinds="network",
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
    with a serializer contract error. Regression for issue #312."""
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
