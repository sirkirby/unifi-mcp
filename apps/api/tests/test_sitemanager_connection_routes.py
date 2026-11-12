"""Management authorization, privacy, lazy creation and explicit probe contracts."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import ApiKey, AuditLog, SiteManagerConnection
from unifi_api.services import sitemanager_management as management
from unifi_core.exceptions import UniFiAuthError
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager

from tests.test_controllers_routes import _bootstrap_app
from tests.test_sitemanager_connections import KEY

URL = "/v1/sitemanager/connection"


@pytest.mark.asyncio
async def test_crud_metadata_no_upstream_and_rotation(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    calls = AsyncMock(side_effect=AssertionError("Unexpected upstream request"))
    monkeypatch.setattr(InventoryManager, "list_hosts", calls)
    app, key = await _bootstrap_app(tmp_path)
    factory = app.state.sitemanager_factory
    factory.invalidate = AsyncMock(wraps=factory.invalidate)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get(URL, headers=headers)
        assert missing.status_code == 404
        created = await client.post(URL, headers=headers, json={"name": "Account", "site_manager_api_key": KEY})
        assert created.status_code == 201, created.text
        data = created.json()
        assert set(data) == {"id", "name", "key_configured", "revision", "created_at", "updated_at"}
        assert data["revision"] == 1 and data["key_configured"] is True
        assert (await client.get(URL, headers=headers)).json() == data
        conflict = await client.post(URL, headers=headers, json={"name": "Other", "site_manager_api_key": KEY})
        assert conflict.status_code == 409
        renamed = await client.patch(URL, headers=headers, json={"name": "Renamed"})
        assert renamed.json()["revision"] == 2
        noop = await client.patch(URL, headers=headers, json={})
        assert noop.json() == renamed.json()
        deleted = await client.delete(URL, headers=headers)
        assert deleted.status_code == 204
        assert (await client.get(URL, headers=headers)).status_code == 404
        responses = [missing, created, conflict, renamed, noop, deleted]
        assert len(responses) == 6
        for response in responses:
            assert response.headers["cache-control"] == "no-store"
            assert KEY not in response.text
    calls.assert_not_awaited()
    assert factory.invalidate.await_count == 3
    async with app.state.sessionmaker() as session:
        rows = (await session.scalars(select(AuditLog).where(AuditLog.target.like("sitemanager.%")))).all()
        assert len(rows) == 5
        assert [row.outcome for row in rows] == ["success", "error", "success", "success", "success"]
        assert all(row.controller is None and row.detail is None for row in rows)
        assert KEY not in str([row.__dict__ for row in rows])
    assert KEY not in caplog.text
    await factory.close()
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST", "PATCH", "DELETE", "PROBE"])
@pytest.mark.parametrize("scope", [None, "read", "write", "revoked"])
async def test_admin_required_before_factory(tmp_path, monkeypatch, method, scope):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes="admin" if scope in (None, "revoked") else scope)
    if scope == "revoked":
        from datetime import datetime, timezone

        async with app.state.sessionmaker() as session:
            row = (await session.scalars(select(ApiKey))).one()
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()
    factory = app.state.sitemanager_factory
    factory.acquire = AsyncMock(side_effect=AssertionError("Denied acquire"))
    factory.isolated = AsyncMock(side_effect=AssertionError("Denied probe"))
    headers = {} if scope is None else {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(
            "POST" if method == "PROBE" else method,
            URL + ("/probe" if method == "PROBE" else ""),
            headers=headers,
            json={"name": "Account", "site_manager_api_key": KEY},
        )
        assert response.status_code == (401 if scope in (None, "revoked") else 403)
        assert response.headers["cache-control"] == "no-store"
        assert KEY not in response.text
    factory.acquire.assert_not_called()
    factory.isolated.assert_not_called()
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, "", " ", 42])
async def test_rejected_key_is_not_echoed_and_cannot_change_row(tmp_path, monkeypatch, caplog, bad):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(URL, headers=headers, json={"name": "Account", "site_manager_api_key": KEY})
        before = (await client.get(URL, headers=headers)).json()
        for patch in ({"site_manager_api_key": bad}, {KEY: KEY}, {"base_url": KEY}, {"api_token": KEY}, {"name": None}):
            response = await client.patch(URL, headers=headers, json=patch)
            assert response.status_code == 422
            assert response.json()["detail"]["kind"] == "invalid_sitemanager_request"
            assert KEY not in response.text
        assert (await client.get(URL, headers=headers)).json() == before
    assert KEY not in caplog.text
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("fails", [False, True])
async def test_explicit_probe_closes_isolated_connection(tmp_path, monkeypatch, caplog, fails):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    from unifi_api.services import sitemanager_managers as managers

    connections = []

    class FakeConnection:
        def __init__(self, *, api_key):
            assert api_key == KEY
            self.initialize = AsyncMock()
            self.close = AsyncMock()
            connections.append(self)

    monkeypatch.setattr(managers, "SiteManagerConnectionManager", FakeConnection)
    probe = (
        AsyncMock(side_effect=UniFiAuthError(KEY)) if fails else AsyncMock(return_value=([{"secret": KEY}], "token"))
    )
    monkeypatch.setattr(InventoryManager, "list_hosts", probe)
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(URL, headers=headers, json={"name": "Account", "site_manager_api_key": KEY})
        assert connections == []
        async with app.state.sitemanager_factory.acquire() as active:
            response = await client.post(URL + "/probe", headers=headers)
            assert response.status_code == (502 if fails else 200)
            assert response.json()["ok"] is not fails
            assert response.json()["error_kind"] == ("sitemanager_auth_failed" if fails else None)
            assert KEY not in response.text
            active.connection.close.assert_not_awaited()
            assert len(connections) == 2
            connections[1].close.assert_awaited_once()
    probe.assert_awaited_once_with(page_size=1)
    assert KEY not in caplog.text
    await app.state.sitemanager_factory.close()
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_connection_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    actual = management.write_audit

    async def fail_success(session, **kwargs):
        if kwargs["outcome"] == "success":
            raise RuntimeError(KEY)
        return await actual(session, **kwargs)

    monkeypatch.setattr(management, "write_audit", fail_success)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            URL, headers={"Authorization": f"Bearer {key}"}, json={"name": "Account", "site_manager_api_key": KEY}
        )
    assert response.status_code == 500
    assert KEY not in response.text
    async with app.state.sessionmaker() as session:
        assert (await session.scalars(select(SiteManagerConnection))).all() == []
        audits = (await session.scalars(select(AuditLog))).all()
        assert len(audits) == 1
        assert audits[0].outcome == "error"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_cloud_audit_json_admin_csv_and_subscriber_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    from unifi_api.services.audit import add_audit_subscriber

    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    events = []
    unsubscribe = add_audit_subscriber(events.append)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            created = await client.post(URL, headers=headers, json={"name": "Account", "site_manager_api_key": KEY})
            cid = created.json()["id"]
            response = await client.get("/v1/audit", headers=headers, params={"sitemanager_connection": cid})
            rows = response.json()["items"]
            assert len(rows) == 1
            assert rows[0]["sitemanager_connection"] == cid
            assert rows[0]["controller"] is None
            assert (
                await client.get("/v1/audit", headers=headers, params={"sitemanager_connection": "other-local-id"})
            ).json()["items"] == []
            for path in ("/admin/audit/_rows", "/admin/audit/export.csv"):
                rendered = await client.get(path, headers=headers, params={"sitemanager_connection": cid})
                assert rendered.status_code == 200
                assert cid in rendered.text
                assert KEY not in rendered.text
                excluded = await client.get(path, headers=headers, params={"sitemanager_connection": "other-local-id"})
                assert cid not in excluded.text
            from unifi_api.routes.admin.audit import _make_filter_fn

            filtered = _make_filter_fn(outcome=None, q=None, sitemanager_connection=cid)
            assert len(events) == 1
            assert events[0]["sitemanager_connection"] == cid
            assert filtered(events[0]) is True
            assert filtered({"sitemanager_connection": "other-local-id"}) is False
            assert KEY not in str(events)
    finally:
        unsubscribe()
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_cloud_key_misplaced_in_bearer_is_never_prefixed_in_audit(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, _ = await _bootstrap_app(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(URL, headers={"Authorization": f"Bearer {KEY}"})
        assert response.status_code == 401
        assert KEY not in response.text
    async with app.state.sessionmaker() as session:
        rows = (await session.scalars(select(AuditLog))).all()
        assert len(rows) == 1
        assert rows[0].key_id_prefix == "(unverified)"
    assert KEY not in caplog.text
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_total_audit_failure_is_safe_and_fail_visible(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    monkeypatch.setattr(management, "write_audit", AsyncMock(side_effect=RuntimeError(KEY)))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            URL, headers={"Authorization": f"Bearer {key}"}, json={"name": "Account", "site_manager_api_key": KEY}
        )
        assert response.status_code == 500
        assert response.headers["cache-control"] == "no-store"
        assert KEY not in response.text
    assert KEY not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    async with app.state.sessionmaker() as session:
        assert (await session.scalars(select(SiteManagerConnection))).all() == []
    await app.state.engine.dispose()
