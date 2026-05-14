"""SSE stream endpoints — capability, auth, content-type/frame shape."""

from __future__ import annotations

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


class _FakeMgr:
    """Tiny manager stub: replay buffer + add_subscriber registration."""

    def __init__(self, buffer: list[dict]) -> None:
        self._buffer = buffer

    def get_recent_from_buffer(self) -> list[dict]:
        # Manager contract: most-recent-first.
        return list(self._buffer)

    def add_subscriber(self, cb):
        # Return an unsub callable; we never invoke cb in this test.
        return lambda: None


@pytest.mark.asyncio
async def test_stream_network_events_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="protect")  # no network

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/streams/network/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "network"


@pytest.mark.asyncio
async def test_stream_network_events_missing_auth(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _key, cid = await _bootstrap(tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/v1/streams/network/events?controller={cid}")
    # Auth middleware raises 401 on missing bearer.
    assert r.status_code == 401, r.text


@pytest.mark.asyncio
async def test_stream_network_events_returns_sse_content_type(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fake_mgr = _FakeMgr(
        buffer=[
            {"id": "e1", "key": "STA_CONNECT", "msg": "client connected", "time": 1700000000},
        ],
    )
    app.state.manager_factory.get_domain_manager = AsyncMock(return_value=fake_mgr)

    # Patch the route's sse_event_stream import to a finite async generator.
    # The route module did `from ... import sse_event_stream`, so we patch the
    # symbol on that module. We assert the route passes the right args through.
    captured: dict = {}

    async def fake_stream(**kwargs):
        captured.update(kwargs)
        ser = kwargs["serializer"]
        for evt in kwargs["manager"].get_recent_from_buffer():
            payload = ser.serialize(evt)
            import json as _json

            yield (
                f"event: {kwargs['product']}.event\nid: {evt.get('id')}\ndata: {_json.dumps(payload, default=str)}\n\n"
            ).encode()

    from unifi_api.routes.streams import network as net_route

    monkeypatch.setattr(net_route, "sse_event_stream", fake_stream)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/streams/network/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    payload = r.text
    assert "event: network.event" in payload
    assert "id: e1" in payload
    # Route plumbed the right product + serializer + controller_id through.
    assert captured["product"] == "network"
    assert captured["controller_id"] == cid
