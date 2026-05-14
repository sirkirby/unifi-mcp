"""Phase 5A PR1 Cluster 3 — networks/WLANs/VPN/DNS/routing config resource routes.

Covers active routes, static routes, traffic routes, DNS records, VPN clients,
VPN servers, and AP groups (LIST + DETAIL where the manifest has details).
"""

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


# ---------- active routes ----------


@pytest.mark.asyncio
async def test_list_active_routes_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"pfx": "10.0.0.0/24", "nh": [{"via": "10.0.0.1", "intf": "eth0"}], "metric": 1},
        {"pfx": "192.168.1.0/24", "nh": [{"via": "192.168.1.1", "intf": "eth1"}], "metric": 2},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.routing_manager import RoutingManager

    monkeypatch.setattr(RoutingManager, "get_active_routes", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/active-routes?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    assert body["items"][0]["gateway"] == "10.0.0.1"
    assert body["items"][0]["interface"] == "eth0"


@pytest.mark.asyncio
async def test_list_active_routes_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/active-routes?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["kind"] == "capability_mismatch"


# ---------- static routes ----------


@pytest.mark.asyncio
async def test_list_routes_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {
            "_id": f"sr-{i}",
            "name": f"route-{i}",
            "static-route_network": f"10.{i}.0.0/24",
            "static-route_nexthop": f"10.{i}.0.1",
            "static-route_distance": 1,
            "enabled": True,
        }
        for i in range(2)
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.routing_manager import RoutingManager

    monkeypatch.setattr(RoutingManager, "get_routes", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/static-routes?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    # paginate() sorts descending; sr-1 comes before sr-0.
    subnets = {i["target_subnet"] for i in body["items"]}
    assert subnets == {"10.0.0.0/24", "10.1.0.0/24"}


@pytest.mark.asyncio
async def test_get_route_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {
        "_id": "sr-1",
        "name": "office",
        "static-route_network": "10.5.0.0/24",
        "static-route_nexthop": "10.5.0.1",
        "enabled": True,
    }

    async def fake_get(self, route_id):
        return target if route_id == "sr-1" else None

    from unifi_core.network.managers.routing_manager import RoutingManager

    monkeypatch.setattr(RoutingManager, "get_route_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/static-routes/sr-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["target_subnet"] == "10.5.0.0/24"


@pytest.mark.asyncio
async def test_get_route_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, route_id):
        return None

    from unifi_core.network.managers.routing_manager import RoutingManager

    monkeypatch.setattr(RoutingManager, "get_route_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/static-routes/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- traffic routes ----------


@pytest.mark.asyncio
async def test_list_traffic_routes_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {
            "_id": "tr-1",
            "description": "vpn-traffic",
            "matching_target": "DOMAIN",
            "domains": ["example.com"],
            "next_hop": "wg0",
            "enabled": True,
        },
        {"_id": "tr-2", "description": "iot", "matching_target": "IP", "ip_addresses": ["8.8.8.8"], "enabled": False},
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager

    monkeypatch.setattr(TrafficRouteManager, "get_traffic_routes", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/traffic-routes?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2
    # Note: traffic routes use `description` for the human-readable name.
    names = {i["name"] for i in body["items"]}
    assert names == {"vpn-traffic", "iot"}


@pytest.mark.asyncio
async def test_get_traffic_route_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {
        "_id": "tr-1",
        "description": "vpn-traffic",
        "matching_target": "DOMAIN",
        "domains": ["example.com"],
        "enabled": True,
    }

    async def fake_get(self, route_id):
        return target if route_id == "tr-1" else None

    from unifi_core.network.managers.traffic_route_manager import TrafficRouteManager

    monkeypatch.setattr(TrafficRouteManager, "get_traffic_route_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/traffic-routes/tr-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["name"] == "vpn-traffic"


# ---------- DNS records ----------


@pytest.mark.asyncio
async def test_list_dns_records_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": f"dns-{i}", "key": f"host-{i}.local", "value": f"10.0.0.{10 + i}", "record_type": "A", "enabled": True}
        for i in range(2)
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.dns_manager import DnsManager

    monkeypatch.setattr(DnsManager, "list_dns_records", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dns-records?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_dns_record_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "dns-1", "key": "host-1.local", "value": "10.0.0.11", "record_type": "A", "enabled": True}

    async def fake_get(self, record_id):
        return target if record_id == "dns-1" else None

    from unifi_core.network.managers.dns_manager import DnsManager

    monkeypatch.setattr(DnsManager, "get_dns_record", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dns-records/dns-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_dns_record_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, record_id):
        return None

    from unifi_core.network.managers.dns_manager import DnsManager

    monkeypatch.setattr(DnsManager, "get_dns_record", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dns-records/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_dns_record_details_unifi_not_found(tmp_path, monkeypatch) -> None:
    """Manager refactor PR #172: get_dns_record raises UniFiNotFoundError."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    from unifi_core.exceptions import UniFiNotFoundError
    from unifi_core.network.managers.dns_manager import DnsManager

    async def fake_get(self, record_id):
        raise UniFiNotFoundError("dns_record", record_id)

    monkeypatch.setattr(DnsManager, "get_dns_record", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/dns-records/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- VPN clients ----------


@pytest.mark.asyncio
async def test_list_vpn_clients_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": f"vc-{i}", "name": f"client-{i}", "vpn_type": "wireguard-client", "enabled": True} for i in range(2)
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.vpn_manager import VpnManager

    monkeypatch.setattr(VpnManager, "get_vpn_clients", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/vpn-clients?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_vpn_client_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "vc-1", "name": "client-1", "vpn_type": "wireguard-client", "enabled": True}

    async def fake_get(self, client_id):
        return target if client_id == "vc-1" else None

    from unifi_core.network.managers.vpn_manager import VpnManager

    monkeypatch.setattr(VpnManager, "get_vpn_client_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/vpn-clients/vc-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"


# ---------- VPN servers ----------


@pytest.mark.asyncio
async def test_list_vpn_servers_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [
        {"_id": f"vs-{i}", "name": f"server-{i}", "vpn_type": "wireguard-server", "enabled": True} for i in range(2)
    ]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.vpn_manager import VpnManager

    monkeypatch.setattr(VpnManager, "get_vpn_servers", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/vpn-servers?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_vpn_server_details_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, server_id):
        return None

    from unifi_core.network.managers.vpn_manager import VpnManager

    monkeypatch.setattr(VpnManager, "get_vpn_server_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/vpn-servers/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------- AP groups ----------


@pytest.mark.asyncio
async def test_list_ap_groups_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake = [{"_id": f"apg-{i}", "name": f"group-{i}", "device_macs": [f"aa:bb:cc:dd:ee:0{i}"]} for i in range(2)]

    async def fake_get(self):
        return fake

    from unifi_core.network.managers.network_manager import NetworkManager

    monkeypatch.setattr(NetworkManager, "list_ap_groups", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/ap-groups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "list"
    assert len(body["items"]) == 2


@pytest.mark.asyncio
async def test_get_ap_group_details_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"_id": "apg-1", "name": "lobby", "device_macs": ["aa:bb:cc:dd:ee:01"]}

    async def fake_get(self, group_id):
        return target if group_id == "apg-1" else None

    from unifi_core.network.managers.network_manager import NetworkManager

    monkeypatch.setattr(NetworkManager, "get_ap_group_details", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/ap-groups/apg-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
