"""Cross-surface validation, errors, authentication and generation-aware account reads."""

import copy
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import AuditLog
from unifi_api.graphql.context import RequestCache
from unifi_api.services.sitemanager_connections import SiteManagerConfigurationError
from unifi_api.services.sitemanager_reads import read_sitemanager
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.sitemanager.managers.connection_manager import SiteManagerHttpError, SiteManagerNotConfiguredError

from tests.sitemanager_data import CASES, SENSITIVE, TOKEN, bootstrap
from tests.sitemanager_secrets import KEY

CALLER = "CALLER-ID-MUST-NOT-ECHO-73"
UPSTREAM = "UPSTREAM-TEXT-MUST-NOT-ECHO-24"


async def request_case(client, key, case, surface):
    name, method, path, args, _, _, query, field = case
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if surface == "rest":
        return await client.request(
            method, path, headers=headers, **({"json": copy.deepcopy(args)} if method == "POST" else {})
        )
    if surface == "action":
        return await client.post("/v1/sitemanager/actions/" + name, headers=headers, json={"args": copy.deepcopy(args)})
    return await client.post("/v1/graphql", headers=headers, json={"query": "{ sitemanager { " + query + " } }"})


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
async def test_every_operation_not_configured_without_upstream(
    tmp_path, monkeypatch, case, surface, cloud_secrecy_guard
):
    app, key, factory = await bootstrap(tmp_path, monkeypatch, fake=False)
    from unifi_api.services import sitemanager_managers

    constructor = AsyncMock(side_effect=AssertionError("Constructed without a cloud account"))
    monkeypatch.setattr(sitemanager_managers, "SiteManagerConnectionManager", constructor)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, case, surface)
        if surface == "graphql":
            assert response.status_code == 200
            assert response.json()["errors"][0]["extensions"]["code"] == "NOT_CONFIGURED"
        else:
            assert response.status_code == 503
            assert response.json()["detail"]["kind"] == "sitemanager_not_configured"
        constructor.assert_not_called()
        cloud_secrecy_guard(response.text)
        async with app.state.sessionmaker() as session:
            audit = (await session.scalars(select(AuditLog))).all()
            assert len(audit) == (1 if surface == "action" else 0)
            if surface == "action":
                assert audit[0].sitemanager_connection is None and audit[0].controller is None
                assert audit[0].error_kind == "sitemanager_not_configured"
    finally:
        await factory.close()
        await app.state.engine.dispose()


