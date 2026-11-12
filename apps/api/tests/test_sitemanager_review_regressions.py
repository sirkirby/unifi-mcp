"""Executable regressions for controller compatibility and cloud management boundaries."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from starlette.requests import Request
from unifi_api.db.models import AuditLog, Controller, SiteManagerConnection
from unifi_api.services import sitemanager_connections
from unifi_api.services.controllers import update_controller
from unifi_api.services.sitemanager_connections import associated_data

from tests.test_controllers_routes import _bootstrap_app
from tests.test_sitemanager_connections import KEY

URL = "/v1/sitemanager/connection"
CONSOLE = {
    "name": "Console",
    "base_url": "https://192.0.2.1",
    "product_kinds": ["network"],
    "api_token": "synthetic-console-original",
}


async def legacy_controller(app):
    now = datetime.now(timezone.utc)
    row = Controller(
        id="synthetic-legacy-console",
        name="Legacy",
        base_url="https://192.0.2.1",
        product_kinds="network,sitemanager",
        credentials_blob=app.state.cipher.encrypt(
            json.dumps({"username": "", "password": "", "api_token": "synthetic-console-original"}).encode()
        ),
        verify_tls=True,
        is_default=False,
        created_at=now,
        updated_at=now,
    )
    async with app.state.sessionmaker() as session:
        session.add(row)
        await session.commit()
    return row


@pytest.mark.asyncio
async def test_empty_product_controller_accepts_credential_only_patch(tmp_path, monkeypatch, cloud_secrecy_guard):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post("/v1/controllers", headers=headers, json={**CONSOLE, "product_kinds": []})
            assert created.status_code == 201
            response = await client.patch(
                "/v1/controllers/" + created.json()["id"],
                headers=headers,
                json={"api_token": "synthetic-console-replacement"},
            )
            assert response.status_code == 200
            assert response.json()["product_kinds"] == []
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_stored_legacy_kinds_accept_credential_update_without_revalidation(
    tmp_path, monkeypatch, cloud_secrecy_guard
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    row = await legacy_controller(app)
    try:
        async with app.state.sessionmaker() as session:
            updated = await update_controller(
                session, app.state.cipher, row.id, api_token="synthetic-console-replacement"
            )
            await session.commit()
            assert updated.product_kinds == "network,sitemanager"
            assert json.loads(app.state.cipher.decrypt(updated.credentials_blob)) == {
                "username": "",
                "password": "",
                "api_token": "synthetic-console-replacement",
            }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.patch(
                "/v1/controllers/" + row.id,
                headers={"Authorization": f"Bearer {key}"},
                json={"api_token": "synthetic-console-second-replacement"},
            )
            assert response.status_code == 200
            assert response.json()["product_kinds"] == ["network", "sitemanager"]
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("listing", [True, False])
async def test_stored_legacy_kinds_remain_readable(tmp_path, monkeypatch, listing, cloud_secrecy_guard):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    row = await legacy_controller(app)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            response = await client.get(
                "/v1/controllers" + ("" if listing else "/" + row.id), headers={"Authorization": f"Bearer {key}"}
            )
            assert response.status_code == 200
            data = response.json()
            if listing:
                assert len(data) == 1
                data = data[0]
            assert data["product_kinds"] == ["network", "sitemanager"]
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_console_unknown_fields_still_ignored_on_create_and_patch(tmp_path, monkeypatch, cloud_secrecy_guard):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    extras = {"id": "caller-supplied-id", "created_at": "caller-supplied-timestamp", "site_manager_api_key": KEY}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/controllers", headers=headers, json={**CONSOLE, **extras})
            assert response.status_code == 201
            created = response.json()
            assert created["id"] != extras["id"] and created["created_at"] != extras["created_at"]
            response = await client.patch(
                "/v1/controllers/" + created["id"],
                headers=headers,
                json={**created, "name": "Renamed", "site_manager_api_key": KEY},
            )
            assert response.status_code == 200
            assert response.json()["name"] == "Renamed"
            cloud_secrecy_guard(response.text)
        async with app.state.sessionmaker() as session:
            row = await session.get(Controller, created["id"])
            assert json.loads(app.state.cipher.decrypt(row.credentials_blob)) == {
                "username": "",
                "password": "",
                "api_token": "synthetic-console-original",
            }
            assert (await session.scalars(select(SiteManagerConnection))).all() == []
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["rotation", "delete"])
async def test_postcommit_close_failure_cannot_change_success_or_audit(
    tmp_path, monkeypatch, caplog, operation, cloud_secrecy_guard
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (
                await client.post(URL, headers=headers, json={"name": "Account", "site_manager_api_key": KEY})
            ).status_code == 201
            async with app.state.sitemanager_factory.acquire() as cached:
                cached.connection.close = AsyncMock(side_effect=RuntimeError(KEY))
            if operation == "rotation":
                response = await client.patch(
                    URL, headers=headers, json={"site_manager_api_key": "synthetic-rotated-cloud-key"}
                )
                assert response.status_code == 200
                assert response.json()["revision"] == 2
            else:
                response = await client.delete(URL, headers=headers)
                assert response.status_code == 204
        async with app.state.sessionmaker() as session:
            rows = (await session.scalars(select(SiteManagerConnection))).all()
            if operation == "rotation":
                assert len(rows) == 1
                assert rows[0].revision == 2
                assert (
                    app.state.cipher.decrypt(rows[0].api_key_blob, associated_data=associated_data(rows[0].id))
                    == b"synthetic-rotated-cloud-key"
                )
            else:
                assert rows == []
            audit = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
            assert len(audit) == 2
            assert [row.outcome for row in audit] == ["success", "success"]
            assert audit[1].target == "sitemanager.connection." + ("update" if operation == "rotation" else "delete")
        cached.connection.close.assert_awaited_once()
        cloud_secrecy_guard(caplog.text)
        cloud_secrecy_guard(response.text)
        if operation == "rotation":
            cloud_secrecy_guard(response.text, key="synthetic-rotated-cloud-key")
            cloud_secrecy_guard(caplog.text, key="synthetic-rotated-cloud-key")
        assert "RuntimeError" in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
    finally:
        await app.state.sitemanager_factory.close()
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_delete_between_account_read_and_update_returns_not_configured(
    tmp_path, monkeypatch, cloud_secrecy_guard
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    original = sitemanager_connections.get_connection
    deleted = []

    async def read_then_delete(session):
        row = await original(session)
        async with app.state.sessionmaker() as other:
            await other.execute(delete(SiteManagerConnection).where(SiteManagerConnection.id == row.id))
            await other.commit()
        deleted.append(row.id)
        return row

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            assert (
                await client.post(URL, headers=headers, json={"name": "Account", "site_manager_api_key": KEY})
            ).status_code == 201
            monkeypatch.setattr(sitemanager_connections, "get_connection", read_then_delete)
            response = await client.patch(URL, headers=headers, json={"name": "Renamed"})
            assert len(deleted) == 1
            assert response.status_code == 404
            assert response.json()["detail"]["kind"] == "sitemanager_not_configured"
        async with app.state.sessionmaker() as session:
            assert (await session.scalars(select(SiteManagerConnection))).all() == []
            audit = (await session.scalars(select(AuditLog).order_by(AuditLog.id))).all()
            assert len(audit) == 2
            assert audit[1].outcome == "error"
            assert audit[1].error_kind == "sitemanager_not_configured"
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "read", "write"])
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_cloud_authorization_precedes_malformed_body_parsing(
    tmp_path, monkeypatch, scope, method, cloud_secrecy_guard
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes=scope or "admin")
    headers = {"content-type": "application/json"}
    if scope:
        headers["Authorization"] = f"Bearer {key}"
    body_reads = []
    original_body = Request.body

    async def track_body(request):
        body_reads.append(request.url.path)
        return await original_body(request)

    monkeypatch.setattr(Request, "body", track_body)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(method, URL, headers=headers, content=b'{"site_manager_api_key":')
            assert response.status_code == (401 if scope is None else 403)
            assert response.headers["cache-control"] == "no-store"
            assert body_reads == []
        async with app.state.sessionmaker() as session:
            audit = (await session.scalars(select(AuditLog))).all()
            assert len(audit) == 1
            assert audit[0].outcome == "denied"
            assert audit[0].error_kind == ("missing_bearer" if scope is None else "insufficient_scope")
    finally:
        await app.state.engine.dispose()
