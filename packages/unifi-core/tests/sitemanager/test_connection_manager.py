"""The Site Manager HTTP client: where the key goes, and what errors say."""

import inspect
import logging

import aiohttp
import pytest
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.sitemanager.managers import connection_manager as cm
from unifi_core.sitemanager.managers.connection_manager import (
    SITE_MANAGER_API_ORIGIN,
    SiteManagerConnectionManager,
    SiteManagerHttpError,
    SiteManagerNotConfiguredError,
    path_segment,
)

from tests.sitemanager.conftest import KEY


def test_destination_is_fixed_and_not_read_from_settings():
    assert SITE_MANAGER_API_ORIGIN == "https://api.ui.com"
    assert inspect.signature(SiteManagerConnectionManager).parameters["base_url"].default == SITE_MANAGER_API_ORIGIN
    # The module cannot consult the process environment: it never imports os.
    assert not hasattr(cm, "os")


async def test_sends_key_in_header_and_unwraps_envelope(connection, api):
    api.reply("GET", "/v1/hosts", {"data": [{"id": "h1"}], "nextToken": "t2", "traceId": "tr"})

    response = await connection.get("/v1/hosts", params=[("pageSize", "2"), ("hostIds[]", "a:1")])

    assert (response.data, response.next_token, response.trace_id) == ([{"id": "h1"}], "t2", "tr")
    (sent,) = api.requests
    assert sent.headers["X-API-Key"] == KEY
    assert sent.query == [("pageSize", "2"), ("hostIds[]", "a:1")]
    assert KEY not in sent.path and KEY not in str(sent.query)


