"""REST account reads retain native envelopes, filters, cursors and projection policy."""

import copy

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import AuditLog, Controller
from unifi_core.sitemanager.managers.connection_manager import SiteManagerResponse

from tests.sitemanager_data import CASES, SENSITIVE, TOKEN, bootstrap


@pytest.mark.asyncio
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
async def test_all_nine_account_resources(tmp_path, monkeypatch, case, cloud_secrecy_guard):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    name, method, path, args, manager, binding, _, _ = case
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {key}"},
                **({"json": copy.deepcopy(args)} if method == "POST" else {}),
            )
        assert response.status_code == 200, response.text
        body = response.json()
        if "items" in body:
            assert len(body["items"]) == 1
            assert body["items"][0]
            assert body["next_cursor"] == (
                TOKEN
                if name in {"sitemanager_list_hosts", "sitemanager_list_sites", "sitemanager_list_devices"}
                else None
            )
        else:
            assert body["data"]["id"] in {"synthetic-host", "synthetic-config"}
        if name == "sitemanager_list_devices":
            assert body["items"][0]["host_id"] == "synthetic-host"
            assert len(body["items"][0]["devices"]) == 2
        if name == "sitemanager_get_isp_metrics":
            assert body["count"] == 1 and body["items"][0]["summary"]["period_count"] == 3
        if name == "sitemanager_query_isp_metrics":
            assert body["partial"] is True and body["message"] == "One synthetic site omitted"
        getattr(getattr(factory.bundle, manager), binding).assert_awaited_once()
        assert factory.acquisitions == 1
        assert SENSITIVE not in response.text
        cloud_secrecy_guard(response.text, allow_redacted=True)
        async with app.state.sessionmaker() as session:
            assert (await session.scalars(select(Controller))).all() == []
            assert (await session.scalars(select(AuditLog))).all() == []
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1])
async def test_empty_and_short_pages_keep_cursor_byte_for_byte(tmp_path, monkeypatch, size):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    # These are real Core manager reads over a fake transport, not a flattened synthetic result.
    factory.connection.get.side_effect = None
    factory.connection.get.return_value = SiteManagerResponse([{"id": "synthetic-host"}][:size], TOKEN)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/sitemanager/hosts",
                headers={"Authorization": f"Bearer {key}"},
                params={"cursor": TOKEN, "page_size": 500},
            )
        assert response.status_code == 200
        assert len(response.json()["items"]) == size
        assert response.json()["next_cursor"] == TOKEN
        factory.connection.get.assert_awaited_once_with("/v1/hosts", params=[("pageSize", "500"), ("nextToken", TOKEN)])
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_devices_preserve_repeated_host_filters_and_grouping(tmp_path, monkeypatch):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/v1/sitemanager/devices",
                headers={"Authorization": f"Bearer {key}"},
                params=[
                    ("host_ids", "synthetic-second"),
                    ("host_ids", "synthetic-first"),
                    ("updated_since", "2026-01-01T00:00:00Z"),
                    ("cursor", TOKEN),
                    ("page_size", "1"),
                ],
            )
        assert response.status_code == 200
        groups = response.json()["items"]
        assert len(groups) == 1 and len(groups[0]["devices"]) == 2
        call = factory.connection.get.await_args
        assert call.args == ("/v1/devices",)
        assert call.kwargs["params"] == [
            ("pageSize", "1"),
            ("nextToken", TOKEN),
            ("hostIds[]", "synthetic-second"),
            ("hostIds[]", "synthetic-first"),
            ("time", "2026-01-01T00:00:00Z"),
        ]
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_metrics_defaults_zero_periods_and_partial_query(tmp_path, monkeypatch):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/v1/sitemanager/isp-metrics", headers=headers, params={"period_limit": 0})
            assert response.status_code == 200
            series = response.json()["items"]
            assert len(series) == 1
            assert series[0]["periods"] == []
            assert series[0]["summary"]["period_count"] == 3
            assert series[0]["summary"]["avg_latency_ms"] == 10
            assert series[0]["periods_truncated"] is True
            factory.connection.get.assert_awaited_once_with("/v1/isp-metrics/1h", params=[("duration", "7d")])
            response = await client.post(
                "/v1/sitemanager/isp-metrics/query",
                headers=headers,
                json={
                    "sites": [
                        {
                            "host_id": "synthetic-host",
                            "site_id": "synthetic-site",
                            "begin_timestamp": "2026-01-01T00:00:00Z",
                        }
                    ],
                    "period_limit": 1,
                },
            )
            assert response.status_code == 200
            assert response.json()["partial"] is True
            assert response.json()["message"] == "One synthetic site omitted"
            assert len(response.json()["items"]) == 1 and len(response.json()["items"][0]["periods"]) == 1
            assert response.json()["items"][0]["summary"]["period_count"] == 3
            factory.connection.post.assert_awaited_once_with(
                "/v1/isp-metrics/1h/query",
                json_body={
                    "sites": [
                        {
                            "hostId": "synthetic-host",
                            "siteId": "synthetic-site",
                            "beginTimestamp": "2026-01-01T00:00:00Z",
                        }
                    ],
                },
            )
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [False, True])
async def test_reported_state_opt_in_and_nested_policy(tmp_path, monkeypatch, raw):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    object.__setattr__(app.state.config.policy.response, "redact_sensitive_fields", not raw)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            base = await client.get("/v1/sitemanager/hosts/synthetic-host", headers={"Authorization": f"Bearer {key}"})
            assert base.json()["data"]["reported_state"] is None
            response = await client.get(
                "/v1/sitemanager/hosts/synthetic-host",
                headers={"Authorization": f"Bearer {key}"},
                params={"include_reported_state": "true"},
            )
            assert response.status_code == 200
            expected = SENSITIVE if raw else "***REDACTED***"
            assert response.json()["data"]["reported_state"]["api_key"] == expected
            assert response.json()["data"]["reported_state"]["nested"]["password"] == expected
            assert response.json()["data"]["owner"] is False
            assert response.json()["data"]["registration_time"] == 0
            assert factory.bundle.inventory_manager.get_host.await_args.kwargs["include_reported_state"] is True
    finally:
        await app.state.engine.dispose()
