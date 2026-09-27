"""Focused fixed-AP mutation tests for the session-authenticated client manager."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiAuthError
from unifi_core.network.managers.client_manager import (
    ClientManager,
    FixedApNotFoundError,
    FixedApOperationError,
)

CLIENT_MAC = "aa:bb:cc:dd:ee:ff"
AP_MAC = "11:22:33:44:55:66"


def _connection(record: dict, *, ap: dict | None = None):
    conn = MagicMock()
    conn.ensure_session_connected = AsyncMock(return_value=True)
    conn._invalidate_cache = MagicMock()
    conn.controller = MagicMock()
    conn.controller.devices.values.return_value = [
        MagicMock(mac=AP_MAC, raw=ap or {"mac": AP_MAC, "type": "uap", "is_access_point": True, "adopted": True})
    ]
    conn.refresh_handler = AsyncMock()
    state = deepcopy(record)

    async def request(request):
        nonlocal state
        if request.path.startswith("/stat/user/"):
            return [deepcopy(state)]
        if request.method == "put":
            state = deepcopy(request.data)
        return None

    conn.request = AsyncMock(side_effect=request)
    return conn, lambda: state


@pytest.mark.asyncio
async def test_fixed_ap_preserves_full_user_record_and_verifies_readback():
    record = {
        "_id": "user-1",
        "mac": CLIENT_MAC,
        "noted": True,
        "is_wired": False,
        "name": "kept",
        "fixed_ip": "10.0.0.9",
    }
    conn, state = _connection(record)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    assert await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC) == {
        "success": True,
        "fixed_ap_enabled": True,
        "fixed_ap_mac": AP_MAC,
    }
    writes = [call.args[0].data for call in conn.request.call_args_list if call.args[0].method == "put"]
    assert writes == [{**record, "fixed_ap_enabled": True, "fixed_ap_mac": AP_MAC}]
    assert state()["name"] == "kept"
    conn._invalidate_cache.assert_called_once()


@pytest.mark.asyncio
async def test_fixed_ap_disable_preserves_inactive_mac_without_reconnect():
    record = {
        "_id": "user-1",
        "mac": CLIENT_MAC,
        "noted": True,
        "is_wired": False,
        "fixed_ap_enabled": True,
        "fixed_ap_mac": AP_MAC,
    }
    conn, _ = _connection(record)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    assert await manager.set_client_fixed_ap(CLIENT_MAC, False) == {
        "success": True,
        "fixed_ap_enabled": False,
        "fixed_ap_mac": AP_MAC,
    }
    write = next(call.args[0].data for call in conn.request.call_args_list if call.args[0].method == "put")
    assert write["fixed_ap_enabled"] is False
    assert write["fixed_ap_mac"] == AP_MAC
    assert not any(call[0] == "force_reconnect_client" for call in conn.method_calls)


@pytest.mark.asyncio
async def test_fixed_ap_notes_before_full_update_and_refetches():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": False, "is_wired": False, "hostname": "client"}
    conn, _ = _connection(record)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    assert (await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC))["success"] is True
    writes = [call.args[0].data for call in conn.request.call_args_list if call.args[0].method == "put"]
    assert writes[0]["noted"] is True
    assert writes[1]["noted"] is True
    assert writes[1]["fixed_ap_enabled"] is True


@pytest.mark.asyncio
async def test_fixed_ap_rejects_api_key_only_session_route():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": True, "is_wired": False}
    conn, _ = _connection(record)
    conn.ensure_session_connected = AsyncMock(return_value=False)
    manager = ClientManager(conn)

    with pytest.raises(UniFiAuthError, match="require Network session authentication"):
        await manager.set_client_fixed_ap(CLIENT_MAC, False)
    conn.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixed_ap_session_denial_happens_before_noting_client():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": False, "is_wired": False}
    conn, _ = _connection(record)
    conn.ensure_session_connected = AsyncMock(return_value=False)
    manager = ClientManager(conn)

    with pytest.raises(UniFiAuthError, match="No client mutation was attempted"):
        await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC)
    conn.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixed_ap_uses_persisted_user_id_not_merged_client_id():
    record = {"_id": "persisted-user", "mac": CLIENT_MAC, "noted": True}
    conn, _ = _connection(record)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(
        return_value=SimpleNamespace(raw={"_id": "merged-stale-id", "mac": CLIENT_MAC, "is_wired": False})
    )

    assert (await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC))["success"] is True
    write = next(call.args[0] for call in conn.request.call_args_list if call.args[0].method == "put")
    assert write.path == "/rest/user/persisted-user"


@pytest.mark.asyncio
async def test_fixed_ap_rejects_client_without_verified_wireless_state():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": True}
    conn, _ = _connection(record)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    with pytest.raises(ValueError, match="wireless connection is verified"):
        await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC)
    conn.request.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixed_ap_rejects_missing_or_non_ap_inventory():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": True, "is_wired": False}
    conn, _ = _connection(record, ap={"mac": AP_MAC, "type": "uap", "adopted": False})
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    with pytest.raises(FixedApNotFoundError, match="target was not found"):
        await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC)


@pytest.mark.asyncio
async def test_fixed_ap_rejects_ignored_controller_write():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": True, "is_wired": False}
    conn, _ = _connection(record)
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    async def ignored(request):
        if request.path.startswith("/stat/user/"):
            return [deepcopy(record)]
        return None

    conn.request = AsyncMock(side_effect=ignored)
    with pytest.raises(FixedApOperationError, match="did not persist"):
        await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC)


@pytest.mark.asyncio
async def test_fixed_ap_translates_raw_controller_errors_for_api_egress():
    conn, _ = _connection({"_id": "user-1", "mac": CLIENT_MAC, "noted": True, "is_wired": False})
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(side_effect=RuntimeError("controller said aa:bb:cc:dd:ee:ff secret"))

    with pytest.raises(FixedApOperationError, match=r"Fixed AP update failed \(RuntimeError\)") as caught:
        await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC)
    assert "aa:bb:cc:dd:ee:ff" not in str(caught.value)


@pytest.mark.asyncio
async def test_fixed_ap_translates_arbitrary_value_error_for_api_egress():
    conn, _ = _connection({"_id": "user-1", "mac": CLIENT_MAC, "noted": True, "is_wired": False})
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(side_effect=ValueError("controller aa:bb:cc:dd:ee:ff hostname=secret-tv"))

    with pytest.raises(FixedApOperationError, match=r"Fixed AP update failed \(ValueError\)") as caught:
        await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC)
    assert "aa:bb:cc:dd:ee:ff" not in str(caught.value)


@pytest.mark.asyncio
async def test_fixed_ap_accepts_explicit_integrated_access_point_capability():
    record = {"_id": "user-1", "mac": CLIENT_MAC, "noted": True, "is_wired": False}
    conn, _ = _connection(record, ap={"mac": AP_MAC, "type": "udm", "adopted": True, "is_access_point": True})
    manager = ClientManager(conn)
    manager.get_client_details = AsyncMock(return_value=SimpleNamespace(raw=deepcopy(record)))

    assert (await manager.set_client_fixed_ap(CLIENT_MAC, True, AP_MAC))["success"] is True
