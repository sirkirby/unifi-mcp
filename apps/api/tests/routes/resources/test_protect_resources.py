"""Protect resource endpoints — happy paths, capability mismatch, 404."""

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


@pytest.mark.asyncio
async def test_list_cameras_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_cams = [
        {
            "id": f"cam-{i}",
            "name": f"Camera {i}",
            "model": "G4 Pro",
            "type": "camera",
            "state": "CONNECTED",
            "is_recording": True,
            "is_motion_detected": False,
            "ip_address": f"10.0.0.{i}",
            "channels": [],
        }
        for i in range(4)
    ]

    async def fake_list(self, *a, **kw):
        return fake_cams

    from unifi_core.protect.managers.camera_manager import CameraManager

    monkeypatch.setattr(CameraManager, "list_cameras", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/cameras?controller={cid}&limit=2",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_list_cameras_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")  # no protect

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/cameras?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["detail"]["kind"] == "capability_mismatch"
    assert body["detail"]["missing_product"] == "protect"


@pytest.mark.asyncio
async def test_get_camera_happy_and_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {
        "id": "cam-1",
        "name": "Door",
        "model": "G4 Doorbell",
        "type": "camera",
        "state": "CONNECTED",
        "is_recording": True,
        "ip_address": "10.0.0.5",
        "channels": [],
    }

    async def fake_get(self, camera_id):
        if camera_id == "cam-1":
            return target
        raise ValueError(f"Camera not found: {camera_id}")

    from unifi_core.protect.managers.camera_manager import CameraManager

    monkeypatch.setattr(CameraManager, "get_camera", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/cameras/cam-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/cameras/cam-999?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["data"]["id"] == "cam-1"
    assert body["render_hint"]["kind"] == "detail"
    assert miss.status_code == 404


@pytest.mark.asyncio
async def test_list_known_faces_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_faces = [
        {
            "id": f"face-{i}",
            "name": f"Person {i}",
            "matched_name": f"Person {i}",
            "type": "face",
            "detections_count": i + 1,
            "last_detected_at": str(1778700000000 + i),
            "metadata": {},
        }
        for i in range(3)
    ]

    async def fake_list(self, *a, **kw):
        return {"faces": fake_faces, "count": len(fake_faces), "links": {}}

    from unifi_core.protect.managers.recognition_manager import RecognitionManager

    monkeypatch.setattr(RecognitionManager, "list_known_faces", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/known-faces?controller={cid}&limit=2",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert {item["id"] for item in body["items"]} == {"face-1", "face-2"}
    assert {item["matched_name"] for item in body["items"]} == {"Person 1", "Person 2"}
    assert body["next_cursor"] is not None
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_list_known_faces_group_types_filter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    calls: list[dict] = []

    async def fake_list(self, *a, **kw):
        calls.append(kw)
        return {
            "faces": [
                {
                    "id": "face-427",
                    "type": "face",
                    "detections_count": 14,
                    "metadata": {},
                }
            ],
            "count": 1,
            "links": {},
        }

    from unifi_core.protect.managers.recognition_manager import RecognitionManager

    monkeypatch.setattr(RecognitionManager, "list_known_faces", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/known-faces?controller={cid}&group_types=unknown",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"][0]["id"] == "face-427"
    assert calls[0]["group_types"] == ["unknown"]


@pytest.mark.asyncio
async def test_list_events_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_events = [
        {
            "id": f"evt-{i}",
            "type": "motion",
            "start": 1700000000 - i,
            "end": 1700000010 - i,
            "score": 50 + i,
            "smart_detect_types": [],
            "camera_id": "cam-1",
            "thumbnail_id": f"thumb-{i}",
        }
        for i in range(3)
    ]

    async def fake_list(self, *a, **kw):
        return fake_events

    from unifi_core.protect.managers.event_manager import EventManager

    monkeypatch.setattr(EventManager, "list_events", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/events?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "event_log"
    assert {item["id"] for item in body["items"]} == {"evt-0", "evt-1", "evt-2"}


@pytest.mark.asyncio
async def test_list_recordings_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_recordings = [
        {
            "id": f"rec-{i}",
            "type": "timelapse",
            "camera_id": "cam-1",
            "start": 1700000000 - i,
            "end": 1700000060 - i,
            "file_size": 1024,
        }
        for i in range(2)
    ]

    async def fake_list(self, camera_id, *a, **kw):
        return fake_recordings

    from unifi_core.protect.managers.recording_manager import RecordingManager

    monkeypatch.setattr(RecordingManager, "list_recordings", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/recordings?controller={cid}&camera_id=cam-1",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_recording_filter_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    fake_recordings = [
        {
            "id": "rec-1",
            "type": "clip",
            "camera_id": "cam-1",
            "start": 1700000000,
            "end": 1700000060,
            "file_size": 1024,
        },
    ]

    async def fake_list(self, camera_id, *a, **kw):
        return fake_recordings

    from unifi_core.protect.managers.recording_manager import RecordingManager

    monkeypatch.setattr(RecordingManager, "list_recordings", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/recordings/rec-1?controller={cid}&camera_id=cam-1",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/recordings/rec-999?controller={cid}&camera_id=cam-1",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["id"] == "rec-1"
    assert miss.status_code == 404
