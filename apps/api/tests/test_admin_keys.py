"""Phase 5B PR2 Task 16 — admin /admin/keys list/create/revoke."""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.db.models import ApiKey, Base
from unifi_api.server import create_app


def _cfg(tmp_path: Path) -> ApiConfig:
    return ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
    )


async def _bootstrap_app_with_admin_key(tmp_path: Path):
    app = create_app(_cfg(tmp_path))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = app.state.sessionmaker
    material = generate_key()
    key_id = str(uuid.uuid4())
    async with sm() as session:
        session.add(
            ApiKey(
                id=key_id,
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="admin",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return app, material.plaintext, material.prefix, key_id


@pytest.mark.asyncio
async def test_keys_page_shell_renders_unauth_and_table_fragment_lists_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Page route is unauth (vanilla nav can't carry the localStorage Bearer);
    the table-body fragment is admin-scoped and contains the actual rows."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, prefix, _ = await _bootstrap_app_with_admin_key(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1. Page shell: anonymous, returns 200 + the HTMX-driven shell
        r = await c.get("/admin/keys")
        assert r.status_code == 200
        assert "API keys" in r.text
        assert 'hx-get="/admin/keys/_table"' in r.text
        assert prefix not in r.text  # rows aren't inlined — they come from the fragment
        assert r.headers.get("cache-control") == "no-store"
        # 2. Unauth fragment fetch: 401
        r = await c.get("/admin/keys/_table")
        assert r.status_code == 401
        # 3. Admin-Bearer fragment fetch: rows present
        r = await c.get("/admin/keys/_table", headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200
        assert prefix in r.text


@pytest.mark.asyncio
async def test_keys_create_returns_modal_with_plaintext(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, _, _ = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/admin/keys/create",
            headers=headers,
            data={"name": "robot", "scopes": "read"},
        )
        assert r.status_code == 200
        body = r.text
        match = re.search(r"unifi_live_[A-Z2-7]{22}", body)
        assert match is not None, f"no plaintext key found in body: {body!r}"
        plaintext = match.group(0)
        assert "copy it now" in body
        # OOB tbody refresh contains the new prefix
        new_prefix = plaintext[:15]
        assert new_prefix in body
    # Confirm the row is in the DB
    sm = app.state.sessionmaker
    async with sm() as session:
        rows = (await session.execute(select(ApiKey).where(ApiKey.name == "robot"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].prefix == new_prefix
        assert rows[0].scopes == "read"


@pytest.mark.asyncio
async def test_keys_revoke_returns_200_empty_body(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, _, key_id = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/admin/keys/{key_id}/revoke", headers=headers)
        assert r.status_code == 200
        assert r.text == ""
    sm = app.state.sessionmaker
    async with sm() as session:
        row = await session.get(ApiKey, key_id)
        assert row is not None
        assert row.revoked_at is not None
