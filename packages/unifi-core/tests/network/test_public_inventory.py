"""Public fallback must not manufacture legacy identities or telemetry."""

from unittest.mock import AsyncMock

import pytest
from unifi_core.auth import AuthenticationStatus, AuthMethod, UniFiAuth
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.client_manager import ClientManager
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.network_manager import NetworkManager
from unifi_core.network.models.integration import PublicInventory, PublicInventoryItem
from unifi_core.network.read_views import shape_client_list, shape_device_list, shape_network_list, shape_wlan_list

SITE_ID = "00000000-0000-0000-0000-000000000001"
ITEM_ID = "00000000-0000-0000-0000-000000000002"


def connection():
    return ConnectionManager("controller.test", "", "", auth=UniFiAuth(api_key="synthetic"))


@pytest.mark.parametrize("session,key", [(False, False), (True, False), (False, True), (True, True)])
def test_auth_requirements_do_not_confuse_configuration_with_availability(session, key):
    status = AuthenticationStatus(session_configured=session, api_key_configured=key)
    assert status.configured(AuthMethod.LOCAL_ONLY) == session
    assert status.configured(AuthMethod.API_KEY_ONLY) == key
    assert status.configured(AuthMethod.EITHER) == (session or key)
    assert status.configured(AuthMethod.BOTH) == (session and key)
    assert status.session_available is None
    assert status.api_key_available is None


@pytest.mark.asyncio
async def test_both_requirement_cannot_be_satisfied_by_one_session():
    with pytest.raises(UniFiAuthError, match="each session explicitly"):
        await UniFiAuth(api_key="synthetic").get_session(AuthMethod.BOTH)


@pytest.mark.asyncio
async def test_pagination_reads_all_pages():
    cm = connection()
    cm.request_integration = AsyncMock(
        side_effect=[
            {"data": [{"id": SITE_ID}], "totalCount": 2},
            {"data": [{"id": ITEM_ID}], "totalCount": 2},
        ]
    )
    assert len(await cm.integration_pages("/v1/sites")) == 2
    assert cm.request_integration.await_args.args[1]["offset"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second",
    [
        {"data": [{"id": SITE_ID}], "totalCount": 2},
        {"data": [], "totalCount": 2},
        {"data": [{"id": ITEM_ID}], "totalCount": 3},
        {"data": [{"id": ITEM_ID}], "totalCount": True},
    ],
)
async def test_pagination_rejects_duplicates_truncation_and_drifting_total(second):
    cm = connection()
    cm.request_integration = AsyncMock(side_effect=[{"data": [{"id": SITE_ID}], "totalCount": 2}, second])
    with pytest.raises(UniFiAuthError):
        await cm.integration_pages("/v1/sites")


@pytest.mark.asyncio
async def test_site_resolution_uses_internal_reference_and_preserves_uuid_provenance():
    cm = connection()
    cm.integration_pages = AsyncMock(
        side_effect=[
            [{"id": SITE_ID, "internalReference": "default", "name": "Synthetic site"}],
            [{"id": ITEM_ID, "name": "Synthetic network", "enabled": True, "vlanId": 20}],
        ]
    )
    records = await cm.public_inventory("networks")
    cm.integration_pages.assert_awaited_with(f"/v1/sites/{SITE_ID}/networks")
    assert records[0]["_id"] is None
    assert records[0]["integration_id"] == ITEM_ID
    assert records[0]["vlan"] == 20


@pytest.mark.asyncio
async def test_site_resolution_never_guesses_from_display_name():
    cm = connection()
    cm.integration_pages = AsyncMock(return_value=[{"id": SITE_ID, "internalReference": "other", "name": "default"}])
    with pytest.raises(UniFiAuthError, match="not a display name"):
        await cm.public_inventory("devices")
    assert cm.integration_pages.await_count == 1


@pytest.mark.asyncio
async def test_historical_clients_are_not_replaced_by_connected_clients():
    cm = connection()
    cm._initialized = cm._key_mode = True
    with pytest.raises(UniFiAuthError, match="include_offline"):
        await ClientManager(cm).get_all_clients()


@pytest.mark.parametrize(
    "domain,shape,key",
    [
        ("networks", shape_network_list, "networks"),
        ("wlans", shape_wlan_list, "wlans"),
        ("devices", shape_device_list, "devices"),
        ("clients", shape_client_list, "clients"),
    ],
)
def test_partial_shapes_and_empty_lists_keep_source(domain, shape, key):
    record = PublicInventoryItem(id=ITEM_ID, name="Synthetic", type="VPN").inventory_record(domain)
    result = shape(PublicInventory([record]), site="default")
    assert result["_meta"]["source_api"] == "integration"
    assert result["_meta"]["complete"] is False
    assert result[key][0]["id" if domain == "wlans" else "_id"] is None
    assert result[key][0]["integration_id"] == ITEM_ID
    assert shape(PublicInventory(), site="default")["_meta"]["source_api"] == "integration"


def test_unknown_client_transport_is_not_wireless_and_missing_guest_is_unknown():
    records = PublicInventory([PublicInventoryItem(id=ITEM_ID, type="VPN").inventory_record("clients")])
    result = shape_client_list(records, site="default")
    assert result["clients"][0]["connection_type"] is None
    assert result["clients"][0]["is_guest"] is None
    assert shape_client_list(records, site="default", filter_type="wireless")["count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("warm", [False, True])
@pytest.mark.parametrize("has_wlans", [False, True])
async def test_public_wlan_details_require_session_after_cold_or_warm_initialization(warm, has_wlans):
    cm = connection()
    cm._initialized = cm._key_mode = warm

    async def initialize():
        cm._initialized = cm._key_mode = True
        return True

    cm.initialize = AsyncMock(side_effect=initialize)
    cm.public_inventory = AsyncMock(
        return_value=PublicInventory(
            [PublicInventoryItem(id=ITEM_ID, name="Synthetic").inventory_record("wlans")] if has_wlans else []
        )
    )
    with pytest.raises(UniFiAuthError, match="WLAN details.*session authentication"):
        await NetworkManager(cm).get_wlan_details(ITEM_ID)
