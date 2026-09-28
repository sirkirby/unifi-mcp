"""Guarded guest-network creation through the legacy networkconf endpoint.

The controller derives guest purpose from the built-in Hotspot firewall zone:
the UI posts ``purpose='corporate'`` with the Hotspot ``firewall_zone_id`` and
the save hook stores ``purpose='guest'``. A guest request is only sent after a
fresh V2 zone lookup proves the zone is Hotspot by its canonical ``zone_key``.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.network.managers.network_manager import NetworkManager

NETWORK_ID = "70d8e9f0a1b2c3d4e5f6a7b8"
HOTSPOT_ZONE = {"_id": "hotspot-zone", "name": "Hotspot", "zone_key": "hotspot", "default_zone": True}
INTERNAL_ZONE = {"_id": "internal-zone", "name": "Internal", "zone_key": "internal", "default_zone": True}


def _make_connection():
    conn = MagicMock()
    conn.site = "default"
    conn.request = AsyncMock()
    conn.get_cached = MagicMock(return_value=None)
    conn._update_cache = MagicMock()
    conn._invalidate_cache = MagicMock()
    conn.ensure_connected = AsyncMock(return_value=True)
    return conn


def _guest(**overrides):
    data = {
        "name": "Visitors",
        "purpose": "guest",
        "firewall_zone_id": "hotspot-zone",
        "enabled": False,
        "vlan_enabled": True,
        "vlan": 3900,
        "ip_subnet": "192.0.2.1/29",
        "dhcpd_enabled": False,
        "network_isolation_enabled": False,
    }
    data.update(overrides)
    return data


def _zones(*zones):
    return {"data": list(zones)}


def _methods(conn):
    return [(call.args[0].method, call.args[0].path) for call in conn.request.await_args_list]


# ---------------------------------------------------------------------------
# Supported explicit guest create
# ---------------------------------------------------------------------------


async def test_explicit_guest_create_posts_ui_wire_payload_and_verifies_guest_readback():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest()
    original = dict(requested)
    created = {"_id": NETWORK_ID, **requested, "purpose": "corporate"}
    stored = {"_id": NETWORK_ID, **requested}
    conn.request.side_effect = [_zones(INTERNAL_ZONE, HOTSPOT_ZONE), [created], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is True
    assert result.mutation_applied is True
    assert "purpose" in result.persisted_fields
    assert "firewall_zone_id" in result.persisted_fields
    assert _methods(conn) == [("get", "/firewall/zone"), ("post", "/rest/networkconf"), ("get", "/rest/networkconf")]
    post = conn.request.await_args_list[1].args[0]
    assert post.data == {**original, "purpose": "corporate"}
    assert requested == original


async def test_explicit_guest_create_preserves_unknown_direct_sdk_fields_on_the_wire():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest(networkgroup="LAN", ipv6_interface_type="none")
    stored = {"_id": NETWORK_ID, **requested}
    conn.request.side_effect = [_zones(HOTSPOT_ZONE), [stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is True
    post = conn.request.await_args_list[1].args[0]
    assert post.data["networkgroup"] == "LAN"
    assert post.data["ipv6_interface_type"] == "none"
    assert post.data["purpose"] == "corporate"


async def test_guest_zone_is_matched_by_canonical_key_not_name():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    renamed_hotspot = {**HOTSPOT_ZONE, "name": "Visitors"}
    requested = _guest()
    stored = {"_id": NETWORK_ID, **requested}
    conn.request.side_effect = [_zones(renamed_hotspot), [stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is True


async def test_guest_zone_lookup_is_fresh_for_every_validation():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [_zones(HOTSPOT_ZONE), _zones({**HOTSPOT_ZONE, "zone_key": "internal"})]

    await mgr.validate_firewall_zone_assignment({}, _guest())
    with pytest.raises(ValueError, match="Hotspot zone"):
        await mgr.validate_firewall_zone_assignment({}, _guest())

    assert _methods(conn) == [("get", "/firewall/zone"), ("get", "/firewall/zone")]


# ---------------------------------------------------------------------------
# Readback exactness
# ---------------------------------------------------------------------------


async def test_guest_create_reports_coerced_purpose_when_controller_stores_corporate():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest()
    stored = {"_id": NETWORK_ID, **requested, "purpose": "corporate"}
    conn.request.side_effect = [_zones(HOTSPOT_ZONE), [stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.coerced_fields == ("purpose",)
    assert result.metadata["network_id"] == NETWORK_ID


async def test_guest_create_reports_coerced_zone_when_controller_moves_network():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest()
    stored = {"_id": NETWORK_ID, **requested, "firewall_zone_id": "internal-zone"}
    conn.request.side_effect = [_zones(HOTSPOT_ZONE), [stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.coerced_fields == ("firewall_zone_id",)


async def test_guest_create_reports_dropped_zone_and_purpose():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest()
    stored = {"_id": NETWORK_ID, **requested}
    del stored["purpose"], stored["firewall_zone_id"]
    conn.request.side_effect = [_zones(HOTSPOT_ZONE), [stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.dropped_fields == ("firewall_zone_id", "purpose")


async def test_guest_create_readback_failure_is_reported_as_applied():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest()
    conn.request.side_effect = [_zones(HOTSPOT_ZONE), [{"_id": NETWORK_ID}], RuntimeError("read failed")]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.metadata["network_id"] == NETWORK_ID


# ---------------------------------------------------------------------------
# Fail closed before any write
# ---------------------------------------------------------------------------


async def test_guest_create_without_zone_is_rejected_without_requests():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest()
    del requested["firewall_zone_id"]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is False
    assert "Internal firewall zone" in result.error
    conn.request.assert_not_called()


@pytest.mark.parametrize(
    "zone",
    [
        {**INTERNAL_ZONE, "_id": "hotspot-zone"},
        {"_id": "hotspot-zone", "name": "Hotspot", "default_zone": False},
        {"_id": "hotspot-zone", "name": "Hotspot", "zone_key": "HOTSPOT"},
    ],
)
async def test_guest_create_rejects_non_hotspot_zone_before_write(zone):
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [_zones(zone)]

    result = await mgr.create_network(_guest())

    assert result.success is False
    assert result.mutation_applied is False
    assert "Hotspot zone" in result.error
    assert _methods(conn) == [("get", "/firewall/zone")]


async def test_guest_create_rejects_unknown_zone_before_write():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [_zones(INTERNAL_ZONE)]

    result = await mgr.create_network(_guest())

    assert result.success is False
    assert result.mutation_applied is False
    assert "Hotspot zone" in result.error
    assert _methods(conn) == [("get", "/firewall/zone")]


@pytest.mark.parametrize("failure", [RuntimeError("opaque controller detail"), {"unexpected": "shape"}])
async def test_guest_create_fails_closed_when_zone_lookup_fails(failure):
    conn = _make_connection()
    mgr = NetworkManager(conn)
    conn.request.side_effect = [failure]

    result = await mgr.create_network(_guest())

    assert result.success is False
    assert result.mutation_applied is False
    assert "could not be verified" in result.error
    assert "opaque controller detail" not in result.error
    assert _methods(conn) == [("get", "/firewall/zone")]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network_isolation_enabled", True),
        ("gateway_type", "switch"),
        ("gateway_device", "aa:bb:cc:dd:ee:ff"),
        ("l3_interface_type", "vlan"),
        ("sdwan_underlay", True),
        ("sdwan_remote_site_id", "remote-site"),
    ],
)
async def test_direct_sdk_guest_create_rejects_incompatible_inputs_without_requests(field, value):
    conn = _make_connection()
    mgr = NetworkManager(conn)

    result = await mgr.create_network(_guest(**{field: value}))

    assert result.success is False
    assert result.mutation_applied is False
    assert field in result.error
    conn.request.assert_not_called()


async def test_validate_helper_raises_for_direct_callers_without_zone_lookup():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    with pytest.raises(ValueError, match="network_isolation_enabled"):
        await mgr.validate_firewall_zone_assignment({}, _guest(network_isolation_enabled=True))

    conn.request.assert_not_called()


async def test_zone_record_not_found_is_a_wrong_zone_rejection():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    mgr._get_firewall_zone_record = AsyncMock(side_effect=UniFiNotFoundError("firewall_zone", "hotspot-zone"))

    with pytest.raises(ValueError, match="Hotspot zone"):
        await mgr.validate_firewall_zone_assignment({}, _guest())


# ---------------------------------------------------------------------------
# Unchanged paths
# ---------------------------------------------------------------------------


async def test_guest_update_guard_is_unchanged_even_with_hotspot_zone():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    result = await mgr.update_network(NETWORK_ID, {"purpose": "guest", "firewall_zone_id": "hotspot-zone"})

    assert result.success is False
    assert result.mutation_applied is False
    assert "Hotspot zone" in result.error
    conn.request.assert_not_called()


async def test_validate_helper_rejects_guest_purpose_for_existing_networks():
    conn = _make_connection()
    mgr = NetworkManager(conn)

    with pytest.raises(ValueError, match="Hotspot zone"):
        await mgr.validate_firewall_zone_assignment(
            {"_id": NETWORK_ID, "purpose": "corporate"},
            {"purpose": "guest", "firewall_zone_id": "hotspot-zone"},
        )

    conn.request.assert_not_called()


async def test_corporate_hotspot_create_keeps_exact_requested_purpose_semantics():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = _guest(purpose="corporate")
    stored = {"_id": NETWORK_ID, **requested, "purpose": "guest"}
    conn.request.side_effect = [[stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is False
    assert result.mutation_applied is True
    assert result.coerced_fields == ("purpose",)
    assert _methods(conn) == [("post", "/rest/networkconf"), ("get", "/rest/networkconf")]
    assert conn.request.await_args_list[0].args[0].data["purpose"] == "corporate"


async def test_corporate_create_without_zone_skips_zone_lookup():
    conn = _make_connection()
    mgr = NetworkManager(conn)
    requested = {"name": "LAN", "purpose": "corporate", "ip_subnet": "192.0.2.1/24"}
    stored = {"_id": NETWORK_ID, **requested}
    conn.request.side_effect = [[stored], [stored]]

    result = await mgr.create_network(requested)

    assert result.success is True
    assert _methods(conn) == [("post", "/rest/networkconf"), ("get", "/rest/networkconf")]
