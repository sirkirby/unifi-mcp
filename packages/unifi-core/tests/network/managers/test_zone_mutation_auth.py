"""Mixed-surface zone writes must validate their session path before mutation."""

from unittest.mock import AsyncMock, Mock

import pytest
from unifi_core.auth import UniFiAuth
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.firewall_manager import FirewallManager


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,args",
    [
        ("create_firewall_zone", ("Synthetic",)),
        ("update_firewall_zone", ("synthetic-id", "Synthetic")),
        ("delete_firewall_zone", ("synthetic-id",)),
    ],
)
@pytest.mark.parametrize("session_credentials", [False, True])
async def test_key_backed_legacy_connection_cannot_write_zones(operation, args, session_credentials):
    auth = UniFiAuth(api_key="synthetic-key")
    cm = ConnectionManager(
        "controller.test", "user" if session_credentials else "", "password" if session_credentials else "", auth=auth
    )
    cm._initialized = cm._key_mode = True
    cm.controller = Mock()
    cm._aiohttp_session = Mock(closed=False)
    cm.ensure_connected = AsyncMock(return_value=True)
    manager = FirewallManager(cm, auth)
    manager._request_integration_api = AsyncMock()
    manager._get_integration_site_id = AsyncMock()
    manager._resolve_zone_record = AsyncMock()
    with pytest.raises(UniFiAuthError, match="No zone mutation was attempted"):
        await getattr(manager, operation)(*args)
    manager._request_integration_api.assert_not_awaited()
    manager._get_integration_site_id.assert_not_awaited()
    manager._resolve_zone_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_session_can_continue_to_zone_write():
    auth = UniFiAuth(api_key="synthetic-key")
    cm = ConnectionManager("controller.test", "user", "password", auth=auth)
    cm._initialized = True
    cm.controller = Mock()
    cm._aiohttp_session = Mock(closed=False)
    cm.ensure_connected = AsyncMock(return_value=True)
    manager = FirewallManager(cm, auth)
    manager._get_integration_site_id = AsyncMock(return_value="site")
    manager._request_integration_api = AsyncMock(return_value={"id": "public-id"})
    manager._wait_for_created_v2_zone = AsyncMock(return_value={"_id": "legacy-id"})
    assert await manager.create_firewall_zone("Synthetic") == {"_id": "legacy-id"}
    manager._request_integration_api.assert_awaited_once()
