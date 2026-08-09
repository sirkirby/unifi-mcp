"""Post-write persistence verification for fetch-merge-put manager updates.

Regression coverage for the silent-no-op write: the controller can answer a
legacy /rest/wlanconf (or /rest/networkconf) PUT with rc:ok yet silently not
persist the requested fields. The managers used to return success
unconditionally; they now re-read and confirm the change actually landed.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.network.managers.network_manager import (
    NetworkManager,
    _apply_minrate_dependencies,
    _unpersisted_fields,
)

WLAN_ID = "60c7d8e9f0a1b2c3d4e5f6a7"
NETWORK_ID = "70d8e9f0a1b2c3d4e5f6a7b8"


def _make_connection():
    """Connection mock whose cache always misses, so each fetch hits request()."""
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock()
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    return conn


def _wlan(**overrides):
    base = {"_id": WLAN_ID, "name": "IoT", "proxy_arp": False, "minrate_ng_data_rate_kbps": 1000}
    base.update(overrides)
    return base


def _network(**overrides):
    base = {"_id": NETWORK_ID, "name": "Default", "igmp_snooping": False}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _unpersisted_fields helper
# ---------------------------------------------------------------------------


def test_unpersisted_flags_field_that_did_not_move():
    before = {"proxy_arp": False}
    after = {"proxy_arp": False}  # unchanged after the write
    assert _unpersisted_fields(before, after, {"proxy_arp": True}) == ["proxy_arp"]


def test_unpersisted_accepts_field_that_changed():
    before = {"proxy_arp": False}
    after = {"proxy_arp": True}
    assert _unpersisted_fields(before, after, {"proxy_arp": True}) == []


def test_unpersisted_ignores_noop_request():
    # Requested value already equals current state -> nothing to verify.
    before = {"proxy_arp": True}
    after = {"proxy_arp": True}
    assert _unpersisted_fields(before, after, {"proxy_arp": True}) == []


def test_unpersisted_skips_write_only_fields():
    before = {"x_passphrase": "old"}
    after = {}  # controller never echoes the passphrase back
    assert _unpersisted_fields(before, after, {"x_passphrase": "new"}) == []


# ---------------------------------------------------------------------------
# update_wlan
# ---------------------------------------------------------------------------


async def test_update_wlan_empty_update_is_successful_noop():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    result = await mgr.update_wlan(WLAN_ID, {})

    assert result.success is True
    assert result.mutation_applied is False
    assert result.metadata["wlan_id"] == WLAN_ID
    conn.ensure_connected.assert_not_awaited()
    conn.request.assert_not_called()


async def test_update_wlan_fails_when_not_persisted():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    before = _wlan()
    # get(pre) -> put(ignored) -> get(post == pre)
    conn.request.side_effect = [[before], {}, [_wlan()]]

    result = await mgr.update_wlan(WLAN_ID, {"proxy_arp": True})

    assert result.success is False
    assert result.dropped_fields == ("proxy_arp",)
    assert result.error is not None and "proxy_arp" in result.error


async def test_update_wlan_succeeds_when_persisted():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_wlan()], {}, [_wlan(proxy_arp=True)]]

    result = await mgr.update_wlan(WLAN_ID, {"proxy_arp": True})

    assert result.success is True
    assert result.persisted_fields == ("proxy_arp",)
    assert result.error is None


async def test_update_wlan_readback_failure_labels_before_state_explicitly():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    before = _wlan()
    conn.request.side_effect = [[before], {}, RuntimeError("read failed")]

    result = await mgr.update_wlan(WLAN_ID, {"proxy_arp": True})

    assert result.success is False
    assert result.resource is None
    assert result.metadata["details_before_attempt"] == before
    assert "read failed" in result.error


async def test_update_wlan_succeeds_for_write_only_field():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    # passphrase never round-trips; must not be reported as unpersisted
    conn.request.side_effect = [[_wlan()], {}, [_wlan()]]

    result = await mgr.update_wlan(WLAN_ID, {"x_passphrase": "newsecret"})

    assert result.success is True
    assert result.unverifiable_fields == ("x_passphrase",)
    assert result.error is None


# ---------------------------------------------------------------------------
# update_network (shares the same verification path)
# ---------------------------------------------------------------------------


async def test_update_network_empty_update_is_successful_noop():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    result = await mgr.update_network(NETWORK_ID, {})

    assert result.success is True
    assert result.mutation_applied is False
    assert result.metadata["network_id"] == NETWORK_ID
    conn.ensure_connected.assert_not_awaited()
    conn.request.assert_not_called()


async def test_update_network_fails_when_not_persisted():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_network()], {}, [_network()]]

    result = await mgr.update_network(NETWORK_ID, {"igmp_snooping": True})

    assert result.success is False
    assert result.dropped_fields == ("igmp_snooping",)
    assert result.error is not None and "igmp_snooping" in result.error


async def test_update_network_readback_failure_labels_before_state_explicitly():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    before = _network()
    conn.request.side_effect = [[before], {}, RuntimeError("read failed")]

    result = await mgr.update_network(NETWORK_ID, {"igmp_snooping": True})

    assert result.success is False
    assert result.resource is None
    assert result.metadata["details_before_attempt"] == before
    assert "read failed" in result.error


async def test_update_network_fails_when_controller_coerces_value():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    before = _network(purpose="vlan-only")
    after = _network(purpose="wan")
    conn.request.side_effect = [[before], {}, [after]]

    result = await mgr.update_network(NETWORK_ID, {"purpose": "corporate"})

    assert result.success is False
    assert result.coerced_fields == ("purpose",)
    assert result.resource == after


async def test_create_network_rejects_unsafe_guest_before_write():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    result = await mgr.create_network({"name": "Guest", "purpose": "guest"})

    assert result.success is False
    assert result.mutation_applied is False
    assert "Internal firewall zone" in result.error
    conn.request.assert_not_called()


async def test_update_network_rejects_unsafe_guest_before_write():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    result = await mgr.update_network(NETWORK_ID, {"purpose": "guest"})

    assert result.success is False
    assert result.mutation_applied is False
    conn.request.assert_not_called()


async def test_create_network_rereads_and_flags_purpose_coercion():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = {"name": "VLAN", "purpose": "vlan-only", "enabled": True}
    created = {"_id": NETWORK_ID, **requested}
    refetched = {**created, "purpose": "corporate"}
    conn.request.side_effect = [[created], [refetched]]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.metadata["network_id"] == NETWORK_ID
    assert result.persisted_fields == ("enabled", "name")
    assert result.coerced_fields == ("purpose",)


async def test_create_wlan_rereads_and_reports_partial_persistence():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = {"name": "Guest", "security": "open", "enabled": False, "guest_policy": True}
    created = {"_id": WLAN_ID, **requested}
    refetched = {**created, "guest_policy": False}
    conn.request.side_effect = [[created], [refetched]]

    result = await mgr.create_wlan(requested)

    assert result.success is False
    assert result.partial_success is True
    assert result.coerced_fields == ("guest_policy",)
    assert result.metadata["wlan_id"] == WLAN_ID


async def test_delete_network_fails_closed_on_malformed_verification_read():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_network(purpose="corporate")], {}, {"unexpected": "shape"}]

    with pytest.raises(RuntimeError, match="invalid network list response"):
        await mgr.delete_network(NETWORK_ID)


@pytest.mark.parametrize("purpose", ["wan", "vpn-client", "vpn-server", None])
async def test_delete_network_refuses_non_lan_purposes(purpose):
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_network(**({"purpose": purpose} if purpose else {}))]]

    with pytest.raises(ValueError, match="not a LAN/VLAN network"):
        await mgr.delete_network(NETWORK_ID)
    # Only the existence read happened; no DELETE was issued.
    assert conn.request.await_count == 1


async def test_delete_network_verifies_absence():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_network(purpose="corporate")], {}, []]

    assert await mgr.delete_network(NETWORK_ID) is True
    delete_request = conn.request.call_args_list[1].args[0]
    assert delete_request.method == "delete"
    assert delete_request.path == f"/rest/networkconf/{NETWORK_ID}"


async def test_delete_wlan_verifies_absence_and_fails_on_malformed_readback():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_wlan()], {}, {"unexpected": "shape"}]

    with pytest.raises(RuntimeError, match="invalid WLAN list response"):
        await mgr.delete_wlan(WLAN_ID)


async def test_delete_wlan_verifies_absence():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [[_wlan()], {}, []]

    assert await mgr.delete_wlan(WLAN_ID) is True
    delete = conn.request.call_args_list[1].args[0]
    assert delete.method == "delete"
    assert delete.path == f"/rest/wlanconf/{WLAN_ID}"


# ---------------------------------------------------------------------------
# _apply_minrate_dependencies helper
# ---------------------------------------------------------------------------


def test_minrate_deps_adds_manual_preference_and_enable_for_ng():
    out = _apply_minrate_dependencies({"minrate_ng_data_rate_kbps": 6000})
    assert out["minrate_setting_preference"] == "manual"
    assert out["minrate_ng_enabled"] is True
    assert out["minrate_ng_data_rate_kbps"] == 6000


def test_minrate_deps_adds_enable_for_na_band():
    out = _apply_minrate_dependencies({"minrate_na_data_rate_kbps": 12000})
    assert out["minrate_setting_preference"] == "manual"
    assert out["minrate_na_enabled"] is True


def test_minrate_deps_preserves_explicit_caller_values():
    # A caller who deliberately sets auto/disabled is not overridden.
    out = _apply_minrate_dependencies(
        {
            "minrate_ng_data_rate_kbps": 6000,
            "minrate_setting_preference": "auto",
            "minrate_ng_enabled": False,
        }
    )
    assert out["minrate_setting_preference"] == "auto"
    assert out["minrate_ng_enabled"] is False


def test_minrate_deps_noop_without_rate_field():
    assert _apply_minrate_dependencies({"proxy_arp": True}) == {"proxy_arp": True}


def test_minrate_deps_does_not_mutate_input():
    src = {"minrate_ng_data_rate_kbps": 6000}
    _apply_minrate_dependencies(src)
    assert src == {"minrate_ng_data_rate_kbps": 6000}


# ---------------------------------------------------------------------------
# update_wlan applies the min-rate dependencies on the wire
# ---------------------------------------------------------------------------


async def test_update_wlan_injects_manual_minrate_dependencies_into_put():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    before = _wlan(minrate_ng_data_rate_kbps=1000, minrate_setting_preference="auto", minrate_ng_enabled=True)
    after = _wlan(minrate_ng_data_rate_kbps=6000, minrate_setting_preference="manual", minrate_ng_enabled=True)
    # get(pre) -> put -> get(post, rate now persisted because mode is manual)
    conn.request.side_effect = [[before], {}, [after]]

    result = await mgr.update_wlan(WLAN_ID, {"minrate_ng_data_rate_kbps": 6000})

    assert result.success is True
    assert result.error is None
    put_request = conn.request.call_args_list[1].args[0]
    assert put_request.data["minrate_ng_data_rate_kbps"] == 6000
    assert put_request.data["minrate_setting_preference"] == "manual"
    assert put_request.data["minrate_ng_enabled"] is True
