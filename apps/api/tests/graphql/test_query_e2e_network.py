"""Phase 6 PR2.5 — end-to-end network GraphQL queries.

Five representative consumer flows (flat list, deep relationship edge,
cross-resource fan-in, pagination, auth scope) plus the deep N+1 regression
sibling lives in `test_n1_regression.py`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path: Path):
    """Bootstrap an admin-keyed app with one controller seeded."""
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    material = generate_key()
    cid = str(uuid.uuid4())
    cipher = ColumnCipher(derive_key("k"))
    cred_blob = cipher.encrypt(json.dumps({"username": "u", "password": "p", "api_token": None}).encode("utf-8"))
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="admin",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="c",
                base_url="https://c",
                product_kinds="network",
                credentials_blob=cred_blob,
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


def _stub_managers(
    monkeypatch,
    *,
    clients: list[Any] | None = None,
    devices: list[Any] | None = None,
    networks: list[Any] | None = None,
):
    """Patch ManagerFactory.get_domain_manager / get_connection_manager so
    network resolvers see preconfigured fixture data.

    Returns a per-method call counter dict for N+1 assertions.
    """
    call_counts: dict[str, int] = {
        "get_clients": 0,
        "get_devices": 0,
        "get_networks": 0,
    }

    async def _stub_get_clients():
        call_counts["get_clients"] += 1
        return clients or []

    async def _stub_get_devices():
        call_counts["get_devices"] += 1
        return devices or []

    async def _stub_get_networks():
        call_counts["get_networks"] += 1
        return networks or []

    fake_client_mgr = MagicMock()
    fake_client_mgr.get_clients = _stub_get_clients
    fake_device_mgr = MagicMock()
    fake_device_mgr.get_devices = _stub_get_devices
    fake_network_mgr = MagicMock()
    fake_network_mgr.get_networks = _stub_get_networks

    domain_mgrs = {
        ("network", "client_manager"): fake_client_mgr,
        ("network", "device_manager"): fake_device_mgr,
        ("network", "network_manager"): fake_network_mgr,
    }

    async def _fake_get_domain_manager(self, session, controller_id, product, attr_name):
        return domain_mgrs[(product, attr_name)]

    fake_cm = MagicMock()
    fake_cm.site = "default"
    fake_cm.set_site = AsyncMock()

    async def _fake_get_connection_manager(self, session, controller_id, product):
        return fake_cm

    monkeypatch.setattr(
        "unifi_api.services.managers.ManagerFactory.get_domain_manager",
        _fake_get_domain_manager,
    )
    monkeypatch.setattr(
        "unifi_api.services.managers.ManagerFactory.get_connection_manager",
        _fake_get_connection_manager,
    )

    return call_counts


# ---------------------------------------------------------------------------
# Test 1 — flat list query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_clients_flat_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_clients = [
        {"mac": "aa:bb:cc:dd:ee:01", "hostname": "alpha", "is_online": True, "ap_mac": "ap:01"},
        {"mac": "aa:bb:cc:dd:ee:02", "hostname": "beta", "is_online": False, "ap_mac": "ap:02"},
        {"mac": "aa:bb:cc:dd:ee:03", "hostname": "gamma", "is_online": True, "ap_mac": "ap:01"},
    ]
    _stub_managers(monkeypatch, clients=fixture_clients)

    headers = {"Authorization": f"Bearer {key}"}
    query = (
        f'{{ network {{ clients(controller: "{cid}", limit: 10) {{ items {{ mac hostname status }} nextCursor }} }} }}'
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["network"]["clients"]["items"]
        assert len(items) == 3
        assert {it["hostname"] for it in items} == {"alpha", "beta", "gamma"}
        assert {it["status"] for it in items} == {"online", "offline"}


# ---------------------------------------------------------------------------
# Test 2 — deep query with relationship edge (Client.device)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_clients_with_device_edge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_clients = [
        {"mac": "aa:bb:cc:dd:ee:01", "hostname": "alpha", "ap_mac": "ap:01"},
    ]
    fixture_devices = [
        {"mac": "ap:01", "name": "Living-Room-AP", "model": "U7PRO"},
    ]
    counts = _stub_managers(monkeypatch, clients=fixture_clients, devices=fixture_devices)

    headers = {"Authorization": f"Bearer {key}"}
    query = f'''{{
      network {{
        clients(controller: "{cid}", limit: 5) {{
          items {{
            mac
            hostname
            device {{ mac name model }}
          }}
        }}
      }}
    }}'''
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["network"]["clients"]["items"]
        assert len(items) == 1
        assert items[0]["device"]["name"] == "Living-Room-AP"
        assert items[0]["device"]["model"] == "U7PRO"
        # Both manager methods called exactly once (request cache deduplication)
        assert counts["get_clients"] == 1
        assert counts["get_devices"] == 1


# ---------------------------------------------------------------------------
# Test 3 — cross-resource query (clients + devices + networks in one round-trip)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_cross_resource_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_clients = [{"mac": "aa:01", "hostname": "alpha"}]
    fixture_devices = [{"mac": "ap:01", "name": "AP-1", "model": "U7PRO"}]
    fixture_networks = [{"_id": "net-1", "name": "Trusted"}]
    _stub_managers(
        monkeypatch,
        clients=fixture_clients,
        devices=fixture_devices,
        networks=fixture_networks,
    )

    headers = {"Authorization": f"Bearer {key}"}
    query = f'''{{
      network {{
        clients(controller: "{cid}", limit: 5) {{ items {{ mac }} }}
        devices(controller: "{cid}", limit: 5) {{ items {{ mac name }} }}
        networks(controller: "{cid}", limit: 5) {{ items {{ id name }} }}
      }}
    }}'''
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        net = body["data"]["network"]
        assert net["clients"]["items"][0]["mac"] == "aa:01"
        assert net["devices"]["items"][0]["name"] == "AP-1"
        assert net["networks"]["items"][0]["name"] == "Trusted"


# ---------------------------------------------------------------------------
# Test 4 — pagination with cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_clients_pagination(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    # 5 clients with monotonically increasing last_seen so paginate() (descending)
    # produces a deterministic ordering across pages.
    fixture_clients = [{"mac": f"aa:{i:02x}", "hostname": f"c{i}", "last_seen": 1000 + i} for i in range(5)]
    _stub_managers(monkeypatch, clients=fixture_clients)

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Page 1: limit=2, cursor=null
        q1 = f'{{ network {{ clients(controller: "{cid}", limit: 2) {{ items {{ mac }} nextCursor }} }} }}'
        r1 = await c.post("/v1/graphql", headers=headers, json={"query": q1})
        body1 = r1.json()
        assert body1.get("errors") is None, body1
        page1_macs = [it["mac"] for it in body1["data"]["network"]["clients"]["items"]]
        next_cursor = body1["data"]["network"]["clients"]["nextCursor"]
        assert len(page1_macs) == 2
        assert next_cursor is not None

        # Page 2: limit=2, cursor=<page 1's nextCursor>
        q2 = (
            f'{{ network {{ clients(controller: "{cid}", limit: 2, cursor: "{next_cursor}") '
            f"{{ items {{ mac }} nextCursor }} }} }}"
        )
        r2 = await c.post("/v1/graphql", headers=headers, json={"query": q2})
        body2 = r2.json()
        assert body2.get("errors") is None, body2
        page2_macs = [it["mac"] for it in body2["data"]["network"]["clients"]["items"]]
        assert len(page2_macs) == 2
        # No overlap between pages
        assert set(page1_macs).isdisjoint(set(page2_macs))


# ---------------------------------------------------------------------------
# Test 5 — auth scope (read-scope key works; no key fails)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_auth_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _admin_key, cid = await _bootstrap(tmp_path)

    # Add a read-scope key
    sm = app.state.sessionmaker
    read_material = generate_key()
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=read_material.prefix,
                hash=hash_key(read_material.plaintext),
                scopes="read",
                name="r",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    _stub_managers(monkeypatch, clients=[{"mac": "aa:01", "hostname": "alpha"}])

    query = f'{{ network {{ clients(controller: "{cid}", limit: 1) {{ items {{ mac }} }} }} }}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Read-scope key works for read fields
        r_read = await c.post(
            "/v1/graphql",
            headers={"Authorization": f"Bearer {read_material.plaintext}"},
            json={"query": query},
        )
        body_read = r_read.json()
        assert body_read.get("errors") is None, body_read
        assert body_read["data"]["network"]["clients"]["items"][0]["mac"] == "aa:01"

        # No key -> errors with FORBIDDEN/UNAUTHENTICATED code
        r_unauth = await c.post("/v1/graphql", json={"query": query})
        body_unauth = r_unauth.json()
        assert body_unauth.get("errors")
        codes = [e.get("extensions", {}).get("code") for e in body_unauth["errors"]]
        assert any(c in ("UNAUTHENTICATED", "FORBIDDEN") for c in codes)
