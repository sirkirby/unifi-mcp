"""Phase 5A PR2 Cluster 5 — port forwards / vouchers / SNMP routes."""

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


# ---------- port forwards ----------


@pytest.mark.asyncio
async def test_list_port_forwards_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "p1", "name": "ssh", "enabled": True, "fwd_port": "22", "dst_port": "22", "proto": "tcp"},
        {"_id": "p2", "name": "https", "enabled": True, "fwd_port": "443", "dst_port": "443", "proto": "tcp"},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_port_forwards", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-forwards?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_list_port_forwards_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-forwards?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "capability_mismatch"


@pytest.mark.asyncio
async def test_get_port_forward_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "p9", "name": "rdp", "enabled": True, "fwd_port": "3389", "dst_port": "3389", "proto": "tcp"}

    async def fake_get(self, rule_id):
        return target if rule_id == "p9" else None

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_port_forward_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-forwards/p9?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_port_forward_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, rule_id):
        return None

    from unifi_core.network.managers.firewall_manager import FirewallManager

    monkeypatch.setattr(FirewallManager, "get_port_forward_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-forwards/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_port_forward_unifi_not_found(tmp_path, monkeypatch) -> None:
    """Manager refactor PR #172: get_port_forward_by_id raises UniFiNotFoundError."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    from unifi_core.exceptions import UniFiNotFoundError
    from unifi_core.network.managers.firewall_manager import FirewallManager

    async def fake_get(self, rule_id):
        raise UniFiNotFoundError("port_forward", rule_id)

    monkeypatch.setattr(FirewallManager, "get_port_forward_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-forwards/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- vouchers ----------


@pytest.mark.asyncio
async def test_list_vouchers_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": "v1", "code": "1234567890", "create_time": 1700000000, "duration": 60, "quota": 1, "used": 0},
        {"_id": "v2", "code": "0987654321", "create_time": 1700000100, "duration": 60, "quota": 1, "used": 1},
    ]

    async def fake_get(self, create_time=None):
        return fake

    from unifi_core.network.managers.hotspot_manager import HotspotManager

    monkeypatch.setattr(HotspotManager, "get_vouchers", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/vouchers?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_voucher_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "v9", "code": "ABCDEFGHIJ", "duration": 120, "quota": 1, "used": 0}

    async def fake_get(self, voucher_id):
        return target if voucher_id == "v9" else None

    from unifi_core.network.managers.hotspot_manager import HotspotManager

    monkeypatch.setattr(HotspotManager, "get_voucher_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/voucher-details/v9?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"


# ---------- SNMP ----------


@pytest.mark.asyncio
async def test_get_snmp_settings_happy_path(tmp_path, monkeypatch) -> None:
    """SNMP manager returns list[dict]; serializer unwraps the first item."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [{"enabled": True, "community": "public", "port": 161, "version": "v2c"}]

    async def fake_get(self, section):
        assert section == "snmp"
        return fake

    from unifi_core.network.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "get_settings", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/snmp-settings?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["enabled"] is True
    assert body["data"]["community"] == "public"