ERRORS = [
    (SiteManagerConfigurationError, 503, "sitemanager_configuration_error", "NOT_CONFIGURED"),
    (SiteManagerNotConfiguredError, 503, "sitemanager_not_configured", "NOT_CONFIGURED"),
    (SiteManagerHttpError, 502, "sitemanager_upstream_error", "UPSTREAM_ERROR"),
    (UniFiAuthError, 502, "sitemanager_auth_failed", "UPSTREAM_AUTH_FAILED"),
    (UniFiPermissionError, 502, "sitemanager_permission_denied", "UPSTREAM_FORBIDDEN"),
    (UniFiNotFoundError, 404, "sitemanager_resource_not_found", "NOT_FOUND"),
    (UniFiValidationError, 400, "invalid_sitemanager_request", "BAD_REQUEST"),
    (UniFiRateLimitError, 429, "sitemanager_rate_limited", "RATE_LIMITED"),
    (UniFiConnectionError, 502, "sitemanager_upstream_error", "UPSTREAM_ERROR"),
    (UniFiMalformedResponseError, 502, "sitemanager_upstream_error", "UPSTREAM_ERROR"),
    (UniFiOperationError, 502, "sitemanager_upstream_error", "UPSTREAM_ERROR"),
    (SiteManagerHttpError, 404, "sitemanager_resource_not_found", "NOT_FOUND"),
    (RuntimeError, 500, "sitemanager_internal_error", "INTERNAL"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
@pytest.mark.parametrize("error_type,status,kind,code", ERRORS)
async def test_all_errors_are_fixed_text_without_input_or_upstream_echo(
    tmp_path, monkeypatch, surface, error_type, status, kind, code, caplog, cloud_secrecy_guard
):
    # The HTTPX test client's own URL logging is outside the API server boundary.
    caplog.set_level("WARNING", logger="httpx")
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    text = " ".join((KEY, CALLER, UPSTREAM))
    error = (
        error_type("host", CALLER, message=text)
        if error_type is UniFiNotFoundError
        else error_type(text, status=status, trace_id=text)
        if error_type is SiteManagerHttpError
        else error_type(text)
    )
    factory.bundle.inventory_manager.get_host.side_effect = error
    case = (
        "sitemanager_get_host",
        "GET",
        "/v1/sitemanager/hosts/" + CALLER,
        {"host_id": CALLER},
        "inventory_manager",
        "get_host",
        'host(hostId:"' + CALLER + '") { id }',
        "host",
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, case, surface)
        if surface == "graphql":
            assert response.status_code == 200
            assert response.json()["errors"][0]["extensions"]["code"] == code
        else:
            assert response.status_code == status
            assert response.json()["detail"]["kind"] == kind
        for value in (CALLER, UPSTREAM):
            assert value not in response.text and value not in caplog.text
        cloud_secrecy_guard(response.text)
        assert all(record.exc_info is None for record in caplog.records)
        async with app.state.sessionmaker() as session:
            rows = (await session.scalars(select(AuditLog))).all()
            assert len(rows) == (1 if surface == "action" else 0)
            if rows:
                assert rows[0].target == "sitemanager_get_host" and rows[0].error_kind == kind
                assert rows[0].detail is None and rows[0].sitemanager_connection == "synthetic-local-account"
                assert CALLER not in str(rows[0].__dict__) and UPSTREAM not in str(rows[0].__dict__)
    finally:
        await app.state.engine.dispose()


BAD_ARGS = [
    ("sitemanager_list_hosts", {"page_size": 0}),
    ("sitemanager_list_sites", {"cursor": " "}),
    ("sitemanager_list_devices", {"host_ids": []}),
    ("sitemanager_list_devices", {"host_ids": [" "]}),
    ("sitemanager_list_devices", {"host_ids": [1]}),
    ("sitemanager_list_devices", {"updated_since": CALLER}),
    ("sitemanager_get_host", {"host_id": "%2F" + CALLER}),
    ("sitemanager_get_sdwan_config", {"config_id": "../" + CALLER}),
    ("sitemanager_get_isp_metrics", {"metric_type": "5m", "duration": "7d"}),
    ("sitemanager_get_isp_metrics", {"begin_timestamp": "2026-01-01T00:00:00Z"}),
    ("sitemanager_get_isp_metrics", {"duration": "7d", "begin_timestamp": CALLER, "end_timestamp": CALLER}),
    ("sitemanager_get_isp_metrics", {"period_limit": True}),
    ("sitemanager_query_isp_metrics", {"sites": [{"host_id": CALLER, "site_id": CALLER, KEY: KEY}]}),
    ("sitemanager_query_isp_metrics", {"sites": [None]}),
    ("sitemanager_query_isp_metrics", {"sites": [{"host_id": CALLER, "site_id": CALLER, "duration": "7d"}]}),
    ("sitemanager_query_isp_metrics", {"sites": []}),
    ("sitemanager_list_sdwan_configs", {"controller": CALLER}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", BAD_ARGS)
async def test_invalid_read_arguments_never_acquire_or_call_upstream(tmp_path, monkeypatch, name, args):
    from unifi_api.services.sitemanager_errors import SiteManagerAPIError

    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        with pytest.raises(SiteManagerAPIError) as error:
            await read_sitemanager(
                registry=app.state.manifest_registry,
                type_registry=app.state.type_registry,
                factory=factory,
                tool_name=name,
                args=copy.deepcopy(args),
            )
        assert error.value.kind == "invalid_sitemanager_request"
        assert CALLER not in str(error.value) and KEY not in str(error.value)
        assert factory.acquisitions == 0
        factory.connection.get.assert_not_awaited()
        factory.connection.post.assert_not_awaited()
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [None, "write", "admin"])
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
async def test_account_read_admission_and_denials_have_no_ids(tmp_path, monkeypatch, scope, surface):
    app, key, factory = await bootstrap(tmp_path, monkeypatch, scope=scope or "read")
    case = (
        "sitemanager_get_host",
        "GET",
        "/v1/sitemanager/hosts/" + CALLER,
        {"host_id": CALLER},
        "inventory_manager",
        "get_host",
        'host(hostId:"' + CALLER + '") { id }',
        "host",
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key if scope else None, case, surface)
        if scope == "admin":
            assert response.status_code == 200
            assert factory.acquisitions == 1
        elif surface == "graphql" and scope != "admin":
            assert response.status_code == 200 and response.json()["errors"][0]["extensions"]["code"] == "FORBIDDEN"
            assert factory.acquisitions == 0
        else:
            assert response.status_code == (401 if scope is None else 403)
            assert factory.acquisitions == 0
        async with app.state.sessionmaker() as session:
            rows = (await session.scalars(select(AuditLog))).all()
            assert CALLER not in str([row.__dict__ for row in rows])
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_graphql_aliases_dedupe_only_identical_account_arguments(tmp_path, monkeypatch):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/graphql",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "query": """{
              sitemanager {
                first: devices(hostIds:["synthetic-first"],cursor:"token-a",pageSize:1) { nextCursor }
                same: devices(hostIds:["synthetic-first"],cursor:"token-a",pageSize:1) { nextCursor }
                size: devices(hostIds:["synthetic-first"],cursor:"token-a",pageSize:2) { nextCursor }
                updated: devices(hostIds:["synthetic-first"],cursor:"token-a",pageSize:1,
                                 updatedSince:"2026-01-01T00:00:00Z") { nextCursor }
                normal: host(hostId:"synthetic-host") { id reportedState }
                full: host(hostId:"synthetic-host",includeReportedState:true) { id reportedState }
                other: devices(hostIds:["synthetic-second"],cursor:"token-a",pageSize:1) { nextCursor }
                cursor: devices(hostIds:["synthetic-first"],cursor:"token-b",pageSize:1) { nextCursor }
                periods: ispMetrics(periodLimit:0) { count }
                more: ispMetrics(periodLimit:1) { count }
              }
            }"""
                },
            )
        assert response.json().get("errors") is None, response.text
        assert factory.bundle.inventory_manager.list_devices.await_count == 5
        assert factory.bundle.isp_metrics_manager.get_metrics.await_count == 2
        assert factory.bundle.inventory_manager.get_host.await_count == 2
        assert response.json()["data"]["sitemanager"]["first"] == {"nextCursor": TOKEN}
        cache = RequestCache()

        async def fetch():
            return await read_sitemanager(
                registry=app.state.manifest_registry,
                type_registry=app.state.type_registry,
                factory=factory,
                tool_name="sitemanager_list_hosts",
                args={},
                cache=cache,
            )

        first = await fetch()
        factory.bundle.revision = 2
        second = await fetch()
        assert (first.revision, second.revision) == (1, 2)
        factory.bundle.connection_id = "replacement-local-account"
        third = await fetch()
        assert third.connection_id == "replacement-local-account"
        assert factory.bundle.inventory_manager.list_hosts.await_count == 3
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_query_unknown_nested_key_is_rejected_on_every_surface_before_io(
    tmp_path, monkeypatch, caplog, cloud_secrecy_guard
):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    bad = {"sites": [{"host_id": CALLER, "site_id": CALLER, KEY: KEY}]}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {key}"}
            rest = await client.post("/v1/sitemanager/isp-metrics/query", headers=headers, json=bad)
            action = await client.post(
                "/v1/sitemanager/actions/sitemanager_query_isp_metrics", headers=headers, json={"args": bad}
            )
            gql = await client.post(
                "/v1/graphql",
                headers=headers,
                json={
                    "query": (
                        "query($sites:[SiteManagerMetricsSiteInput!]!){sitemanager{"
                        "queryIspMetrics(sites:$sites){partial}}}"
                    ),
                    "variables": {"sites": [{"hostId": CALLER, "siteId": CALLER, KEY: KEY}]},
                },
            )
        assert rest.status_code == 422
        assert action.status_code in (400, 422)
        assert gql.json()["errors"][0]["extensions"]["code"] == "BAD_REQUEST"
        assert factory.acquisitions == 0
        for response in (rest, action, gql):
            cloud_secrecy_guard(response.text)
            assert CALLER not in response.text
        assert CALLER not in caplog.text
        factory.connection.get.assert_not_awaited()
        factory.connection.post.assert_not_awaited()
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
async def test_nonfinite_upstream_metrics_are_safe_projection_errors(tmp_path, monkeypatch, surface, caplog):
    from unifi_core.sitemanager.models.isp_metrics import IspMetricPeriod, IspMetricSeries

    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    factory.bundle.isp_metrics_manager.get_metrics.side_effect = None
    factory.bundle.isp_metrics_manager.get_metrics.return_value = [
        IspMetricSeries(periods=[IspMetricPeriod(avg_latency_ms=float("nan"))])
    ]
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, CASES[4], surface)
        if surface == "graphql":
            assert response.json()["errors"][0]["extensions"]["code"] == "UPSTREAM_ERROR"
        else:
            assert response.status_code == 502
        assert "nan" not in response.text.lower()
        assert all(record.exc_info is None for record in caplog.records)
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["graphql", "action"])
@pytest.mark.parametrize("raw", [False, True])
async def test_nested_settings_follow_api_policy_on_every_egress(
    tmp_path, monkeypatch, surface, raw, cloud_secrecy_guard
):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    object.__setattr__(app.state.config.policy.response, "redact_sensitive_fields", not raw)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, CASES[7], surface)
        assert response.status_code == 200
        expected = SENSITIVE if raw else "***REDACTED***"
        result = (
            response.json()["data"]["sitemanager"]["sdwanConfig"] if surface == "graphql" else response.json()["data"]
        )
        assert result["settings"] == {"api_key": expected}
        assert result["hubs"] == [{"password": expected}]
        cloud_secrecy_guard(response.text, allow_redacted=True)
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
async def test_rest_rejects_local_connection_selectors_before_acquire(tmp_path, monkeypatch):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            for field in ("controller", "site_id", "api_key", "base_url", "include_sensitive"):
                response = await client.get(
                    "/v1/sitemanager/hosts", headers={"Authorization": f"Bearer {key}"}, params={field: CALLER}
                )
                assert response.status_code == 400 and CALLER not in response.text
        assert factory.acquisitions == 0
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
@pytest.mark.parametrize("case_index", [0, 2, 3])
async def test_empty_native_pages_keep_cursor_on_all_surfaces(tmp_path, monkeypatch, surface, case_index):
    from unifi_core.sitemanager.managers.connection_manager import SiteManagerResponse

    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    factory.connection.get.side_effect = None
    factory.connection.get.return_value = SiteManagerResponse([], TOKEN)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, CASES[case_index], surface)
        assert response.status_code == 200
        data = response.json()
        if surface == "graphql":
            assert data.get("errors") is None
            assert data["data"]["sitemanager"][CASES[case_index][7]] == {"items": [], "nextCursor": TOKEN}
        elif surface == "action":
            assert data["data"] == [] and data["meta"]["next_cursor"] == TOKEN
        else:
            assert data["items"] == [] and data["next_cursor"] == TOKEN
    finally:
        await app.state.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["rest", "graphql", "action"])
async def test_query_502_keeps_upstream_kind_with_site_access_guidance(tmp_path, monkeypatch, surface):
    app, key, factory = await bootstrap(tmp_path, monkeypatch)
    factory.bundle.isp_metrics_manager.query_metrics.side_effect = SiteManagerHttpError(UPSTREAM, status=502)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await request_case(client, key, CASES[5], surface)
        if surface == "graphql":
            assert response.json()["errors"][0]["extensions"]["code"] == "UPSTREAM_ERROR"
            message = response.json()["errors"][0]["message"]
        else:
            assert response.status_code == 502
            assert response.json()["detail"]["kind"] == "sitemanager_upstream_error"
            message = response.json()["detail"]["message"]
        assert "Check access to the requested sites." in message
        assert UPSTREAM not in response.text
    finally:
        await app.state.engine.dispose()
