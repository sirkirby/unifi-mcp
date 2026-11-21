"""A controller 503 on a resource read is a retryable 503, not an unhandled 500.

When the console's application answers 503 (restarting, busy behind a proxy),
aiounifi raises ``ServiceUnavailable`` with the request URL in its text. The
real Network manager reads through the connection's ``request``, so only that
call is replaced here. REST answers a short fixed message with ``Retry-After``,
and neither the controller's address nor the exception text reaches the caller
or the API's own log.
"""

import logging

import pytest
from aiounifi.errors import ServiceUnavailable
from httpx import ASGITransport, AsyncClient
from unifi_core.operation_gate import BUSY_RETRY_AFTER_SECONDS

from tests.routes.resources.test_network_resources import _bootstrap

HOST = "controller-host-sentinel.example"
PRIVATE = "controller-only-detail-3e1f"


class _ConnectionAnswering503:
    """Connection manager stand-in whose controller request answers 503."""

    site = "default"
    has_api_key = False

    async def initialize(self) -> None:
        return None

    async def set_site(self, site: str) -> None:
        self.site = site

    def get_cached(self, *args, **kwargs):
        return None

    def _update_cache(self, *args, **kwargs) -> None:
        return None

    async def request(self, api_request):
        raise ServiceUnavailable(f"Call https://{HOST}/proxy/network/api/s/default/{PRIVATE} received 503")


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["networks", "wlans"])
async def test_a_controller_503_on_a_resource_read_is_a_retryable_503(tmp_path, monkeypatch, caplog, route) -> None:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    app.state.manager_factory._connection_cache[(cid, "network", "default")] = _ConnectionAnswering503()

    with caplog.at_level(logging.DEBUG, logger="unifi-api"):
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/v1/sites/default/{route}?controller={cid}", headers={"Authorization": f"Bearer {key}"}
            )

    assert response.status_code == 503, response.text
    assert response.headers["Retry-After"] == str(BUSY_RETRY_AFTER_SECONDS)
    detail = response.json()["detail"]
    assert detail["kind"] == "controller_unavailable"
    assert f"GET /sites/{{site_id}}/{route}" in detail["message"]
    assert HOST not in response.text and PRIVATE not in response.text

    # The API logs one warning for it: no exception text, no traceback.
    ours = [record for record in caplog.records if record.name == "unifi-api.controller"]
    assert [record.levelno for record in ours] == [logging.WARNING]
    assert ours[0].exc_info is None
    assert HOST not in ours[0].getMessage() and PRIVATE not in ours[0].getMessage()
