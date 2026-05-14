"""Per-resource SSE stream endpoints — path-bound resource id filtering.

These narrow streams reuse the Phase 4B SubscriberPool + sse_event_stream
infrastructure with the new filter_fn parameter (Task 19). Each route binds a
filter that drops events not matching the path-bound resource id.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

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


async def _bootstrap(tmp_path, products):
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


class _FakeMgr:
    """Manager stub: replay buffer + add_subscriber registration."""

    def __init__(self, buffer: list[dict]) -> None:
        self._buffer = buffer

    def get_recent_from_buffer(self) -> list[dict]:
        return list(self._buffer)

    def add_subscriber(self, cb):
        return lambda: None


def _make_finite_stream():
    """Build a finite sse_event_stream replacement that respects filter_fn.

    httpx.ASGITransport.aiter_bytes() blocks on infinite generators (Phase 4B
    workaround), so we yield only filtered replay frames and stop.
    """

    async def fake_stream(**kwargs):
        manager = kwargs["manager"]
        ser = kwargs["serializer"]
        product = kwargs["product"]
        filter_fn = kwargs.get("filter_fn")
        for evt in manager.get_recent_from_buffer():
            if filter_fn is not None and not filter_fn(evt):
                continue
            payload = ser.serialize(evt)
            yield (
                f"event: {product}.event\nid: {evt.get('id')}\ndata: {json.dumps(payload, default=str)}\n\n"
            ).encode()

    return fake_stream


@pytest.mark.asyncio
async def test_stream_protect_camera_events_filters_by_camera_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")

    cam_a = "AAAAAAAAAAAA"
    cam_b = "BBBBBBBBBBBB"
    fake_mgr = _FakeMgr(
        buffer=[
            {"id": "e1", "type": "motion", "camera_id": cam_a, "start": 1700000000000},
            {"id": "e2", "type": "motion", "camera_id": cam_b, "start": 1700000001000},
            {"id": "e3", "type": "ring", "camera_id": cam_a, "start": 1700000002000},
        ],
    )
    app.state.manager_factory.get_domain_manager = AsyncMock(return_value=fake_mgr)

    from unifi_api.routes.streams import protect_per_camera as route_mod

    monkeypatch.setattr(route_mod, "sse_event_stream", _make_finite_stream())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/streams/protect/cameras/{cam_a}/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "id: e1" in body
    assert "id: e3" in body
    assert "id: e2" not in body
    assert "event: protect.event" in body


@pytest.mark.asyncio
async def test_stream_access_door_events_filters_by_door_id(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="access")

    door_a = "door-aaaa"
    door_b = "door-bbbb"
    fake_mgr = _FakeMgr(
        buffer=[
            {"id": "a1", "event": "access.granted", "door_id": door_a, "ts": 1700000000},
            {"id": "a2", "event": "access.denied", "door_id": door_b, "ts": 1700000001},
            {"id": "a3", "event": "access.granted", "door_id": door_a, "ts": 1700000002},
        ],
    )
    app.state.manager_factory.get_domain_manager = AsyncMock(return_value=fake_mgr)

    from unifi_api.routes.streams import access_per_door as route_mod

    monkeypatch.setattr(route_mod, "sse_event_stream", _make_finite_stream())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/streams/access/doors/{door_a}/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "id: a1" in body
    assert "id: a3" in body
    assert "id: a2" not in body
    assert "event: access.event" in body


@pytest.mark.asyncio
async def test_stream_network_device_events_filters_by_mac(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")

    mac_a = "aa:bb:cc:dd:ee:01"
    mac_b = "aa:bb:cc:dd:ee:02"
    fake_mgr = _FakeMgr(
        buffer=[
            {"id": "n1", "key": "STA_CONNECT", "mac": mac_a, "time": 1700000000},
            {"id": "n2", "key": "STA_CONNECT", "mac": mac_b, "time": 1700000001},
            {"id": "n3", "key": "STA_DISCONNECT", "mac": mac_a, "time": 1700000002},
        ],
    )
    app.state.manager_factory.get_domain_manager = AsyncMock(return_value=fake_mgr)

    from unifi_api.routes.streams import network_per_device as route_mod

    monkeypatch.setattr(route_mod, "sse_event_stream", _make_finite_stream())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/streams/network/devices/{mac_a}/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    body = r.text
    assert "id: n1" in body
    assert "id: n3" in body
    assert "id: n2" not in body
    assert "event: network.event" in body
