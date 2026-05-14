"""Access resource endpoints — happy paths, capability mismatch, 404."""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path):
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path, products="access"):
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    material = generate_key()
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="read",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="A",
                base_url="https://x",
                product_kinds=products,
                credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


class _FakeAccessCM:
    """Stub access connection manager — no set_site (single-controller-no-site)."""

    async def initialize(self) -> None:
        return None


def _stub_connection(app, cid: str) -> _FakeAccessCM:
    fake = _FakeAccessCM()
    app.state.manager_factory._connection_cache[(cid, "access")] = fake
    return fake


@pytest.mark.asyncio
async def test_list_doors_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_doors = [
        {
            "id": f"door-{i}",
            "name": f"Door {i}",
            "door_position_status": "closed",
            "lock_relay_status": "locked",
        }
        for i in range(4)
    ]

    async def fake_list(self, *a, **kw):
        return fake_doors

    from unifi_core.access.managers.door_manager import DoorManager

    monkeypatch.setattr(DoorManager, "list_doors", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/doors?controller={cid}&limit=2",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_list_doors_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")  # no access

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/doors?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "access"


@pytest.mark.asyncio
async def test_get_door_happy_and_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {
        "id": "door-1",
        "name": "Lobby",
        "door_position_status": "closed",
        "lock_relay_status": "locked",
    }

    async def fake_get(self, door_id):
        if door_id == "door-1":
            return target
        raise ValueError(f"Door not found: {door_id}")

    from unifi_core.access.managers.door_manager import DoorManager

    monkeypatch.setattr(DoorManager, "get_door", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/doors/door-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/doors/door-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["data"]["id"] == "door-1"
    assert body["render_hint"]["kind"] == "detail"
    assert miss.status_code == 404


@pytest.mark.asyncio
async def test_list_users_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_users = [
        {"id": f"user-{i}", "first_name": "F", "last_name": f"L{i}", "email": f"u{i}@x.com", "status": "active"}
        for i in range(3)
    ]

    async def fake_list(self, *a, **kw):
        return fake_users

    from unifi_core.access.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "list_users", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/users?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"
    assert {item["id"] for item in body["items"]} == {"user-0", "user-1", "user-2"}


@pytest.mark.asyncio
async def test_get_user_filter_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_users = [
        {"id": "user-1", "first_name": "Ada", "last_name": "L", "email": "ada@x.com", "status": "active"},
    ]

    async def fake_list(self, *a, **kw):
        return fake_users

    from unifi_core.access.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "list_users", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/users/user-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/users/user-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["id"] == "user-1"
    assert miss.status_code == 404


@pytest.mark.asyncio
async def test_list_credentials_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_credentials = [
        {"id": f"cred-{i}", "type": "card", "user_id": f"user-{i}", "status": "active"} for i in range(3)
    ]

    async def fake_list(self, *a, **kw):
        return fake_credentials

    from unifi_core.access.managers.credential_manager import CredentialManager

    monkeypatch.setattr(CredentialManager, "list_credentials", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/credentials?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_credential_happy_and_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"id": "cred-1", "type": "card", "user_id": "user-1", "status": "active"}

    async def fake_get(self, credential_id):
        if credential_id == "cred-1":
            return target
        raise ValueError(f"Credential not found: {credential_id}")

    from unifi_core.access.managers.credential_manager import CredentialManager

    monkeypatch.setattr(CredentialManager, "get_credential", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/credentials/cred-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/credentials/cred-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["data"]["id"] == "cred-1"
    assert body["render_hint"]["kind"] == "detail"
    assert miss.status_code == 404
