"""Action endpoint tests (with mocked dispatcher)."""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, AuditLog, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path: Path):
    app = create_app(_cfg(tmp_path))
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
