"""Phase 6 PR3 Task G — end-to-end protect GraphQL queries.

Five representative consumer flows (flat list, deep relationship edge,
cross-resource fan-in, pagination, auth scope). Mirrors the network e2e
sibling in ``test_query_e2e_network.py``.
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
    """Bootstrap an admin-keyed app with one protect controller seeded."""
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
                product_kinds="protect",
                credentials_blob=cred_blob,
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, cid


def _stub_protect_managers(
    monkeypatch,
    *,
    cameras: list[Any] | None = None,
    chimes: list[Any] | None = None,
    lights: list[Any] | None = None,
    sensors: list[Any] | None = None,
    liveviews: list[Any] | None = None,
    events: list[Any] | None = None,
    recordings: list[Any] | None = None,
) -> dict[str, int]:
    """Patch ManagerFactory.get_domain_manager / get_connection_manager so
    protect resolvers see preconfigured fixture data.

    Returns a per-method call counter dict for N+1 assertions.
    """
    call_counts: dict[str, int] = {
        "list_cameras": 0,
        "list_chimes": 0,
        "list_lights": 0,
        "list_sensors": 0,
        "list_liveviews": 0,
        "list_events": 0,
        "list_recordings": 0,
    }

    async def _stub_list_cameras():
        call_counts["list_cameras"] += 1
        return cameras or []

    async def _stub_list_chimes():
        call_counts["list_chimes"] += 1
        return chimes or []

    async def _stub_list_lights():
        call_counts["list_lights"] += 1
        return lights or []

    async def _stub_list_sensors():
        call_counts["list_sensors"] += 1
        return sensors or []

    async def _stub_list_liveviews():
        call_counts["list_liveviews"] += 1
        return liveviews or []

    async def _stub_list_events(*args, **kwargs):
        call_counts["list_events"] += 1
        return events or []

    async def _stub_list_recordings(*args, **kwargs):
        call_counts["list_recordings"] += 1
        return recordings or []

    fake_camera_mgr = MagicMock()
    fake_camera_mgr.list_cameras = _stub_list_cameras
    fake_chime_mgr = MagicMock()
    fake_chime_mgr.list_chimes = _stub_list_chimes
    fake_light_mgr = MagicMock()
    fake_light_mgr.list_lights = _stub_list_lights
    fake_sensor_mgr = MagicMock()
    fake_sensor_mgr.list_sensors = _stub_list_sensors
    fake_liveview_mgr = MagicMock()
    fake_liveview_mgr.list_liveviews = _stub_list_liveviews
    fake_event_mgr = MagicMock()
    fake_event_mgr.list_events = _stub_list_events
    fake_recording_mgr = MagicMock()
    fake_recording_mgr.list_recordings = _stub_list_recordings

    domain_mgrs = {
        ("protect", "camera_manager"): fake_camera_mgr,
        ("protect", "chime_manager"): fake_chime_mgr,
        ("protect", "light_manager"): fake_light_mgr,
        ("protect", "sensor_manager"): fake_sensor_mgr,
        ("protect", "liveview_manager"): fake_liveview_mgr,
        ("protect", "event_manager"): fake_event_mgr,
        ("protect", "recording_manager"): fake_recording_mgr,
    }

    async def _fake_get_domain_manager(self, session, controller_id, product, attr_name):
        return domain_mgrs.get((product, attr_name), MagicMock())

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
# Test 1 — flat list query (cameras)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_cameras_flat_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_cameras = [
        {"id": "cam1", "name": "Front Door", "model": "G4_PRO"},
        {"id": "cam2", "name": "Garage", "model": "G5_FLEX"},
    ]
    _stub_protect_managers(monkeypatch, cameras=fixture_cameras)

    headers = {"Authorization": f"Bearer {key}"}
    query = f'{{ protect {{ cameras(controller: "{cid}") {{ items {{ id name model }} nextCursor }} }} }}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["protect"]["cameras"]["items"]
        assert len(items) == 2
        assert {it["name"] for it in items} == {"Front Door", "Garage"}


# ---------------------------------------------------------------------------
# Test 2 — deep query with relationship edge (Camera.events)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_camera_with_events_edge(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_cameras = [{"id": "cam1", "name": "Front Door", "model": "G4_PRO"}]
    # Camera.events resolver filters raw events by `camera_id` matching the
    # camera's id (the serializer renames camera_id -> camera on the typed
    # Event object). Fixture rows therefore carry `camera_id`.
    fixture_events = [
        {"id": "evt1", "type": "motion", "camera_id": "cam1"},
        {"id": "evt2", "type": "person", "camera_id": "cam1"},
        {"id": "evt3", "type": "motion", "camera_id": "cam2"},  # different camera
    ]
    _stub_protect_managers(
        monkeypatch,
        cameras=fixture_cameras,
        events=fixture_events,
    )

    headers = {"Authorization": f"Bearer {key}"}
    query = f'''{{
      protect {{
        cameras(controller: "{cid}") {{
          items {{
            id
            name
            events {{ id type }}
          }}
        }}
      }}
    }}'''
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        items = body["data"]["protect"]["cameras"]["items"]
        assert len(items) == 1
        cam_events = items[0]["events"]
        assert len(cam_events) == 2
        assert {e["type"] for e in cam_events} == {"motion", "person"}


# ---------------------------------------------------------------------------
# Test 3 — cross-resource query (cameras + chimes + lights in one round-trip)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_cross_resource_query(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_cameras = [{"id": "cam1", "name": "Front Door"}]
    fixture_chimes = [{"id": "chime1", "name": "Doorbell"}]
    fixture_lights = [{"id": "light1", "name": "Porch"}]
    _stub_protect_managers(
        monkeypatch,
        cameras=fixture_cameras,
        chimes=fixture_chimes,
        lights=fixture_lights,
    )

    headers = {"Authorization": f"Bearer {key}"}
    query = f'''{{
      protect {{
        cameras(controller: "{cid}") {{ items {{ id name }} }}
        chimes(controller: "{cid}") {{ items {{ id name }} }}
        lights(controller: "{cid}") {{ items {{ id name }} }}
      }}
    }}'''
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/graphql", headers=headers, json={"query": query})
        assert r.status_code == 200
        body = r.json()
        assert body.get("errors") is None, body
        protect = body["data"]["protect"]
        assert protect["cameras"]["items"][0]["name"] == "Front Door"
        assert protect["chimes"]["items"][0]["name"] == "Doorbell"
        assert protect["lights"]["items"][0]["name"] == "Porch"


# ---------------------------------------------------------------------------
# Test 4 — pagination with cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_cameras_pagination(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)

    fixture_cameras = [{"id": f"cam{i:03d}", "name": f"Camera {i}"} for i in range(5)]
    _stub_protect_managers(monkeypatch, cameras=fixture_cameras)

    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Page 1: limit=2, cursor=null
        q1 = f'{{ protect {{ cameras(controller: "{cid}", limit: 2) {{ items {{ id }} nextCursor }} }} }}'
        r1 = await c.post("/v1/graphql", headers=headers, json={"query": q1})
        body1 = r1.json()
        assert body1.get("errors") is None, body1
        page1_ids = [it["id"] for it in body1["data"]["protect"]["cameras"]["items"]]
        next_cursor = body1["data"]["protect"]["cameras"]["nextCursor"]
        assert len(page1_ids) == 2
        assert next_cursor is not None

        # Page 2: limit=2, cursor=<page 1's nextCursor>
        q2 = (
            f'{{ protect {{ cameras(controller: "{cid}", limit: 2, cursor: "{next_cursor}") '
            f"{{ items {{ id }} nextCursor }} }} }}"
        )
        r2 = await c.post("/v1/graphql", headers=headers, json={"query": q2})
        body2 = r2.json()
        assert body2.get("errors") is None, body2
        page2_ids = [it["id"] for it in body2["data"]["protect"]["cameras"]["items"]]
        assert len(page2_ids) == 2
        # No overlap between pages
        assert set(page1_ids).isdisjoint(set(page2_ids))


# ---------------------------------------------------------------------------
# Test 5 — auth scope (read-scope key works; no key fails)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_auth_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _admin_key, cid = await _bootstrap(tmp_path)

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

    _stub_protect_managers(
        monkeypatch,
        cameras=[{"id": "cam1", "name": "Front"}],
    )

    query = f'{{ protect {{ cameras(controller: "{cid}", limit: 1) {{ items {{ id }} }} }} }}'
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # Read-scope key works for read fields
        r_read = await c.post(
            "/v1/graphql",
            headers={"Authorization": f"Bearer {read_material.plaintext}"},
            json={"query": query},
        )
        body_read = r_read.json()
        assert body_read.get("errors") is None, body_read
        assert body_read["data"]["protect"]["cameras"]["items"][0]["id"] == "cam1"

        # No bearer -> errors with FORBIDDEN/UNAUTHENTICATED code
        r_unauth = await c.post("/v1/graphql", json={"query": query})
        body_unauth = r_unauth.json()
        assert body_unauth.get("errors")
        codes = [e.get("extensions", {}).get("code") for e in body_unauth["errors"]]
        assert any(code in ("UNAUTHENTICATED", "FORBIDDEN") for code in codes)
