"""Phase 5A PR4 Cluster 2 — access events + system.

Covers 6 endpoint families across 2 route modules:

- events.py (new) — /access/events LIST + DETAIL,
  /access/recent-events buffer-snapshot, /access/activity-summary
- system.py (new) — /access/health, /access/system-info
  (product-prefixed paths to disambiguate from network/protect)
"""

import base64
import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, Base, Controller
from unifi_api.server import create_app
from unifi_api.services.pagination import Cursor
from unifi_core.access.models.events import event_identity, with_event_identity
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

    has_proxy = True

    def __init__(self) -> None:
        self.response = {"data": {"events": []}, "total": 0}

    async def proxy_request(self, *args, **kwargs):
        return self.response

    @staticmethod
    def extract_data(response):
        return response.get("data", response)


def _stub_connection(app, cid: str) -> _FakeAccessCM:
    fake = _FakeAccessCM()
    app.state.manager_factory._connection_cache[(cid, "access", None)] = fake
    return fake


def _legacy_event_key(row: dict) -> tuple:
    """The exact Access REST ordering key used before timestamp normalization."""
    return (row.get("timestamp") or row.get("time") or 0, row.get("id") or "")


def _legacy_cursor(row: dict) -> str:
    timestamp, identity = _legacy_event_key(row)
    return Cursor(last_id=identity, last_ts=timestamp).encode()


def _cursor_payload(cursor: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())


def _migration_rows(timestamp_format: str) -> tuple[list[dict], dict]:
    if timestamp_format == "published":
        rows = [
            {
                "id": "",
                "log_key": "access.door.unlock",
                "event_type": "access.door.unlock",
                "message": f"row {index}",
                "published": 1787054400000 + offset,
            }
            for index, offset in enumerate((1000, 0, -1000))
        ]
        return rows, with_event_identity(rows[1])
    if timestamp_format == "seconds":
        rows = [{"id": f"evt-{index}", "timestamp": 1787054400 + offset} for index, offset in enumerate((1, 0, -1))]
    elif timestamp_format == "millis":
        rows = [
            {"id": f"evt-{index}", "timestamp": 1787054400000 + offset} for index, offset in enumerate((1000, 0, -1000))
        ]
    else:
        rows = [
            {"id": "evt-0", "timestamp": "2026-08-18T12:00:01Z"},
            {"id": "evt-1", "timestamp": "2026-08-18T12:00:00Z"},
            {"id": "evt-2", "timestamp": "2026-08-18T11:59:59Z"},
        ]
    return rows, rows[1]


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


@pytest.mark.asyncio
async def test_list_access_events_cursor_traverses_empty_native_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    cm = _stub_connection(app, cid)
    cm.response = {
        "total": 2,
        "data": {
            "events": [
                {
                    "id": "",
                    "published": 1773766800123,
                    "event_type": "access.admin.update",
                    "metadata": {"user": {"id": "user-1"}},
                },
                {
                    "id": "",
                    "published": 1773766800123,
                    "event_type": "access.admin.update",
                    "metadata": {"user": {"id": "user-2"}},
                },
            ]
        },
    }

    seen: list[str] = []
    cursor = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        while True:
            suffix = f"&cursor={cursor}" if cursor else ""
            response = await c.get(
                f"/v1/sites/default/access/events?controller={cid}&limit=1{suffix}",
                headers={"Authorization": f"Bearer {key}"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            seen.extend(item["id"] for item in body["items"])
            cursor = body["next_cursor"]
            if cursor is None:
                break

    assert len(seen) == 2
    assert all(seen)
    assert len(set(seen)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("timestamp_format", ["published", "seconds", "millis", "iso"])
async def test_list_access_events_resumes_legacy_cursor(tmp_path, monkeypatch, timestamp_format) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    cm = _stub_connection(app, cid)
    rows, legacy_target = _migration_rows(timestamp_format)
    cm.response = {"total": len(rows), "data": {"events": rows}}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/access/events?controller={cid}",
            params={"limit": 10, "cursor": _legacy_cursor(legacy_target)},
            headers={"Authorization": f"Bearer {key}"},
        )

    assert response.status_code == 200, response.text
    returned_ids = [item["id"] for item in response.json()["items"]]
    expected_older_id = event_identity(rows[2])
    assert returned_ids == [expected_older_id]
    assert len(returned_ids) == len(set(returned_ids))
    assert event_identity(rows[0]) not in returned_ids
    assert event_identity(rows[1]) not in returned_ids


@pytest.mark.asyncio
async def test_list_access_events_issues_versioned_resource_cursor(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    cm = _stub_connection(app, cid)
    rows, _ = _migration_rows("seconds")
    cm.response = {"total": len(rows), "data": {"events": rows}}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/access/events?controller={cid}",
            params={"limit": 1},
            headers={"Authorization": f"Bearer {key}"},
        )

    assert response.status_code == 200, response.text
    payload = _cursor_payload(response.json()["next_cursor"])
    assert payload["resource"] == "access_events"
    assert payload["version"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cursor", "expected_detail"),
    [
        (Cursor(last_id="missing", last_ts="not-a-time").encode(), "timestamp is unrecoverable"),
        (
            base64.urlsafe_b64encode(
                json.dumps({"resource": "access_events", "version": 99, "last_id": "evt", "last_ts": 1}).encode()
            ).decode(),
            "unsupported Access event cursor version",
        ),
        (
            base64.urlsafe_b64encode(
                json.dumps({"resource": "network_events", "version": 1, "last_id": "evt", "last_ts": 1}).encode()
            ).decode(),
            "unknown resource format",
        ),
        ("not-base64", "invalid Access event cursor"),
    ],
)
async def test_list_access_events_rejects_unrecoverable_cursor(
    tmp_path,
    monkeypatch,
    cursor,
    expected_detail,
) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/sites/default/access/events?controller={cid}",
            params={"cursor": cursor},
            headers={"Authorization": f"Bearer {key}"},
        )

    assert response.status_code == 400
    assert expected_detail in response.json()["detail"]


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
