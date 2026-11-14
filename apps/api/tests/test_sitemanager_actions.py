"""Cloud actions share typed reads and remain isolated from console dispatch."""

import copy
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import AuditLog, Controller
from unifi_api.services import actions
from unifi_api.services.actions import CapabilityMismatch
from unifi_api.services.manifest import ManifestRegistry

from tests.sitemanager_data import CASES, TOKEN, bootstrap


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
async def test_all_nine_actions_without_controller_or_site(tmp_path, monkeypatch, case):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/sitemanager/actions/" + case[0],
                headers={"Authorization": f"Bearer {key}"},
                json={"args": copy.deepcopy(case[3])},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["success"] is True
        assert body["render_hint"]["kind"] in {"list", "detail"}
        if case[0] in {"sitemanager_list_hosts", "sitemanager_list_sites", "sitemanager_list_devices"}:
            assert len(body["data"]) == 1
            assert body["meta"]["next_cursor"] == TOKEN
        elif case[0] == "sitemanager_query_isp_metrics":
            assert len(body["data"]["items"]) == 1
            assert body["data"]["partial"] is True
            assert body["data"]["message"] == "One synthetic site omitted"
        elif isinstance(body["data"], list):
            assert len(body["data"]) == 1
            assert body["meta"]["next_cursor"] is None
        else:
            assert body["data"]["id"] in {"synthetic-host", "synthetic-config"}
        getattr(getattr(factory.bundle, case[4]), case[5]).assert_awaited_once()
        async with app.state.sessionmaker() as session:
            assert (await session.scalars(select(Controller))).all() == []
            rows = (await session.scalars(select(AuditLog))).all()
            assert len(rows) == 1
            assert rows[0].target == case[0] and rows[0].outcome == "success"
            assert rows[0].controller is None and rows[0].sitemanager_connection == "synthetic-local-account"
            assert rows[0].detail is None
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_console_and_account_actions_refuse_cross_target_before_lookup(tmp_path, monkeypatch):
    app, key, factory = await bootstrap(tmp_path, monkeypatch, scope="admin")
    from unifi_api.routes import actions as action_routes

    lookup = AsyncMock(side_effect=AssertionError("Console lookup before target rejection"))
    monkeypatch.setattr(action_routes, "get_controller", lookup)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {key}"}
            response = await client.post(
                "/v1/actions/sitemanager_list_hosts",
                headers=headers,
                json={"controller": "caller-id-must-not-echo", "site": "caller-site", "args": {}},
            )
            assert response.status_code == 409
            assert "caller-id-must-not-echo" not in response.text
            response = await client.post(
                "/v1/sitemanager/actions/unifi_list_clients", headers=headers, json={"args": {}}
            )
            assert response.status_code == 409
        assert factory.acquisitions == 0
        lookup.assert_not_awaited()
        assert not any(name.startswith("sitemanager_") for name in actions.build_dispatch_table())
        with pytest.raises(CapabilityMismatch):
            await actions.dispatch_action(
                registry=ManifestRegistry.load(),
                factory=app.state.manager_factory,
                session=None,
                tool_name="sitemanager_list_hosts",
                controller_id="caller-id",
                controller_products=["sitemanager"],
                site="caller-site",
                args={},
                confirm=True,
            )
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "write"])
@pytest.mark.parametrize(
    "path", ["/v1/sitemanager/isp-metrics/query", "/v1/sitemanager/actions/sitemanager_query_isp_metrics"]
)
async def test_read_scope_precedes_body_parsing_for_account_posts(tmp_path, monkeypatch, path, scope):
    from starlette.requests import Request

    app, key, factory = await bootstrap(tmp_path, monkeypatch, scope=scope or "read")
    original = Request.body
    reads = []

    async def body(request):
        reads.append(request.url.path)
        return await original(request)

    monkeypatch.setattr(Request, "body", body)
    try:
        headers = {"content-type": "application/json"}
        if scope:
            headers["Authorization"] = f"Bearer {key}"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(path, headers=headers, content=b'{"broken":')
        assert response.status_code == (401 if scope is None else 403)
        assert reads == [] and factory.acquisitions == 0
        async with app.state.sessionmaker() as session:
            rows = (await session.scalars(select(AuditLog))).all()
            assert len(rows) == 1 and rows[0].outcome == "denied"
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_unknown_action_and_forbidden_envelope_fields_are_not_echoed(tmp_path, monkeypatch, cloud_secrecy_guard):
    from tests.sitemanager_secrets import KEY

    marker = "CALLER-TOOL-ID-MUST-NOT-ECHO"
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {key}"}
            response = await client.post("/v1/sitemanager/actions/" + marker, headers=headers, json={"args": {}})
            assert response.status_code == 404 and marker not in response.text
            response = await client.post(
                "/v1/sitemanager/actions/sitemanager_list_hosts",
                headers=headers,
                json={"args": {}, "controller": marker, "confirm": True, KEY: KEY},
            )
            assert response.status_code == 422
            assert marker not in response.text
            cloud_secrecy_guard(response.text)
        assert factory.acquisitions == 0
        async with app.state.sessionmaker() as session:
            audit = (await session.scalars(select(AuditLog))).all()
            assert len(audit) == 1
            assert audit[0].target == "sitemanager.action" and audit[0].outcome == "error"
            assert marker not in str(audit[0].__dict__)
    finally:
        await app.state.engine.dispose()
