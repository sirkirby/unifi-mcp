"""Phase 5A PR1 Cluster 2 — clients & user groups resource routes."""

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


async def _bootstrap(tmp_path, products="network"):
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
                name="N",
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


class _FakeCM:
    def __init__(self) -> None:
        self.site = "default"

    async def initialize(self) -> None:
        return None

    async def set_site(self, s: str) -> None:
        self.site = s


def _stub_connection(app, cid: str) -> _FakeCM:
    fake = _FakeCM()
    app.state.manager_factory._connection_cache[(cid, "network")] = fake
    return fake


# ---------- blocked clients ----------


@pytest.mark.asyncio
async def test_list_blocked_clients_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_blocked = [
        {"mac": f"aa:bb:cc:dd:ee:0{i}", "hostname": f"host-{i}", "blocked": True, "last_seen": 1700000000 - i}
        for i in range(3)
    ]

    async def fake_get_blocked(self):
        return fake_blocked

    from unifi_core.network.managers.client_manager import ClientManager

    monkeypatch.setattr(ClientManager, "get_blocked_clients", fake_get_blocked)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/blocked-clients?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "next_cursor" in body and "render_hint" in body
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 3
    assert all(item["blocked"] is True for item in body["items"])


@pytest.mark.asyncio
async def test_list_blocked_clients_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")  # no network

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/blocked-clients?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "network"


# ---------- client groups ----------


@pytest.mark.asyncio
async def test_list_client_groups_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_groups = [{"_id": f"cg-{i}", "name": f"group-{i}", "type": "manual"} for i in range(3)]

    async def fake_list(self):
        return fake_groups

    from unifi_core.network.managers.client_group_manager import ClientGroupManager

    monkeypatch.setattr(ClientGroupManager, "get_client_groups", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/client-groups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_get_client_group_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "cg-1", "name": "marketing", "type": "manual"}

    async def fake_get(self, group_id):
        return target if group_id == "cg-1" else None

    from unifi_core.network.managers.client_group_manager import ClientGroupManager

    monkeypatch.setattr(ClientGroupManager, "get_client_group_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/client-groups/cg-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "render_hint" in body
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_client_group_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, group_id):
        return None

    from unifi_core.network.managers.client_group_manager import ClientGroupManager

    monkeypatch.setattr(ClientGroupManager, "get_client_group_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/client-groups/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- user groups (usergroups, bandwidth profiles) ----------


@pytest.mark.asyncio
async def test_list_user_groups_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_groups = [
        {"_id": f"ug-{i}", "name": f"qos-{i}", "qos_rate_max_down": 1000, "qos_rate_max_up": 500} for i in range(2)
    ]

    async def fake_list(self):
        return fake_groups

    from unifi_core.network.managers.usergroup_manager import UsergroupManager

    monkeypatch.setattr(UsergroupManager, "get_usergroups", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/user-groups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_user_group_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "ug-1", "name": "premium", "qos_rate_max_down": 5000, "qos_rate_max_up": 2000}

    async def fake_get(self, group_id):
        return target if group_id == "ug-1" else None

    from unifi_core.network.managers.usergroup_manager import UsergroupManager

    monkeypatch.setattr(UsergroupManager, "get_usergroup_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/user-groups/ug-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "render_hint" in body
    assert body["render_hint"]["kind"] == "detail"


# ---------- lookup-by-ip ----------


@pytest.mark.asyncio
async def test_lookup_by_ip_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {
        "mac": "aa:bb:cc:dd:ee:01",
        "last_ip": "10.0.0.5",
        "hostname": "kiosk-1",
        "is_online": True,
        "last_seen": 1700000000,
    }

    async def fake_lookup(self, ip):
        return target if ip == "10.0.0.5" else None

    from unifi_core.network.managers.client_manager import ClientManager

    monkeypatch.setattr(ClientManager, "get_client_by_ip", fake_lookup)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/lookup-by-ip?controller={cid}&ip=10.0.0.5",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "render_hint" in body
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["ip"] == "10.0.0.5"
    assert body["data"]["is_online"] is True


@pytest.mark.asyncio
async def test_lookup_by_ip_missing_ip_query_param(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/lookup-by-ip?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    # FastAPI returns 422 for missing required query parameters.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_lookup_by_ip_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_lookup(self, ip):
        return None

    from unifi_core.network.managers.client_manager import ClientManager

    monkeypatch.setattr(ClientManager, "get_client_by_ip", fake_lookup)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/lookup-by-ip?controller={cid}&ip=10.0.0.99",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404
