"""POST /v1/controllers/{id}/probe — live connectivity test."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

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


async def _bootstrap_app(tmp_path: Path, scopes: str = "admin"):
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
                scopes=scopes,
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext


async def _create_controller(client, headers, product_kinds: list[str]) -> str:
    r = await client.post(
        "/v1/controllers",
        headers=headers,
        json={
            "name": "Home",
            "base_url": "https://10.0.0.1",
            "username": "root",
            "password": "hunter2",
            "product_kinds": product_kinds,
            "verify_tls": False,
            "is_default": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.mark.asyncio
async def test_probe_happy_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}

    # Stub _construct_connection_manager to avoid network round-trip.
    async def _stub_construct(self, session, controller_id, product):
        return object()

    monkeypatch.setattr(
        "unifi_api.services.managers.ManagerFactory._construct_connection_manager",
        _stub_construct,
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = await _create_controller(c, headers, ["network", "protect"])
        r = await c.post(f"/v1/controllers/{cid}/probe", headers=headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert set(body["products"].keys()) == {"network", "protect"}
        assert body["products"]["network"]["ok"] is True
        assert body["products"]["protect"]["ok"] is True
        assert body["error_kind"] is None
        assert "last_probed_at" in body


@pytest.mark.asyncio
async def test_probe_requires_admin_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="read")
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # We can't create the controller with read scope, so fabricate a row directly.
        cipher = ColumnCipher(derive_key("k"))
        cred_blob = cipher.encrypt(json.dumps({"username": "u", "password": "p", "api_token": None}).encode("utf-8"))
        async with app.state.sessionmaker() as session:
            session.add(
                Controller(
                    id="c1",
                    name="x",
                    base_url="https://x",
                    product_kinds="network",
                    credentials_blob=cred_blob,
                    verify_tls=True,
                    is_default=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
        r = await c.post("/v1/controllers/c1/probe", headers=headers)
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_probe_unknown_controller_404(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/controllers/nonexistent/probe", headers=headers)
        assert r.status_code == 404
