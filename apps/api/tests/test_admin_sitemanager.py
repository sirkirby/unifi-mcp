"""Admin shell, authorization and secret-free forms and probes."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager

from tests.test_controllers_routes import _bootstrap_app
from tests.test_sitemanager_connections import KEY


@pytest.mark.asyncio
async def test_admin_shell_and_empty_forms_then_crud(tmp_path, monkeypatch, caplog, cloud_secrecy_guard):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        shell = await client.get("/admin/sitemanager")
        assert shell.status_code == 200
        assert 'hx-get="/admin/sitemanager/_connection"' in shell.text
        assert "Account label" not in shell.text
        cloud_secrecy_guard(shell.text)
        empty = await client.get("/admin/sitemanager/_connection", headers=headers)
        assert "No Site Manager" in empty.text
        new = await client.get("/admin/sitemanager/_new_form", headers=headers)
        assert 'type="password"' in new.text and 'value=""' in new.text
        for forbidden in ("base_url", "api_token", "username", "verify_tls", "product_kinds"):
            assert forbidden not in new.text
        created = await client.post(
            "/admin/sitemanager/create", headers=headers, data={"name": "Account label", "site_manager_api_key": KEY}
        )
        assert created.status_code == 200
        assert created.headers["hx-trigger"] == "sitemanager-changed"
        edited = await client.get("/admin/sitemanager/_edit_form", headers=headers)
        assert "Account label" in edited.text
        assert 'name="site_manager_api_key" value=""' in edited.text
        update = await client.post(
            "/admin/sitemanager/update", headers=headers, data={"name": "Renamed", "site_manager_api_key": ""}
        )
        assert update.status_code == 200
        metadata = (await client.get("/v1/sitemanager/connection", headers=headers)).json()
        assert metadata["name"] == "Renamed" and metadata["revision"] == 2
        for bad in ({"base_url": KEY}, {"site_manager_api_key": KEY, "api_token": KEY}):
            rejected = await client.post("/admin/sitemanager/update", headers=headers, data=bad)
            assert rejected.status_code == 422
            cloud_secrecy_guard(rejected.text)
        assert (await client.post("/admin/sitemanager/delete", headers=headers)).status_code == 200
        responses = [shell, empty, new, created, edited, update]
        assert len(responses) == 6
        for response in responses:
            assert response.headers["cache-control"] == "no-store"
            cloud_secrecy_guard(response.text)
    cloud_secrecy_guard(caplog.text)
    await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "read", "write"])
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "_connection"),
        ("GET", "_new_form"),
        ("GET", "_edit_form"),
        ("POST", "create"),
        ("POST", "update"),
        ("POST", "delete"),
        ("POST", "probe"),
    ],
)
async def test_all_fragments_and_actions_require_admin(tmp_path, monkeypatch, scope, method, path, cloud_secrecy_guard):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key = await _bootstrap_app(tmp_path, scopes=scope or "admin")
    headers = {} if scope is None else {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.request(method, "/admin/sitemanager/" + path, headers=headers)
        assert response.status_code == (401 if scope is None else 403)
        assert response.headers["cache-control"] == "no-store"
    await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_admin_probe_discards_account_data(tmp_path, monkeypatch, cloud_secrecy_guard):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    probe = AsyncMock(return_value=([{"name": KEY}], "secret-cursor"))
    monkeypatch.setattr(InventoryManager, "list_hosts", probe)
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/v1/sitemanager/connection", headers=headers, json={"name": "Account", "site_manager_api_key": KEY}
        )
        response = await client.post("/admin/sitemanager/probe", headers=headers)
        assert response.status_code == 200
        assert "Connected" in response.text
        cloud_secrecy_guard(response.text)
        assert "secret-cursor" not in response.text
    probe.assert_awaited_once_with(page_size=1)
    await app.state.sitemanager_factory.close()
    await app.state.engine.dispose()
