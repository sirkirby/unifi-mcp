"""A controller 503 on a resource read is a retryable 503, not an unhandled 500.

When the console's application answers 503 (restarting, busy behind a proxy),
aiounifi raises ``ServiceUnavailable`` with the request URL in its text. REST
answers a short fixed message with ``Retry-After``; neither the controller's
address nor its response text reaches the caller or the log.
"""

import logging

import pytest
from aiounifi.errors import ServiceUnavailable
from httpx import ASGITransport, AsyncClient
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.network_manager import NetworkManager

from tests.routes.resources.test_network_resources import _bootstrap, _stub_connection

HOST = "controller-host-sentinel.example"
PRIVATE = "controller-only-response-body-3e1f"


def _unavailable(*args, **kwargs):
    raise ServiceUnavailable(f"Call https://{HOST}/proxy/network/api/s/default/rest/x received 503: {PRIVATE}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("manager", "method", "route"),
    [
        (NetworkManager, "get_networks", "networks"),
        (ClientManager, "get_clients", "clients"),
    ],
)
async def test_a_controller_503_on_a_resource_read_is_a_retryable_503(
    tmp_path, monkeypatch, caplog, manager, method, route
) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    _stub_connection(app, cid)
    monkeypatch.setattr(manager, method, _unavailable)

    with caplog.at_level(logging.DEBUG):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/v1/sites/default/{route}?controller={cid}", headers={"Authorization": f"Bearer {key}"}
            )

    assert response.status_code == 503, response.text
    assert response.headers["Retry-After"] == "5"
    detail = response.json()["detail"]
    assert detail["kind"] == "controller_unavailable"
    assert f"/sites/{{site_id}}/{route}" in detail["message"]
    assert HOST not in response.text and PRIVATE not in response.text
    assert HOST not in caplog.text and PRIVATE not in caplog.text
    assert "Traceback" not in caplog.text
