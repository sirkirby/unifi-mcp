"""Network resource endpoints — happy paths, capability mismatch, pagination, 404."""

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
    """Stub connection manager that bypasses live initialize/auth."""

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


class _FakeRaw:
    """Tiny stand-in for manager domain objects with a ``raw`` dict."""

    def __init__(self, raw: dict) -> None:
        self.raw = raw


@pytest.mark.asyncio
async def test_list_clients_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_clients = [
        _FakeRaw(
            {
                "mac": f"aa:bb:cc:dd:ee:0{i}",
                "last_ip": f"10.0.0.{i}",
                "hostname": f"host-{i}",
                "is_online": True,
                "last_seen": 1700000000 - i,
            }
        )
        for i in range(5)
    ]

    async def fake_get_clients(self, *a, **kw):
        return fake_clients

    from unifi_core.network.managers.client_manager import ClientManager

    monkeypatch.setattr(ClientManager, "get_clients", fake_get_clients)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/clients?controller={cid}&limit=3",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert "next_cursor" in body
    assert "render_hint" in body
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 3
    assert body["next_cursor"] is not None  # 5 total, page=3, more remain


@pytest.mark.asyncio
async def test_list_clients_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")  # no network

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/clients?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "network"


@pytest.mark.asyncio
async def test_get_client_detail_happy_and_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = _FakeRaw(
        {
            "mac": "aa:bb:cc:dd:ee:00",
            "last_ip": "10.0.0.0",
            "hostname": "alpha",
            "is_online": True,
            "last_seen": 1700000000,
        }
    )

    async def fake_details(self, mac):
        return target if mac == "aa:bb:cc:dd:ee:00" else None

    from unifi_core.network.managers.client_manager import ClientManager

    monkeypatch.setattr(ClientManager, "get_client_details", fake_details)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/clients/aa:bb:cc:dd:ee:00?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/clients/ff:ff:ff:ff:ff:ff?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert "data" in body and "render_hint" in body
    assert body["data"]["mac"] == "aa:bb:cc:dd:ee:00"
    assert body["render_hint"]["kind"] == "detail"

    assert miss.status_code == 404


@pytest.mark.asyncio
async def test_list_devices_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_devices = [
        _FakeRaw({"mac": f"de:ad:be:ef:00:0{i}", "name": f"ap-{i}", "model": "U6", "uptime": 1000 - i, "state": 1})
        for i in range(4)
    ]

    async def fake_get_devices(self, *a, **kw):
        return fake_devices

    from unifi_core.network.managers.device_manager import DeviceManager

    monkeypatch.setattr(DeviceManager, "get_devices", fake_get_devices)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/devices?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 4
    assert body["next_cursor"] is None
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_list_networks_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_nets = [
        {"_id": f"n-{i}", "name": f"net-{i}", "purpose": "corporate", "vlan": 10 + i, "enabled": True} for i in range(3)
    ]

    async def fake_get_networks(self, *a, **kw):
        return fake_nets

    from unifi_core.network.managers.network_manager import NetworkManager

    monkeypatch.setattr(NetworkManager, "get_networks", fake_get_networks)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/networks?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {item["id"] for item in body["items"]} == {"n-0", "n-1", "n-2"}


@pytest.mark.asyncio
async def test_list_wlans_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_wlans = [
        _FakeRaw({"_id": f"w-{i}", "name": f"ssid-{i}", "enabled": True, "security": "wpapsk"}) for i in range(2)
    ]

    async def fake_get_wlans(self, *a, **kw):
        return fake_wlans

    from unifi_core.network.managers.network_manager import NetworkManager

    monkeypatch.setattr(NetworkManager, "get_wlans", fake_get_wlans)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/wlans?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_list_firewall_rules_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_rules = [
        _FakeRaw({"_id": f"r-{i}", "name": f"rule-{i}", "action": "allow", "enabled": True, "predefined": False})
        for i in range(3)
    ]

    async def fake_get_policies(self, *a, **kw):
        return fake_rules

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_firewall_policies", fake_get_policies)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firewall/rules?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert {item["id"] for item in body["items"]} == {"r-0", "r-1", "r-2"}
    assert body["render_hint"]["kind"] == "list"
