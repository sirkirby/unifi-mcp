"""Every upstream classification is projected to fixed management errors."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from unifi_api.services.sitemanager_errors import map_error
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
from unifi_core.sitemanager.managers.inventory_manager import InventoryManager

from tests.test_controllers_routes import _bootstrap_app
from tests.test_sitemanager_connections import KEY

CASES = [
    (SiteManagerNotConfiguredError(KEY), 503, "sitemanager_not_configured"),
    (UniFiAuthError(KEY), 502, "sitemanager_auth_failed"),
    (UniFiPermissionError(KEY), 502, "sitemanager_permission_denied"),
    (UniFiNotFoundError("host", KEY), 404, "sitemanager_resource_not_found"),
    (SiteManagerHttpError(KEY, status=404, trace_id=KEY), 404, "sitemanager_resource_not_found"),
    (UniFiValidationError(KEY), 400, "invalid_sitemanager_request"),
    (UniFiRateLimitError(KEY), 429, "sitemanager_rate_limited"),
    (UniFiConnectionError(KEY), 502, "sitemanager_upstream_error"),
    (UniFiMalformedResponseError(KEY), 502, "sitemanager_upstream_error"),
    (SiteManagerHttpError(KEY, status=502, code=KEY, trace_id=KEY), 502, "sitemanager_upstream_error"),
    (UniFiOperationError(KEY), 502, "sitemanager_upstream_error"),
    (RuntimeError(KEY), 500, "sitemanager_internal_error"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status,kind", CASES, ids=[case[2] + str(i) for i, case in enumerate(CASES)])
async def test_probe_error_mapping_never_returns_or_logs_upstream_text(
    tmp_path, monkeypatch, caplog, error, status, kind, cloud_secrecy_guard
):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    monkeypatch.setattr(InventoryManager, "list_hosts", AsyncMock(side_effect=error))
    app, key = await _bootstrap_app(tmp_path)
    headers = {"Authorization": f"Bearer {key}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (
            await client.post(
                "/v1/sitemanager/connection", headers=headers, json={"name": "Account", "site_manager_api_key": KEY}
            )
        ).status_code == 201
        response = await client.post("/v1/sitemanager/connection/probe", headers=headers)
        assert response.status_code == status
        body = response.json()
        assert body["ok"] is False and body["error_kind"] == kind
        assert "Failed to probe Site Manager connection" in body["message"]
        cloud_secrecy_guard(response.text)
        assert "retry-after" not in response.headers
        assert response.headers["cache-control"] == "no-store"
    cloud_secrecy_guard(caplog.text)
    assert all(record.exc_info is None for record in caplog.records)
    await app.state.engine.dispose()


def test_opaque_exception_renderer_is_not_invoked(caplog, cloud_secrecy_guard):
    class OpaqueError(Exception):
        def __str__(self):
            raise AssertionError("Exception text rendered")

    error = map_error(OpaqueError(), "probe Site Manager connection")
    assert error.kind == "sitemanager_internal_error"
    assert "OpaqueError" in caplog.text
    assert "Exception text rendered" not in caplog.text
