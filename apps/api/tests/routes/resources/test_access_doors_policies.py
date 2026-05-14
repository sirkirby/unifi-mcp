"""Phase 5A PR4 Cluster 1 — access doors+policies+schedules+devices+visitors.

Covers 8 endpoint families:
- doors/{id}/status (nested)        — access_get_door_status
- door-groups (LIST)                — access_list_door_groups
- policies LIST + DETAIL            — access_list_policies, access_get_policy
- schedules LIST                    — access_list_schedules
- access-devices LIST + DETAIL      — access_list_devices, access_get_device
- visitors LIST + DETAIL            — access_list_visitors, access_get_visitor
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
# door status (nested)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_door_status_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    status = {
        "id": "door-1",
        "name": "Lobby",
        "door_position_status": "open",
        "lock_relay_status": "unlocked",
    }

    async def fake_status(self, door_id):
        if door_id == "door-1":
            return status
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("door", door_id)

    from unifi_core.access.managers.door_manager import DoorManager

    monkeypatch.setattr(DoorManager, "get_door_status", fake_status)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/doors/door-1/status?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["door_id"] == "door-1"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_door_status_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_status(self, door_id):
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("door", door_id)

    from unifi_core.access.managers.door_manager import DoorManager

    monkeypatch.setattr(DoorManager, "get_door_status", fake_status)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/doors/missing/status?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# door-groups (LIST only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_door_groups_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    groups = [{"id": f"grp-{i}", "name": f"Group {i}", "type": "door"} for i in range(3)]

    async def fake_list(self):
        return groups

    from unifi_core.access.managers.door_manager import DoorManager

    monkeypatch.setattr(DoorManager, "list_door_groups", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/door-groups?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"


# ---------------------------------------------------------------------------
# policies LIST + DETAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_policies_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    policies = [{"id": f"pol-{i}", "name": f"Policy {i}", "resource_type": "door"} for i in range(4)]

    async def fake_list(self):
        return policies

    from unifi_core.access.managers.policy_manager import PolicyManager

    monkeypatch.setattr(PolicyManager, "list_policies", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/policies?controller={cid}&limit=2",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"] is not None
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_list_policies_capability_mismatch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, products="network")  # no access

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/policies?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 409
    assert r.json()["detail"]["missing_product"] == "access"


@pytest.mark.asyncio
async def test_get_policy_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"id": "pol-1", "name": "Front Door", "resource_type": "door"}

    async def fake_get(self, policy_id):
        if policy_id == "pol-1":
            return target
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("policy", policy_id)

    from unifi_core.access.managers.policy_manager import PolicyManager

    monkeypatch.setattr(PolicyManager, "get_policy", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/policies/pol-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["id"] == "pol-1"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_policy_404_via_unifi_not_found(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, policy_id):
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("policy", policy_id)

    from unifi_core.access.managers.policy_manager import PolicyManager

    monkeypatch.setattr(PolicyManager, "get_policy", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/policies/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# schedules LIST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_schedules_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    schedules = [{"id": f"sch-{i}", "name": f"Sched {i}", "type": "weekly"} for i in range(3)]

    async def fake_list(self):
        return schedules

    from unifi_core.access.managers.policy_manager import PolicyManager

    monkeypatch.setattr(PolicyManager, "list_schedules", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/schedules?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"


# ---------------------------------------------------------------------------
# access-devices LIST + DETAIL (product-prefixed path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_access_devices_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    devices = [{"id": f"dev-{i}", "name": f"Reader {i}", "device_type": "UA-Hub"} for i in range(3)]

    async def fake_list(self, *a, **kw):
        return devices

    from unifi_core.access.managers.device_manager import DeviceManager

    monkeypatch.setattr(DeviceManager, "list_devices", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access-devices?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_access_device_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"id": "dev-1", "name": "Reader 1", "device_type": "UA-Hub"}

    async def fake_get(self, device_id):
        if device_id == "dev-1":
            return target
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("device", device_id)

    from unifi_core.access.managers.device_manager import DeviceManager

    monkeypatch.setattr(DeviceManager, "get_device", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access-devices/dev-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["data"]["id"] == "dev-1"
    assert body["render_hint"]["kind"] == "detail"


@pytest.mark.asyncio
async def test_get_access_device_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    async def fake_get(self, device_id):
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("device", device_id)

    from unifi_core.access.managers.device_manager import DeviceManager

    monkeypatch.setattr(DeviceManager, "get_device", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/access-devices/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# visitors LIST + DETAIL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_visitors_happy_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    visitors = [{"id": f"vis-{i}", "name": f"Visitor {i}", "status": "active"} for i in range(3)]

    async def fake_list(self):
        return visitors

    from unifi_core.access.managers.visitor_manager import VisitorManager

    monkeypatch.setattr(VisitorManager, "list_visitors", fake_list)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(
            f"/v1/sites/default/visitors?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["items"]) == 3
    assert body["render_hint"]["kind"] == "list"


@pytest.mark.asyncio
async def test_get_visitor_happy_and_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)

    target = {"id": "vis-1", "name": "Alice", "status": "active"}

    async def fake_get(self, visitor_id):
        if visitor_id == "vis-1":
            return target
        from unifi_core.exceptions import UniFiNotFoundError

        raise UniFiNotFoundError("visitor", visitor_id)

    from unifi_core.access.managers.visitor_manager import VisitorManager

    monkeypatch.setattr(VisitorManager, "get_visitor", fake_get)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        ok = await c.get(
            f"/v1/sites/default/visitors/vis-1?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )
        miss = await c.get(
            f"/v1/sites/default/visitors/missing?controller={cid}",
            headers={"Authorization": f"Bearer {key}"},
        )

    assert ok.status_code == 200, ok.text
    assert ok.json()["data"]["id"] == "vis-1"
    assert ok.json()["render_hint"]["kind"] == "detail"
    assert miss.status_code == 404
