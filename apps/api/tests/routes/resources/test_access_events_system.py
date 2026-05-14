"""Phase 5A PR4 Cluster 2 — access events + system.

Covers 6 endpoint families across 2 route modules:

- events.py (new) — /access/events LIST + DETAIL,
  /access/recent-events buffer-snapshot, /access/activity-summary
- system.py (new) — /access/health, /access/system-info
  (product-prefixed paths to disambiguate from network/protect)
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
from unifi_core.exceptions import UniFiNotFoundError


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


# ---------------------------------------------------------------------------
# /access/events — LIST (EVENT_LOG)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_access_events_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_events = [
        {
            "id": f"ev-{i}",
            "type": "access_granted",
            "timestamp": 1700000000 + i,
            "door_id": "door-1",
            "user_id": "u-1",
            "result": "granted",
        }
        for i in range(3)
    ]

    async def fake(self, *a, **kw):
        return fake_events

    from unifi_core.access.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "list_events", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "event_log"


# ---------------------------------------------------------------------------
# /access/events/{event_id} — DETAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_access_event_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "id": "ev-1",
        "type": "access_granted",
        "timestamp": 1700000000,
        "door_id": "door-1",
        "user_id": "u-1",
        "result": "granted",
    }

    async def fake(self, event_id):
        assert event_id == "ev-1"
        return payload

    from unifi_core.access.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_event", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/events/ev-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["id"] == "ev-1"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_access_event_404_via_unifi_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake(self, event_id):
        raise UniFiNotFoundError("event", event_id)

    from unifi_core.access.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_event", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/events/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /access/recent-events — buffer snapshot (DETAIL pass-through)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_access_events_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    def fake_buffer(self, *a, **kw):
        return [
            {"id": "ev-1", "type": "access_granted", "door_id": "door-1"},
            {"id": "ev-2", "type": "access_denied", "door_id": "door-1"},
        ]

    from unifi_core.access.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_recent_from_buffer", fake_buffer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/recent-events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # AccessEventSerializer is registered for access_recent_events as
    # EVENT_LOG, but we render the manager's wrapper dict so the route
    # returns DETAIL kind here. Mirror protect's recent-events convention.
    assert body["data"]["count"] == 2
    assert len(body["data"]["events"]) == 2
    assert body["data"]["source"] == "buffer"


# ---------------------------------------------------------------------------
# /access/activity-summary — DETAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_activity_summary_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "since": 1700000000,
        "until": 1700086400,
        "total": 42,
        "granted_count": 30,
        "denied_count": 12,
        "histogram": [{"bucket": 1700000000, "count": 5}],
    }

    async def fake(self, door_id=None, days=7):
        return payload

    from unifi_core.access.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_activity_summary", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/activity-summary?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["total_events"] == 42
    assert body["data"]["granted_count"] == 30
    assert body["render_hint"]["kind"] == "detail"


# ---------------------------------------------------------------------------
# /access/health — DETAIL (product-prefixed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_health_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "host": "1.2.3.4",
        "is_connected": True,
        "api_client_available": True,
        "proxy_available": True,
        "api_client_healthy": True,
        "proxy_healthy": True,
    }

    async def fake(self):
        return payload

    from unifi_core.access.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "get_health", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/health?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["status"] == "healthy"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_access_health_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")  # no access

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/health?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["missing_product"] == "access"


# ---------------------------------------------------------------------------
# /access/system-info — DETAIL (product-prefixed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_access_system_info_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "name": "Access Hub",
        "version": "2.5.0",
        "hostname": "access.local",
        "uptime": 12345,
    }

    async def fake(self):
        return payload

    from unifi_core.access.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "get_system_info", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access/system-info?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["name"] == "Access Hub"
    assert body["data"]["version"] == "2.5.0"
    assert body["render_hint"]["kind"] == "detail"
