"""CI gate: deep query produces constant manager call count regardless of
result cardinality.

PR1 baseline: only the smoke `health` field exists, so this gate just
asserts the framework (`RequestCache` dedupe within one request) is wired
correctly. PR2/3/4 add real deep-query call-count assertions once
network/protect/access resolvers exist.
"""

import asyncio

import pytest
from unifi_api.graphql.context import RequestCache


@pytest.mark.asyncio
async def test_request_cache_dedupes_within_one_query() -> None:
    """Two resolvers in one query reaching the same manager call share one fetch.

    Constructed at PR1 against the RequestCache directly. PR2 augments this
    with a real deep-query call-count test once network resolvers exist.
    """
    cache = RequestCache()
    fetches = 0

    async def _fetch():
        nonlocal fetches
        fetches += 1
        return ["client_a", "client_b", "client_c"]

    a, b = await asyncio.gather(
        cache.get_or_fetch("network/clients/cid1", _fetch),
        cache.get_or_fetch("network/clients/cid1", _fetch),
    )
    assert a == b
    assert fetches == 1, "RequestCache failed to dedupe — N+1 risk"


@pytest.mark.asyncio
async def test_deep_network_query_makes_constant_manager_calls(
    tmp_path,
    monkeypatch,
) -> None:
    """Phase 6 PR2.5 — deep query with N clients × their device makes exactly
    2 manager calls (one for clients, one for devices). The request cache
    prevents N×M fan-out across the relationship edge.
    """
    import json
    import uuid
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from httpx import ASGITransport, AsyncClient
    from unifi_api.auth.api_key import generate_key, hash_key
    from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
    from unifi_api.db.crypto import ColumnCipher, derive_key
    from unifi_api.db.models import ApiKey, Base, Controller
    from unifi_api.server import create_app

    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    cfg = ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )
    app = create_app(cfg)
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

    # 10 clients all hanging off the same AP
    fixture_clients = [{"mac": f"aa:bb:cc:dd:ee:{i:02x}", "hostname": f"c{i}", "ap_mac": "ap:01"} for i in range(10)]
    fixture_devices = [{"mac": "ap:01", "name": "AP-1", "model": "U7PRO"}]

    counts = {"get_clients": 0, "get_devices": 0}

    async def _stub_get_clients():
        counts["get_clients"] += 1
        return fixture_clients

    async def _stub_get_devices():
        counts["get_devices"] += 1
        return fixture_devices

    fake_client_mgr = MagicMock()
    fake_client_mgr.get_clients = _stub_get_clients
    fake_device_mgr = MagicMock()
    fake_device_mgr.get_devices = _stub_get_devices
    fake_cm = MagicMock()
    fake_cm.site = "default"
    fake_cm.set_site = AsyncMock()

    async def _fake_get_domain_manager(self, session, controller_id, product, attr_name):
        if attr_name == "client_manager":
            return fake_client_mgr
        if attr_name == "device_manager":
            return fake_device_mgr
        return MagicMock()

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

    query = f'''{{
      network {{
        clients(controller: "{cid}", limit: 10) {{
          items {{
            mac
            device {{ mac name model }}
          }}
        }}
      }}
    }}'''

    headers = {"Authorization": f"Bearer {material.plaintext}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["network"]["clients"]["items"]
        assert len(items) == 10
        # All 10 clients resolved their device — no fan-out
        assert all(it["device"]["name"] == "AP-1" for it in items)

    # The keystone N+1 assertion
    assert counts["get_clients"] == 1, f"expected 1 client snapshot fetch, got {counts['get_clients']}"
    assert counts["get_devices"] == 1, (
        f"expected 1 device snapshot fetch (cache should dedupe), got {counts['get_devices']}"
    )
