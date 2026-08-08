"""Verified VPN state updates and deletes."""

from unittest.mock import AsyncMock, MagicMock

from unifi_core.network.managers.vpn_manager import VpnManager

VPN_ID = "vpn-client-1"


def _connection() -> MagicMock:
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock()
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    return conn


def _client(*, enabled: bool = True) -> dict:
    return {
        "_id": VPN_ID,
        "name": "Disposable tunnel",
        "purpose": "vpn-client",
        "vpn_type": "wireguard-client",
        "enabled": enabled,
    }


async def test_update_vpn_client_state_verifies_persisted_value() -> None:
    conn = _connection()
    manager = VpnManager(conn)
    conn.request.side_effect = [[_client()], {}, [_client(enabled=False)]]

    result = await manager.update_vpn_client_state(VPN_ID, False)

    assert result.success is True
    assert result.persisted_fields == ("enabled",)
    put = conn.request.call_args_list[1].args[0]
    assert put.method == "put"
    assert put.data["name"] == "Disposable tunnel"
    assert put.data["enabled"] is False


async def test_update_vpn_client_state_reports_dropped_value() -> None:
    conn = _connection()
    manager = VpnManager(conn)
    conn.request.side_effect = [[_client()], {}, [_client()]]

    result = await manager.update_vpn_client_state(VPN_ID, False)

    assert result.success is False
    assert result.dropped_fields == ("enabled",)
    assert result.mutation_applied is True


async def test_delete_vpn_client_checks_type_and_verifies_absence() -> None:
    conn = _connection()
    manager = VpnManager(conn)
    conn.request.side_effect = [[_client()], {}, []]

    assert await manager.delete_vpn_client(VPN_ID) is True
    delete = conn.request.call_args_list[1].args[0]
    assert delete.method == "delete"
    assert delete.path == f"/rest/networkconf/{VPN_ID}"
