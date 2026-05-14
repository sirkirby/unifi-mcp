"""Phase 5A PR3 Cluster 1 — protect cameras (extension) + lights + sensors + chimes.

Per-camera analytics/streams/snapshot are nested under /cameras/{id}/* (the one
intentional flat-layout exception). Lights and sensors expose LIST + DETAIL
(filter-from-list since the protect managers don't expose dedicated get_*
methods for these device families). Chimes expose LIST only.
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
# Cameras — nested analytics / streams / snapshot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_camera_analytics_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "camera_id": "cam-1",
        "camera_name": "Door",
        "detections": {"is_motion_detected": False},
        "smart_detects": {},
        "smart_audio_detects": {},
        "currently_detected": {},
        "motion_zone_count": 2,
        "smart_detect_zone_count": 1,
        "stats": {},
    }

    async def fake(self, camera_id):
        assert camera_id == "cam-1"
        return payload

    from unifi_core.protect.managers.camera_manager import CameraManager

    monkeypatch.setattr(CameraManager, "get_camera_analytics", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/cameras/cam-1/analytics?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["camera_id"] == "cam-1"
    assert body["data"]["motion_zone_count"] == 2
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_camera_streams_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    payload = {
        "camera_id": "cam-1",
        "camera_name": "Door",
        "channels": {"high": {"channel_id": 0}},
        "rtsps_streams": {"high": "rtsps://x/abc"},
    }

    async def fake(self, camera_id):
        return payload

    from unifi_core.protect.managers.camera_manager import CameraManager

    monkeypatch.setattr(CameraManager, "get_camera_streams", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/cameras/cam-1/streams?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["camera_id"] == "cam-1"
    assert body["data"]["rtsps_streams"]["high"] == "rtsps://x/abc"


@pytest.mark.asyncio
async def test_get_camera_snapshot_returns_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_jpeg = b"\xff\xd8" + b"\x00" * 1024 + b"\xff\xd9"

    async def fake(self, camera_id, width=None, height=None):
        return fake_jpeg

    from unifi_core.protect.managers.camera_manager import CameraManager

    monkeypatch.setattr(CameraManager, "get_snapshot", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/cameras/cam-1/snapshot?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # SnapshotSerializer surfaces metadata, not raw bytes.
    assert body["data"]["size_bytes"] == len(fake_jpeg)
    assert body["data"]["content_type"] == "image/jpeg"
    assert body["data"]["captured_at"] is not None
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_camera_analytics_404_via_unifi_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake(self, camera_id):
        raise UniFiNotFoundError("camera", camera_id)

    from unifi_core.protect.managers.camera_manager import CameraManager

    monkeypatch.setattr(CameraManager, "get_camera_analytics", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/cameras/missing/analytics?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# Lights — LIST + DETAIL (filter-from-list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_lights_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_lights = [
        {
            "id": f"light-{i}",
            "mac": f"aa:bb:cc:00:00:0{i}",
            "name": f"Light {i}",
            "model": "FloodLight",
            "state": "CONNECTED",
            "is_pir_motion_detected": False,
            "is_light_on": (i % 2 == 0),
        }
        for i in range(3)
    ]

    async def fake_list(self, *a, **kw):
        return fake_lights

    from unifi_core.protect.managers.light_manager import LightManager

    monkeypatch.setattr(LightManager, "list_lights", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/lights?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"
    assert {item["id"] for item in body["items"]} == {"light-0", "light-1", "light-2"}


@pytest.mark.asyncio
async def test_list_lights_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")  # no protect

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/lights?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "protect"


@pytest.mark.asyncio
async def test_get_light_filter_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_lights = [
        {
            "id": "light-1",
            "mac": "aa:bb:cc:00:00:01",
            "name": "Garage",
            "model": "FloodLight",
            "state": "CONNECTED",
            "is_pir_motion_detected": False,
            "is_light_on": True,
        },
    ]

    async def fake_list(self, *a, **kw):
        return fake_lights

    from unifi_core.protect.managers.light_manager import LightManager

    monkeypatch.setattr(LightManager, "list_lights", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/lights/light-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/lights/light-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["id"] == "light-1"
    assert ok.json()["render_hint"]["kind"] == "detail"
    assert miss.status_code == 404


# ---------------------------------------------------------------------------
# Sensors — LIST + DETAIL (filter-from-list)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_sensors_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_sensors = [
        {
            "id": f"sen-{i}",
            "mac": f"dd:ee:ff:00:00:0{i}",
            "name": f"Sensor {i}",
            "type": "ups",
            "battery": {"status": "normal"},
            "stats": {"humidity": {"status": "normal"}, "light": {"status": "normal"}},
            "motion_detected_at": None,
        }
        for i in range(2)
    ]

    async def fake_list(self, *a, **kw):
        return fake_sensors

    from unifi_core.protect.managers.sensor_manager import SensorManager

    monkeypatch.setattr(SensorManager, "list_sensors", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/sensors?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_sensor_filter_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_sensors = [
        {
            "id": "sen-1",
            "mac": "dd:ee:ff:00:00:01",
            "name": "Closet",
            "type": "ups",
            "battery": {"status": "normal"},
            "stats": {},
            "motion_detected_at": None,
        }
    ]

    async def fake_list(self, *a, **kw):
        return fake_sensors

    from unifi_core.protect.managers.sensor_manager import SensorManager

    monkeypatch.setattr(SensorManager, "list_sensors", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/sensors/sen-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/sensors/sen-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["id"] == "sen-1"
    assert miss.status_code == 404


# ---------------------------------------------------------------------------
# Chimes — LIST only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_chimes_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_chimes = [
        {
            "id": "chime-1",
            "mac": "11:22:33:44:55:66",
            "name": "Front Chime",
            "model": "Chime",
            "type": "chime",
            "state": "CONNECTED",
            "is_connected": True,
            "firmware_version": "1.0.0",
            "volume": 80,
            "camera_ids": ["cam-1"],
            "ring_settings": [],
            "available_tracks": [],
        }
    ]

    async def fake_list(self, *a, **kw):
        return fake_chimes

    from unifi_core.protect.managers.chime_manager import ChimeManager

    monkeypatch.setattr(ChimeManager, "list_chimes", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/chimes?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["paired_cameras"] == ["cam-1"]
    assert body["render_hint"]["kind"] == "list"
