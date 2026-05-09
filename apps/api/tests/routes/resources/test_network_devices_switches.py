"""Phase 5A PR1 Cluster 1 — devices & switches resource routes."""

from datetime import datetime, timezone
import uuid

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
        session.add(ApiKey(
            id=str(uuid.uuid4()), prefix=material.prefix,
            hash=hash_key(material.plaintext), scopes="read",
            name="t", created_at=datetime.now(timezone.utc),
        ))
        session.add(Controller(
            id=cid, name="N", base_url="https://x", product_kinds=products,
            credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
            verify_tls=False, is_default=True,
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ))
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


# ---------- port profiles ----------


@pytest.mark.asyncio
async def test_list_port_profiles_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_profiles = [
        {"_id": f"pp-{i}", "name": f"profile-{i}", "poe_mode": "auto",
         "native_networkconf_id": f"net-{i}"}
        for i in range(3)
    ]

    async def fake_get_port_profiles(self, *a, **kw):
        return fake_profiles

    from unifi_core.network.managers.switch_manager import SwitchManager
    monkeypatch.setattr(SwitchManager, "get_port_profiles", fake_get_port_profiles)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-profiles?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "next_cursor" in body and "render_hint" in body
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 3
    assert {item["id"] for item in body["items"]} == {"pp-0", "pp-1", "pp-2"}


@pytest.mark.asyncio
async def test_list_port_profiles_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")  # no network

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-profiles?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "network"


@pytest.mark.asyncio
async def test_get_port_profile_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "pp-1", "name": "trunk-all", "poe_mode": "off",
              "native_networkconf_id": "n-1"}

    async def fake_get(self, profile_id):
        return target if profile_id == "pp-1" else None

    from unifi_core.network.managers.switch_manager import SwitchManager
    monkeypatch.setattr(SwitchManager, "get_port_profile_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-profiles/pp-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "render_hint" in body
    assert body["data"]["id"] == "pp-1"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_port_profile_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, profile_id):
        return None

    from unifi_core.network.managers.switch_manager import SwitchManager
    monkeypatch.setattr(SwitchManager, "get_port_profile_by_id", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/port-profiles/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- switch ports (wrapper-dict) ----------


@pytest.mark.asyncio
async def test_list_switch_ports_unwraps_wrapper_dict(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    wrapper = {
        "name": "sw-1",
        "model": "US-24",
        "port_overrides": [
            {"port_idx": i, "name": f"Port {i}", "portconf_id": f"pc-{i}",
             "poe_mode": "auto", "op_mode": "switch"}
            for i in range(4)
        ],
    }

    async def fake_get_switch_ports(self, mac):
        return wrapper

    from unifi_core.network.managers.switch_manager import SwitchManager
    monkeypatch.setattr(SwitchManager, "get_switch_ports", fake_get_switch_ports)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/switch-ports?controller={cid}&device_mac=aa:bb:cc:dd:ee:01",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 4
    # Pagination sorts descending by (port_idx, ""), so highest comes first.
    assert body["items"][0]["port_idx"] == 3
    assert body["items"][-1]["port_idx"] == 0


# ---------- LLDP neighbors (wrapper-dict) ----------


@pytest.mark.asyncio
async def test_list_lldp_neighbors_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    wrapper = {
        "name": "sw-1",
        "model": "US-24",
        "lldp_table": [
            {"local_port_idx": 1, "chassis_id": "11:22:33:44:55:66",
             "port_id": "1", "system_name": "neighbor-a", "capabilities": ["bridge"]},
            {"local_port_idx": 2, "chassis_id": "aa:bb:cc:dd:ee:ff",
             "port_id": "2", "system_name": "neighbor-b", "capabilities": []},
        ],
    }

    async def fake_lldp(self, mac):
        return wrapper

    from unifi_core.network.managers.switch_manager import SwitchManager
    monkeypatch.setattr(SwitchManager, "get_lldp_neighbors", fake_lldp)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/lldp-neighbors?controller={cid}&device_mac=aa:bb:cc:dd:ee:01",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    # Descending sort by local_port_idx — neighbor-b (port 2) first.
    assert body["items"][0]["system_name"] == "neighbor-b"
    assert body["items"][-1]["system_name"] == "neighbor-a"


# ---------- rogue APs ----------


@pytest.mark.asyncio
async def test_list_rogue_aps_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_rogues = [
        {"bssid": f"de:ad:be:ef:00:0{i}", "essid": f"NeighborSSID-{i}",
         "channel": 6, "rssi": -60 - i, "last_seen": 1700000000 - i}
        for i in range(3)
    ]

    async def fake_list(self, within_hours=24):
        return fake_rogues

    from unifi_core.network.managers.device_manager import DeviceManager
    monkeypatch.setattr(DeviceManager, "list_rogue_aps", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/rogue-aps?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 3
    assert body["items"][0]["bssid"].startswith("de:ad:be:ef:")


# ---------- speedtest status ----------


@pytest.mark.asyncio
async def test_get_speedtest_status_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_status = {"status": 0, "status_download": 875.5, "status_upload": 42.1,
                   "latency": 8, "rundate": 1700000000}

    async def fake_get_status(self, gateway_mac):
        return fake_status

    from unifi_core.network.managers.device_manager import DeviceManager
    monkeypatch.setattr(DeviceManager, "get_speedtest_status", fake_get_status)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/speedtest-status?controller={cid}&gateway_mac=00:11:22:33:44:55",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "render_hint" in body
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["download_mbps"] == 875.5
    assert body["data"]["status"] == "idle"


# ---------- available channels ----------


@pytest.mark.asyncio
async def test_list_available_channels_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_channels = [
        {"channel": 1, "freq": 2412, "ht": 20, "allowed": True},
        {"channel": 6, "freq": 2437, "ht": 20, "allowed": True},
        {"channel": 11, "freq": 2462, "ht": 20, "allowed": True},
    ]

    async def fake_list(self, *a, **kw):
        return fake_channels

    from unifi_core.network.managers.device_manager import DeviceManager
    monkeypatch.setattr(DeviceManager, "list_available_channels", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/available-channels?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 3
    # Descending sort by channel — 11 first, 1 last.
    assert {item["channel"] for item in body["items"]} == {1, 6, 11}
    assert body["items"][0]["channel"] == 11


# ---------- device radio (extension to /devices/{mac}/radio) ----------


@pytest.mark.asyncio
async def test_get_device_radio_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_radio = {
        "mac": "aa:bb:cc:dd:ee:01",
        "name": "ap-1",
        "model": "U6",
        "radios": [
            {"name": "wifi0", "radio": "ng", "channel": 6, "ht": "20",
             "tx_power": 20, "tx_power_mode": "auto",
             "current_channel": 6, "current_tx_power": 20, "num_sta": 5},
        ],
    }

    async def fake_radio_get(self, mac):
        return fake_radio if mac == "aa:bb:cc:dd:ee:01" else None

    from unifi_core.network.managers.device_manager import DeviceManager
    monkeypatch.setattr(DeviceManager, "get_device_radio", fake_radio_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/devices/aa:bb:cc:dd:ee:01/radio?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "render_hint" in body
    assert body["data"]["mac"] == "aa:bb:cc:dd:ee:01"
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["radios"][0]["channel"] == 6
