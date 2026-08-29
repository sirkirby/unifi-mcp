"""Tests for complete DPI catalogue retrieval and Integration-API transport."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from unifi_core.network.managers.dpi_manager import DpiManager


@pytest.fixture
def connection():
    conn = MagicMock()
    conn.site = "default"
    conn.host = "192.168.1.1"
    conn.port = 443
    conn.verify_ssl = True
    conn.get_cached.return_value = None
    return conn


@pytest.fixture
def auth():
    value = MagicMock()
    value.has_api_key = True
    value.get_api_key_session = AsyncMock()
    return value


@pytest.fixture
def manager(connection, auth):
    return DpiManager(connection, auth)


@pytest.mark.asyncio
async def test_full_catalog_uses_supported_page_size_and_actual_offsets(manager, connection):
    applications = [{"id": app_id, "name": f"Application {app_id}"} for app_id in range(201)]

    async def fake_request(path, params=None):
        if path == "/v1/dpi/applications" and params["offset"] == "0":
            return {"data": applications[:200], "totalCount": 201, "offset": 0}
        if path == "/v1/dpi/applications" and params["offset"] == "200":
            return {"data": applications[200:], "totalCount": 201, "offset": 200}
        if path == "/v1/dpi/categories":
            return {"data": [{"id": 4, "name": "Media streaming"}], "totalCount": 1, "offset": 0}
        raise AssertionError(f"Unexpected request: {path} {params}")

    with patch.object(manager, "_request_integration_api", side_effect=fake_request) as mock_api:
        result = await manager.get_full_dpi_catalog()

    assert len(result["applications"]) == 201
    assert result["categories"] == [{"id": 4, "name": "Media streaming"}]
    assert [call.args for call in mock_api.await_args_list] == [
        ("/v1/dpi/applications", {"limit": "200", "offset": "0"}),
        ("/v1/dpi/applications", {"limit": "200", "offset": "200"}),
        ("/v1/dpi/categories", {"limit": "200", "offset": "0"}),
    ]
    connection._update_cache.assert_called_once_with(
        "dpi_catalog_default",
        result,
        timeout=900,
    )


@pytest.mark.asyncio
async def test_full_catalog_does_not_cache_incomplete_application_pages(manager, connection):
    async def fake_request(path, params=None):
        if params["offset"] == "0":
            return {"data": [{"id": 1, "name": "First"}], "totalCount": 2, "offset": 0}
        return None

    with (
        patch.object(manager, "_request_integration_api", side_effect=fake_request),
        pytest.raises(RuntimeError, match="incomplete DPI application catalogue"),
    ):
        await manager.get_full_dpi_catalog()

    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
async def test_full_catalog_does_not_cache_incomplete_category_pages(manager, connection):
    async def fake_request(path, params=None):
        if path == "/v1/dpi/applications":
            return {"data": [{"id": 1, "name": "First"}], "totalCount": 1, "offset": 0}
        if params["offset"] == "0":
            return {"data": [{"id": 4, "name": "Media"}], "totalCount": 2, "offset": 0}
        return None

    with (
        patch.object(manager, "_request_integration_api", side_effect=fake_request),
        pytest.raises(RuntimeError, match="incomplete DPI category catalogue"),
    ):
        await manager.get_full_dpi_catalog()

    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second_page", "error"),
    [
        ({"data": [{"id": 1, "name": "First"}], "totalCount": 2, "offset": 1}, "duplicate"),
        ({"data": [{"id": 2, "name": "Second"}], "totalCount": 3, "offset": 1}, "changed"),
        ({"data": [], "totalCount": 2, "offset": 1}, "incomplete"),
        ({"data": [{"id": 2, "name": "Second"}], "totalCount": 2, "offset": 0}, "incomplete"),
    ],
    ids=["duplicate-id", "changed-total", "empty-page", "wrong-offset"],
)
async def test_full_catalog_rejects_invalid_later_pages(manager, connection, second_page, error):
    async def fake_request(path, params=None):
        if params["offset"] == "0":
            return {"data": [{"id": 1, "name": "First"}], "totalCount": 2, "offset": 0}
        return second_page

    with (
        patch.object(manager, "_request_integration_api", side_effect=fake_request),
        pytest.raises(RuntimeError, match=error),
    ):
        await manager.get_full_dpi_catalog()

    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("first_page", "error"),
    [
        ({"data": [{"id": 1, "name": "First"}], "offset": 0}, "invalid"),
        ({"data": [{"id": 1, "name": "First"}], "totalCount": "unknown", "offset": 0}, "invalid"),
        ({"data": [{"id": 1, "name": "First"}], "totalCount": 1.5, "offset": 0}, "invalid"),
        ({"data": [{"id": 1, "name": "First"}], "totalCount": "1.5", "offset": 0}, "invalid"),
        (
            {
                "data": [{"id": 1, "name": "First"}, {"id": 2, "name": "Second"}],
                "totalCount": 1,
                "offset": 0,
            },
            "inconsistent",
        ),
    ],
    ids=["missing-total", "invalid-total", "fractional-float", "fractional-string", "overfull-page"],
)
async def test_full_catalog_rejects_missing_or_inconsistent_totals(manager, connection, first_page, error):
    with (
        patch.object(manager, "_request_integration_api", new=AsyncMock(return_value=first_page)),
        pytest.raises(RuntimeError, match=error),
    ):
        await manager.get_full_dpi_catalog()

    connection._update_cache.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_integration_request_propagates_tls_verification(connection, auth, verify_ssl):
    connection.verify_ssl = verify_ssl
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"data": []})

    response_context = AsyncMock()
    response_context.__aenter__ = AsyncMock(return_value=response)
    response_context.__aexit__ = AsyncMock(return_value=None)

    session = AsyncMock()
    session.get = MagicMock(return_value=response_context)
    session.close = AsyncMock()
    auth.get_api_key_session.return_value = session

    manager = DpiManager(connection, auth)
    await manager._request_integration_api("/v1/dpi/applications")

    session.get.assert_called_once()
    assert session.get.call_args.kwargs["ssl"] is verify_ssl
    session.close.assert_awaited_once()
