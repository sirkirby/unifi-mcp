"""The firewall manager resolves the configured site to its Integration API site UUID."""

from unittest.mock import AsyncMock, Mock

import pytest
from unifi_core.exceptions import UniFiOperationError
from unifi_core.network.managers.firewall_manager import FirewallManager

DEFAULT_SITE = {"id": "88f7af54-98f8-306a-a1c7-c9349722b1f6", "internalReference": "default", "name": "Default"}
OFFICE_SITE = {"id": "1d2c3b4a-0000-4000-8000-000000000002", "internalReference": "x7k2p9qa", "name": "Office"}


def _manager(site: str, sites_response) -> FirewallManager:
    connection = Mock()
    connection.site = site
    connection.get_cached = Mock(return_value=None)
    connection._update_cache = Mock()
    manager = FirewallManager(connection)
    manager._request_integration_api = AsyncMock(return_value=sites_response)
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("default", DEFAULT_SITE["id"]),
        ("x7k2p9qa", OFFICE_SITE["id"]),
        (OFFICE_SITE["id"], OFFICE_SITE["id"]),
    ],
    ids=["internal_key_first_site", "internal_key_second_site", "integration_uuid"],
)
async def test_multi_site_console_resolves_the_configured_site(configured, expected):
    manager = _manager(configured, {"data": [DEFAULT_SITE, OFFICE_SITE]})

    assert await manager._get_integration_site_id() == expected
    manager._connection._update_cache.assert_called_once_with(f"integrations_site_id_{configured}", expected)


@pytest.mark.asyncio
async def test_single_site_console_resolves_by_internal_key():
    manager = _manager("default", {"data": [DEFAULT_SITE]})

    assert await manager._get_integration_site_id() == DEFAULT_SITE["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "configured",
    ["Office", "office", "unknown-site"],
    ids=["display_name", "display_name_other_case", "no_such_site"],
)
async def test_a_site_that_matches_no_key_or_uuid_is_refused(configured):
    manager = _manager(configured, {"data": [DEFAULT_SITE, OFFICE_SITE]})

    with pytest.raises(UniFiOperationError, match="internal site key or Integration UUID"):
        await manager._get_integration_site_id()
    manager._connection._update_cache.assert_not_called()


@pytest.mark.asyncio
async def test_a_single_site_console_does_not_fall_back_to_its_only_site():
    """A configured site that is not this console's site must not resolve to it."""
    manager = _manager("x7k2p9qa", {"data": [DEFAULT_SITE]})

    with pytest.raises(UniFiOperationError, match="internal site key or Integration UUID"):
        await manager._get_integration_site_id()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [{"data": []}, {"data": "default"}, {}, [], None, {"data": [DEFAULT_SITE, "not-a-site"]}],
    ids=["empty", "data_not_a_list", "no_data", "not_an_object", "none", "row_not_an_object"],
)
async def test_an_unusable_site_list_is_refused(response):
    manager = _manager("default", response)

    with pytest.raises(UniFiOperationError):
        await manager._get_integration_site_id()
    manager._connection._update_cache.assert_not_called()


@pytest.mark.asyncio
async def test_cached_site_id_skips_the_site_list():
    manager = _manager("default", {"data": [DEFAULT_SITE]})
    manager._connection.get_cached = Mock(return_value=DEFAULT_SITE["id"])

    assert await manager._get_integration_site_id() == DEFAULT_SITE["id"]
    manager._request_integration_api.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_site_list_is_read_in_one_large_page():
    manager = _manager("default", {"data": [DEFAULT_SITE]})

    await manager._get_integration_site_id()

    manager._request_integration_api.assert_awaited_once_with("get", "/v1/sites", params={"limit": "200"})
