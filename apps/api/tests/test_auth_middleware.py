"""Auth middleware: bearer token resolution + scope enforcement."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.auth.cache import ArgonVerifyCache
from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.db.engine import create_engine
from unifi_api.db.models import ApiKey, Base
from unifi_api.db.session import get_sessionmaker


async def _make_app(tmp_path: Path) -> FastAPI:
    """Build an app that has middleware wired but no seeded key."""
    db_path = tmp_path / "state.db"
    engine = create_engine(db_path)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sm = get_sessionmaker(engine)
    app = FastAPI()
    app.state.sessionmaker = sm
    app.state.argon_cache = ArgonVerifyCache()

    @app.get("/protected", dependencies=[Depends(require_scope(Scope.READ))])
    async def protected():
        return {"ok": True}

    @app.get("/admin-only", dependencies=[Depends(require_scope(Scope.ADMIN))])
    async def admin_only():
        return {"ok": True}

    return app


async def _seed_key(app: FastAPI, scopes: str) -> str:
    """Create a row in api_keys and return the plaintext token."""
    sm = app.state.sessionmaker
    material = generate_key()
    digest = hash_key(material.plaintext)
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=digest,
                scopes=scopes,
                name="test",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return material.plaintext


@pytest.mark.asyncio
async def test_missing_token_401(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/protected")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_401(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/protected", headers={"Authorization": "Bearer unifi_live_XXXXXXXXXXXXXXXXXXXXXX"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_with_required_scope_200(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    plaintext = await _seed_key(app, scopes="read")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_insufficient_scope_403(tmp_path: Path) -> None:
    app = await _make_app(tmp_path)
    plaintext = await _seed_key(app, scopes="read")
    # /admin-only requires admin; the seeded key only has read
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/admin-only", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_cache_hit_skips_argon2(tmp_path: Path) -> None:
    """Two consecutive requests with same key should hit cache on second call."""
    app = await _make_app(tmp_path)
    plaintext = await _seed_key(app, scopes="read")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r1 = await c.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
        r2 = await c.get("/protected", headers={"Authorization": f"Bearer {plaintext}"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert app.state.argon_cache.get(plaintext) is not None
