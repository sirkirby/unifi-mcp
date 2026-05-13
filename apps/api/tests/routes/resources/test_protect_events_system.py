"""Phase 5A PR3 Cluster 2 — protect events + recordings + liveviews + system.

Covers 9 endpoint families across 4 route modules:
- events.py extends with detail/thumbnail/recent-events/smart-detections
- recordings.py extends with /recording-status
- liveviews.py (new) — LIST + filter-from-list DETAIL
- system.py (new) — /firmware-status, /alarm-status, /alarm-profiles,
  /protect/health, /protect/system-info, /viewers
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


async def _bootstrap(tmp_path, products="protect"):
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
                name="P",
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


class _FakeProtectCM:
    """Stub protect connection manager — no set_site (single-controller-no-site)."""

    async def initialize(self) -> None:
        return None


def _stub_connection(app, cid: str) -> _FakeProtectCM:
    fake = _FakeProtectCM()
    app.state.manager_factory._connection_cache[(cid, "protect")] = fake
    return fake


# ---------------------------------------------------------------------------
# Smart detections — EVENT_LOG list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_smart_detections_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_events = [
        {
            "id": f"sd-{i}",
            "type": "smartDetectZone",
            "start": 1700000000 + i,
            "score": 90,
            "smart_detect_types": ["person"],
            "camera_id": "cam-1",
            "recognized_person_id": "face-group-1",
            "recognized_person_name": "Assigned Person",
        }
        for i in range(3)
    ]

    async def fake(self, *a, **kw):
        return fake_events

    from unifi_core.protect.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "list_smart_detections", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/smart-detections?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["items"][0]["recognized_person_name"] == "Assigned Person"
    assert body["render_hint"]["kind"] == "event_log"


# ---------------------------------------------------------------------------
# Recent events — DETAIL pass-through (buffer wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recent_events_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    def fake_buffer(self, *a, **kw):
        return [
            {"id": "ev-1", "type": "motion", "recognized_person_name": "Assigned Person"},
            {"id": "ev-2", "type": "ring"},
        ]

    from unifi_core.protect.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_recent_from_buffer", fake_buffer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/recent-events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["render_hint"]["kind"] == "detail"
    assert body["data"]["count"] == 2
    assert len(body["data"]["events"]) == 2
    assert body["data"]["events"][0]["recognized_person_name"] == "Assigned Person"


# ---------------------------------------------------------------------------
# Event detail + thumbnail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_event_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "id": "ev-1",
        "type": "motion",
        "start": 1700000000,
        "end": 1700000010,
        "camera_id": "cam-1",
        "score": 88,
        "recognized_person_id": "face-group-1",
        "recognized_person_name": "Assigned Person",
        "recognized_person_confidence": 94,
        "detected_thumbnail_id": "crop-1",
    }

    async def fake(self, event_id):
        assert event_id == "ev-1"
        return payload

    from unifi_core.protect.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_event", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/events/ev-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["id"] == "ev-1"
    assert body["data"]["recognized_person_name"] == "Assigned Person"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_event_404_via_unifi_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake(self, event_id):
        raise UniFiNotFoundError("event", event_id)

    from unifi_core.protect.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_event", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/events/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_event_thumbnail_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "event_id": "ev-1",
        "thumbnail_id": "thumb-abc",
        "thumbnail_available": True,
        "image_base64": "Zm9v",
        "content_type": "image/jpeg",
    }

    async def fake(self, event_id, width=None, height=None):
        return payload

    from unifi_core.protect.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "get_event_thumbnail", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/event-thumbnails/ev-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["event_id"] == "ev-1"
    assert body["data"]["thumbnail_available"] is True
    assert body["render_hint"]["kind"] == "detail"


# ---------------------------------------------------------------------------
# Recording status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_recording_status_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "cameras": [
            {
                "camera_id": "cam-1",
                "name": "Door",
                "recording_mode": "always",
                "is_recording": True,
            }
        ],
        "count": 1,
    }

    async def fake(self, camera_id=None):
        return payload

    from unifi_core.protect.managers.recording_manager import RecordingManager

    monkeypatch.setattr(RecordingManager, "get_recording_status", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/recording-status?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["count"] == 1
    assert body["render_hint"]["kind"] == "detail"


# ---------------------------------------------------------------------------
# Liveviews — LIST + filter-from-list DETAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_liveviews_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_lvs = [
        {
            "id": "lv-1",
            "name": "Main",
            "is_default": True,
            "is_global": False,
            "layout": 4,
            "owner_id": "u-1",
            "slots": [],
            "slot_count": 0,
            "camera_count": 0,
        },
        {
            "id": "lv-2",
            "name": "Outdoor",
            "is_default": False,
            "is_global": True,
            "layout": 9,
            "owner_id": "u-1",
            "slots": [],
            "slot_count": 0,
            "camera_count": 0,
        },
    ]

    async def fake(self):
        return fake_lvs

    from unifi_core.protect.managers.liveview_manager import LiveviewManager

    monkeypatch.setattr(LiveviewManager, "list_liveviews", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/liveviews?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_liveview_filter_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_lvs = [
        {
            "id": "lv-1",
            "name": "Main",
            "is_default": True,
            "is_global": False,
            "layout": 4,
            "owner_id": "u-1",
            "slots": [],
            "slot_count": 0,
            "camera_count": 0,
        }
    ]

    async def fake(self):
        return fake_lvs

    from unifi_core.protect.managers.liveview_manager import LiveviewManager

    monkeypatch.setattr(LiveviewManager, "list_liveviews", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/liveviews/lv-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/liveviews/lv-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert ok.status_code == 200
    assert ok.json()["data"]["id"] == "lv-1"
    assert ok.json()["render_hint"]["kind"] == "detail"
    assert miss.status_code == 404


# ---------------------------------------------------------------------------
# System: firmware-status / alarm-status / alarm-profiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_firmware_status_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "nvr": {"id": "nvr-1", "name": "Studio", "current_firmware": "3.0", "version": "3.0", "is_updating": False},
        "devices": [],
        "total_devices": 0,
        "devices_with_updates": 0,
    }

    async def fake(self):
        return payload

    from unifi_core.protect.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "get_firmware_status", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/firmware-status?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["nvr"]["id"] == "nvr-1"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_alarm_get_status_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "armed": False,
        "status": "disabled",
        "active_profile_id": "p-1",
        "active_profile_name": "Home",
        "armed_at": None,
        "will_be_armed_at": None,
        "breach_detected_at": None,
        "breach_event_count": 0,
        "profiles": [],
    }

    async def fake(self):
        return payload

    from unifi_core.protect.managers.alarm_manager import AlarmManager

    monkeypatch.setattr(AlarmManager, "get_arm_state", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/alarm-status?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["status"] == "disabled"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_alarm_list_profiles_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_profiles = [
        {"id": "p-1", "name": "Home"},
        {"id": "p-2", "name": "Away"},
    ]

    async def fake(self):
        return fake_profiles

    from unifi_core.protect.managers.alarm_manager import AlarmManager

    monkeypatch.setattr(AlarmManager, "list_arm_profiles", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/alarm-profiles?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2


# ---------------------------------------------------------------------------
# Protect health + system-info (product-prefixed paths)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protect_health_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "cpu": {"average_load": 12.5, "temperature_c": 50.0},
        "memory": {"available_bytes": 1, "free_bytes": 2, "total_bytes": 3},
        "storage": {
            "available_bytes": 1,
            "size_bytes": 2,
            "used_bytes": 3,
            "is_recycling": False,
            "type": "hdd",
        },
        "is_updating": False,
        "uptime_seconds": 3600,
    }

    async def fake(self):
        return payload

    from unifi_core.protect.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "get_health", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/protect/health?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["cpu"]["average_load"] == 12.5
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_protect_system_info_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "id": "nvr-1",
        "name": "Studio",
        "model": "UDM-Pro",
        "firmware_version": "3.0",
        "version": "3.0",
        "uptime_seconds": 3600,
        "camera_count": 4,
    }

    async def fake(self):
        return payload

    from unifi_core.protect.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "get_system_info", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/protect/system-info?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["id"] == "nvr-1"
    assert body["render_hint"]["kind"] == "detail"


# ---------------------------------------------------------------------------
# Viewers — LIST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_viewers_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_viewers = [
        {
            "id": "v-1",
            "name": "Lobby",
            "type": "viewer",
            "mac": "ff:ee:dd:cc:bb:aa",
            "host": "10.0.0.5",
            "firmware_version": "1.0",
            "is_connected": True,
            "is_updating": False,
            "uptime_seconds": 100,
            "state": "CONNECTED",
            "software_version": "1.0",
            "liveview_id": "lv-1",
        }
    ]

    async def fake(self):
        return fake_viewers

    from unifi_core.protect.managers.system_manager import SystemManager

    monkeypatch.setattr(SystemManager, "list_viewers", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/viewers?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == "v-1"


@pytest.mark.asyncio
async def test_list_viewers_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")  # no protect

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/viewers?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "protect"
