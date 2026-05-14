"""Capability probe + cache tests."""

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import ApiKey, Base
from unifi_api.server import create_app
from unifi_api.services.capability_cache import CapabilityCache


def test_cache_get_and_put() -> None:
    c = CapabilityCache(ttl_seconds=60)
    c.put("cid1", {"products": ["network"]})
    assert c.get("cid1") == {"products": ["network"]}


def test_cache_ttl_expires() -> None:
    c = CapabilityCache(ttl_seconds=1)
    c.put("cid1", {"x": 1})
    time.sleep(1.2)
    assert c.get("cid1") is None


def test_cache_invalidate() -> None:
    c = CapabilityCache(ttl_seconds=60)
    c.put("cid1", {"x": 1})
    c.invalidate("cid1")
    assert c.get("cid1") is None


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap(tmp_path: Path):
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    material = generate_key()
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
        await session.commit()
    return app, material.plaintext


@pytest.mark.asyncio
async def test_capabilities_endpoint_returns_payload(tmp_path, monkeypatch) -> None:
    """End-to-end /v1/controllers/{id}/capabilities with mocked probe."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}

    # Patch the probe at its source module
    from unifi_api.services import controllers as ctrl_svc

    async def _fake_probe(controller):
        return {
            "id": controller.id,
            "name": controller.name,
            "base_url": controller.base_url,
            "products": ["network"],
            "version": {"controller": "9.0.108", "firmware": None},
            "v2_api": True,
            "sites": [],
            "known_quirks": [],
            "probed_at": "now",
            "probe_error": None,
        }

    monkeypatch.setattr(ctrl_svc, "probe_capabilities", _fake_probe)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/v1/controllers",
            headers=headers,
            json={
                "name": "X",
                "base_url": "https://x",
                "username": "u",
                "password": "p",
                "product_kinds": ["network"],
                "verify_tls": False,
                "is_default": True,
            },
        )
        cid = r.json()["id"]
        r = await c.get(f"/v1/controllers/{cid}/capabilities", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["products"] == ["network"]
        # Second call uses cache (we don't expose hit/miss flag, just confirm same response)
        r2 = await c.get(f"/v1/controllers/{cid}/capabilities", headers=headers)
        assert r2.json() == body