async def test_session_ignores_proxy_environment(connection, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    assert connection._get_session().trust_env is False


async def test_redirect_is_reported_not_followed(connection, api):
    api.reply("GET", "/v1/hosts", status=302, headers={"Location": f"{api.base_url}/elsewhere"})

    with pytest.raises(UniFiConnectionError, match="redirect"):
        await connection.get("/v1/hosts")

    assert [request.path for request in api.requests] == ["/v1/hosts"]


@pytest.mark.parametrize(
    "path",
    [
        "@other.example/v1/hosts",
        ".other.example/v1/hosts",
        ":8443/v1/hosts",
        "v1/hosts",
        "/\\other.example/v1/hosts",
        "",
    ],
)
async def test_path_that_could_change_the_destination_makes_no_request(connection, api, path):
    with pytest.raises(UniFiValidationError, match="root-relative"):
        await connection.get(path)
    with pytest.raises(UniFiValidationError, match="root-relative"):
        await connection.post(path, json_body={})

    assert not api.requests


async def test_unconfigured_client_makes_no_request(api):
    manager = SiteManagerConnectionManager("   ", base_url=api.base_url)

    assert manager.configured is False and await manager.initialize() is False
    with pytest.raises(SiteManagerNotConfiguredError, match="UNIFI_SITEMANAGER_API_KEY"):
        await manager.get("/v1/hosts")
    assert not api.requests


@pytest.mark.parametrize(
    ("status", "error"),
    [(401, UniFiAuthError), (403, UniFiPermissionError), (500, SiteManagerHttpError), (502, SiteManagerHttpError)],
)
async def test_error_statuses_map_to_typed_errors_without_upstream_text(connection, api, status, error):
    api.reply("GET", "/v1/sites", {"message": "thing leaked: host-secret-id", "traceId": "tr-9"}, status=status)

    with pytest.raises(error) as raised:
        await connection.get("/v1/sites")

    assert "host-secret-id" not in str(raised.value)
    assert "tr-9" in str(raised.value)
    assert KEY not in str(raised.value)


async def test_http_error_carries_status_and_code(connection, api):
    api.reply("GET", "/v1/sites", {"code": "BAD_GATEWAY", "traceId": "tr"}, status=502)

    with pytest.raises(SiteManagerHttpError) as raised:
        await connection.get("/v1/sites")

    assert (raised.value.status, raised.value.code, raised.value.trace_id) == (502, "BAD_GATEWAY", "tr")


async def test_not_found_names_the_callers_resource(connection, api):
    api.reply("GET", "/v1/hosts/abc", {"code": "DATA_NOT_FOUND", "message": "thing not found"}, status=404)

    with pytest.raises(UniFiNotFoundError) as raised:
        await connection.get("/v1/hosts/abc", resource=("Host", "abc"))

    assert (raised.value.resource_type, raised.value.identifier) == ("Host", "abc")


async def test_bad_request_includes_bounded_upstream_reason(connection, api):
    api.reply("GET", "/v1/isp-metrics/1h", {"message": "x" * 500}, status=400)

    with pytest.raises(UniFiValidationError) as raised:
        await connection.get("/v1/isp-metrics/1h")

    assert "x" * 200 in str(raised.value) and "x" * 201 not in str(raised.value)


async def test_bad_request_reason_never_carries_the_api_key(connection, api):
    api.reply("GET", "/v1/hosts", {"message": f"unexpected header value {KEY} in request"}, status=400)

    with pytest.raises(UniFiValidationError) as raised:
        await connection.get("/v1/hosts")

    assert KEY not in str(raised.value)
    assert "unexpected header value [redacted] in request" in str(raised.value)


@pytest.mark.parametrize("status", [400, 401, 403, 500])
async def test_an_echoed_api_key_never_reaches_an_error_through_the_trace_or_code(connection, api, status):
    api.reply("GET", "/v1/hosts", {"traceId": f"tr-{KEY}", "code": KEY, "message": "nope"}, status=status)

    with pytest.raises(Exception) as raised:
        await connection.get("/v1/hosts")

    error = raised.value
    assert KEY not in str(error) and "tr-[redacted]" in str(error)
    assert KEY not in repr(vars(error))


@pytest.mark.parametrize("payload", [["not", "an", "envelope"], {"httpStatusCode": 200}])
async def test_unreadable_success_body_is_malformed(connection, api, payload):
    api.reply("GET", "/v1/hosts", payload)

    with pytest.raises(UniFiMalformedResponseError):
        await connection.get("/v1/hosts")


async def test_transport_failure_hides_exception_text_and_chain(connection, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise aiohttp.ClientConnectionError(f"boom header X-API-Key={KEY}")

    monkeypatch.setattr(connection._get_session(), "request", boom)

    with caplog.at_level(logging.DEBUG), pytest.raises(UniFiConnectionError) as raised:
        await connection.get("/v1/hosts")

    assert KEY not in str(raised.value) and KEY not in caplog.text
    assert raised.value.__cause__ is None and raised.value.__suppress_context__ is True
    assert "ClientConnectionError" in str(raised.value)


async def test_timeout_is_a_connection_error(api):
    manager = SiteManagerConnectionManager(KEY, base_url=api.base_url, timeout_seconds=0.05)
    api.reply("GET", "/v1/hosts", {"data": []}, delay=1.0)
    try:
        with pytest.raises(UniFiConnectionError, match="timed out"):
            await manager.get("/v1/hosts")
    finally:
        await manager.close()


async def test_get_waits_out_a_short_rate_limit(connection, api, monkeypatch):
    waits: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(cm.asyncio, "sleep", fake_sleep)
    api.reply("GET", "/v1/hosts", status=429, headers={"Retry-After": "2"})
    api.reply("GET", "/v1/hosts", {"data": []})

    assert (await connection.get("/v1/hosts")).data == []
    assert waits == [2.0]


@pytest.mark.parametrize("retry_after", ["600", "soon", None])
async def test_get_reports_a_rate_limit_it_will_not_wait_for(connection, api, retry_after):
    api.reply("GET", "/v1/hosts", status=429, headers={"Retry-After": retry_after} if retry_after else {})

    with pytest.raises(UniFiRateLimitError) as raised:
        await connection.get("/v1/hosts")

    assert ("600" in str(raised.value)) is (retry_after == "600")
    assert len(api.requests) == 1


async def test_post_is_never_retried(connection, api):
    api.reply("POST", "/v1/isp-metrics/5m/query", status=429, headers={"Retry-After": "1"})

    with pytest.raises(UniFiRateLimitError):
        await connection.post("/v1/isp-metrics/5m/query", json_body={"sites": []})

    assert len(api.requests) == 1


def test_path_segment_encodes_opaque_ids():
    assert path_segment("900A6F00:123456789", "host") == "900A6F00%3A123456789"
    assert path_segment("hub_1-a", "config") == "hub_1-a"


@pytest.mark.parametrize(
    "value", ["", ".", "..", "a/b", "a?b", "a#b", "a%2Fb", "a b", "a\\b", "a\nb", "x" * 257, None, 7]
)
def test_path_segment_refuses_values_that_could_retarget_the_request(value):
    with pytest.raises(UniFiValidationError) as raised:
        path_segment(value, "host")
    assert str(raised.value) == "Invalid host id"


LOG_ROUTES = [
    ("/v1/hosts", "/v1/hosts"),
    ("/v1/hosts/CALLER-ID-123", "/v1/hosts/{id}"),
    ("/v1/sites", "/v1/sites"),
    ("/v1/devices", "/v1/devices"),
    ("/v1/isp-metrics/1h", "/v1/isp-metrics/{metric_type}"),
    ("/v1/isp-metrics/5m/query", "/v1/isp-metrics/{metric_type}/query"),
    ("/v1/sd-wan-configs", "/v1/sd-wan-configs"),
    ("/v1/sd-wan-configs/CALLER-ID-123", "/v1/sd-wan-configs/{id}"),
    ("/v1/sd-wan-configs/CALLER-ID-123/status", "/v1/sd-wan-configs/{id}/status"),
    ("/v1/CALLER-ID-123/unknown", "/{unknown}"),
]


@pytest.mark.parametrize("path,template", LOG_ROUTES)
async def test_real_transport_failure_logs_only_route_template(path, template, unused_tcp_port, caplog):
    client = SiteManagerConnectionManager(KEY, base_url=f"http://127.0.0.1:{unused_tcp_port}")
    try:
        with pytest.raises(UniFiConnectionError):
            await client.get(path + "?cursor=CALLER-CURSOR-456")
        records = [record for record in caplog.records if record.name == cm.__name__]
        assert len(records) == 1
        assert records[0].getMessage() == f"Site Manager request GET {template} failed (ClientConnectorError)"
        assert records[0].exc_info is None
        assert "CALLER" not in records[0].getMessage() and "?" not in records[0].getMessage()
        assert KEY not in caplog.text
    finally:
        await client.close()


@pytest.mark.parametrize("path,template", LOG_ROUTES)
async def test_real_rate_limit_retry_logs_only_route_template(path, template, connection, api, caplog):
    api.reply("GET", path, status=429, headers={"Retry-After": "0"})
    api.reply("GET", path, {"data": []})
    with caplog.at_level(logging.INFO, logger=cm.__name__):
        result = await connection.get(path + "?cursor=CALLER-CURSOR-456")
    assert result.data == []
    assert len(api.requests) == 2
    assert api.requests[0].query == [("cursor", "CALLER-CURSOR-456")]
    records = [record for record in caplog.records if record.name == cm.__name__]
    assert len(records) == 1
    assert records[0].getMessage() == f"Site Manager rate limit on GET {template}; retrying in 0.0s"
    assert records[0].exc_info is None
    assert "CALLER" not in records[0].getMessage() and "?" not in records[0].getMessage()
    assert KEY not in caplog.text
