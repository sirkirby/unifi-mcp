"""Phase 5B PR2 Task 17 — admin controllers page."""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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


async def _bootstrap_app_with_admin_key(tmp_path: Path):
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


async def _seed_controller(
    app,
    *,
    name: str = "home-net",
    products: str = "network",
    username: str = "user",
    password: str = "pass",
    api_token: str | None = None,
) -> str:
    cipher = ColumnCipher(derive_key("k"))
    cred_blob = cipher.encrypt(
        json.dumps({"username": username, "password": password, "api_token": api_token}).encode("utf-8")
    )
    cid = str(uuid.uuid4())
    async with app.state.sessionmaker() as session:
        session.add(
            Controller(
                id=cid,
                name=name,
                base_url="https://10.0.0.1:443",
                product_kinds=products,
                credentials_blob=cred_blob,
                verify_tls=False,
                is_default=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    return cid


@pytest.mark.asyncio
async def test_controllers_page_shell_renders_unauth_and_table_fragment_lists_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Page route is unauth (vanilla nav can't carry the localStorage Bearer);
    the table-body fragment is admin-scoped and contains the actual rows.
    Decrypted credentials must never appear anywhere in the rendered HTML."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    await _seed_controller(app, name="home-net", products="network,protect", password="hunter2")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 1. Page shell: anonymous, returns 200 + the HTMX-driven shell
        r = await c.get("/admin/controllers")
        assert r.status_code == 200
        assert "Controllers" in r.text
        assert 'hx-get="/admin/controllers/_table"' in r.text
        assert "home-net" not in r.text  # rows aren't inlined — they come from the fragment
        assert r.headers.get("cache-control") == "no-store"
        # 2. Unauth fragment fetch: 401
        r = await c.get("/admin/controllers/_table")
        assert r.status_code == 401
        # 3. Admin-Bearer fragment fetch: rows present, no plaintext creds
        r = await c.get("/admin/controllers/_table", headers={"Authorization": f"Bearer {key}"})
        assert r.status_code == 200
        assert "home-net" in r.text
        assert "https://10.0.0.1:443" in r.text
        assert "hunter2" not in r.text


@pytest.mark.asyncio
async def test_controllers_create_round_trips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            "/admin/controllers/create",
            headers=headers,
            data={
                "name": "added-via-ui",
                "base_url": "https://10.1.1.1:443",
                "username": "u",
                "password": "p",
                "api_token": "",
                "product_kinds": ["network"],
                "verify_tls": "on",
                "is_default": "on",
            },
        )
        assert r.status_code == 200
        # Empty body + HX-Trigger fires the table-body refetch on the client.
        assert r.text == ""
        assert r.headers.get("hx-trigger") == "controllers-changed"
    async with app.state.sessionmaker() as session:
        rows = (await session.execute(select(Controller))).scalars().all()
        match = [rr for rr in rows if rr.name == "added-via-ui"]
        assert len(match) == 1
        assert match[0].is_default is True
        assert match[0].verify_tls is True


@pytest.mark.asyncio
async def test_controllers_edit_with_blank_password_preserves_creds(tmp_path: Path, monkeypatch) -> None:
    """Edit form sent with blank password/username/api_token must NOT clobber existing credentials."""
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    cid = await _seed_controller(
        app,
        name="home",
        username="root",
        password="hunter2",
        api_token="tok",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(
            f"/admin/controllers/{cid}/update",
            headers=headers,
            data={
                "name": "home-renamed",
                "base_url": "https://10.0.0.1:443",
                "username": "",
                "password": "",
                "api_token": "",
                "product_kinds": ["network"],
                "verify_tls": "on",
                "is_default": "",
            },
        )
        assert r.status_code == 200

    cipher = ColumnCipher(derive_key("k"))
    async with app.state.sessionmaker() as session:
        row = await session.get(Controller, cid)
        assert row is not None
        creds = json.loads(cipher.decrypt(row.credentials_blob))
        assert creds["username"] == "root"
        assert creds["password"] == "hunter2"
        assert creds["api_token"] == "tok"
        assert row.name == "home-renamed"
        assert row.verify_tls is True
        assert row.is_default is False


@pytest.mark.asyncio
async def test_controllers_probe_returns_fragment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")

    async def _stub(self, session, controller_id, product):
        return object()

    monkeypatch.setattr(
        "unifi_api.services.managers.ManagerFactory._construct_connection_manager",
        _stub,
    )

    app, key = await _bootstrap_app_with_admin_key(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    cid = await _seed_controller(app, products="network,protect")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post(f"/admin/controllers/{cid}/probe", headers=headers)
        assert r.status_code == 200
        assert "html" in r.headers.get("content-type", "").lower()
        assert "ok" in r.text.lower()
        assert "network" in r.text and "protect" in r.text
