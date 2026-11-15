"""DPI catalog failures reach API callers as structured errors, never a 500.

``DpiManager`` raises fixed-text core errors when the integration API cannot
answer (no key, a rejected key, a refused key, another status, an unreadable
body). REST answers each with a structured ``detail``; GraphQL with an error
whose message quotes neither the controller's address nor its response.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_core.network.managers.dpi_manager import DpiManager

from tests.test_action_endpoint import _bootstrap

HOST = "controller-host-sentinel.example"
PRIVATE = "controller-only-response-body-3e1f"


def _session_answering(status: int, body) -> MagicMock:
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=body)
    response.text = AsyncMock(return_value=PRIVATE)
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=response)
    context.__aexit__ = AsyncMock(return_value=None)
    session = MagicMock()
    session.get = MagicMock(return_value=context)
    session.close = AsyncMock()
    return session


def _connection(auth) -> SimpleNamespace:
    return SimpleNamespace(
        host=HOST,
        port=443,
        site="default",
        ssl=True,
        tls_env_prefix=None,
        unifi_auth=auth,
        get_cached=lambda *args, **kwargs: None,
        _update_cache=lambda *args, **kwargs: None,
    )


async def _app(tmp_path, monkeypatch, auth):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path, scopes="read")
    connection = _connection(auth)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=DpiManager(connection, auth))
    factory.get_connection_manager = AsyncMock(return_value=connection)
    app.state.manager_factory = factory
    return app, key, cid


def _auth_answering(status: int, body=None) -> MagicMock:
    auth = MagicMock()
    auth.has_api_key = True
    auth.get_api_key_session = AsyncMock(return_value=_session_answering(status, body))
    return auth


UPSTREAM_CASES = [
    (401, None, 502, "api_key_rejected"),
    (403, None, 403, "api_key_forbidden"),
    (404, None, 502, "dpi_upstream_error"),
    (500, None, 502, "dpi_upstream_error"),
    (200, ["not", "an", "object"], 502, "dpi_upstream_error"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("resource", ["dpi-applications", "dpi-categories"])
@pytest.mark.parametrize(("upstream", "body", "status", "kind"), UPSTREAM_CASES)
async def test_rest_answers_upstream_failures_with_structured_detail(
    tmp_path, monkeypatch, caplog, resource, upstream, body, status, kind
):
    app, key, cid = await _app(tmp_path, monkeypatch, _auth_answering(upstream, body))

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/v1/sites/default/{resource}?controller={cid}", headers={"Authorization": f"Bearer {key}"}
        )

    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["kind"] == kind
    assert detail["controller"] == cid
    assert detail["hint"]
    assert HOST not in response.text and PRIVATE not in response.text
    assert HOST not in caplog.text and PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["dpiApplications", "dpiCategories"])
@pytest.mark.parametrize(
    ("auth", "expected"),
    [
        (SimpleNamespace(has_api_key=False), "needs a Network API key"),
        (_auth_answering(401), "(HTTP 401). The controller rejected the configured API key."),
        (_auth_answering(500), "DPI catalog request failed (HTTP 500)."),
    ],
    ids=["no_key", "rejected", "server_error"],
)
async def test_graphql_error_message_is_the_fixed_text(tmp_path, monkeypatch, field, auth, expected):
    app, key, cid = await _app(tmp_path, monkeypatch, auth)
    query = "{ network { " + field + '(controller: "' + cid + '") { items { id } } } }'

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        response = await client.post("/v1/graphql", headers={"Authorization": f"Bearer {key}"}, json={"query": query})

    assert response.status_code == 200
    errors = response.json()["errors"]
    assert errors and expected in errors[0]["message"]
    assert "UNIFI_" not in errors[0]["message"]
    assert HOST not in response.text and PRIVATE not in response.text
    assert "://" not in errors[0]["message"]
