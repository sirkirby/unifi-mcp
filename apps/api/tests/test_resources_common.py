"""Shared resource-route deps tests."""

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import Depends, HTTPException
from httpx import ASGITransport, AsyncClient
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import Base, Controller
from unifi_api.routes.resources._common import require_capability, resolve_controller


def _cfg(tmp_path):
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


@pytest.mark.asyncio
async def test_resolve_controller_uses_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    from unifi_api.server import create_app

    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    cipher = ColumnCipher(derive_key("k"))
    cid = str(uuid.uuid4())
    async with sm() as session:
        session.add(
            Controller(
                id=cid,
                name="N",
                base_url="https://x",
                product_kinds="network",
                credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    @app.get("/test")
    async def test_endpoint(controller=Depends(resolve_controller)):
        return {"id": controller.id, "name": controller.name}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/test")
    assert r.status_code == 200
    assert r.json()["id"] == cid


def test_require_capability_passes_when_present() -> None:
    class FakeController:
        product_kinds = "network,protect"

    require_capability(FakeController(), "network")  # no exception


def test_require_capability_raises_409_when_missing() -> None:
    class FakeController:
        product_kinds = "network"
        id = "x"

    with pytest.raises(HTTPException) as exc:
        require_capability(FakeController(), "protect")
    assert exc.value.status_code == 409
    assert exc.value.detail["kind"] == "capability_mismatch"
    assert exc.value.detail["missing_product"] == "protect"
