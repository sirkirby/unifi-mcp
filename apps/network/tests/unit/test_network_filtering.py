"""Tests for list_networks / get_network_details / list_wlans filtering."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

NETWORKS = [
    {"_id": "n1", "name": "Default", "enabled": True, "purpose": "corporate", "vlan": 1, "ip_subnet": "192.0.2.0/24"},
    {"_id": "n2", "name": "IoT", "enabled": True, "purpose": "corporate", "vlan": 20, "ip_subnet": "198.51.100.0/24"},
    {"_id": "n3", "name": "Guest", "enabled": True, "purpose": "guest", "vlan": 30, "ip_subnet": "203.0.113.0/24"},
]


def _patch(networks=None, detail=None, wlans=None):
    mock_conn = MagicMock()
    mock_conn.site = "default"
    p = patch("unifi_network_mcp.tools.network.network_manager")
    mock = p.start()
    mock.get_networks = AsyncMock(return_value=list(networks or []))
    mock.get_network_details = AsyncMock(return_value=detail)
    mock.get_wlans = AsyncMock(return_value=list(wlans or []))
    mock._connection = mock_conn
    return p, mock


@pytest.mark.asyncio
async def test_list_networks_purpose_and_fields():
    p, _ = _patch(networks=NETWORKS)
    try:
        from unifi_network_mcp.tools.network import list_networks

        result = await list_networks(purpose="guest", fields="_id,name")
    finally:
        p.stop()
    assert result["total_count"] == 1
    assert set(result["networks"][0].keys()) == {"_id", "name"}


@pytest.mark.asyncio
async def test_list_networks_purpose_is_case_insensitive():
    # Mixed-case input must match the lowercase controller value, consistent with
    # the search/action filters elsewhere (which normalize case).
    p, _ = _patch(networks=NETWORKS)
    try:
        from unifi_network_mcp.tools.network import list_networks

        result = await list_networks(purpose="Guest")
    finally:
        p.stop()
    assert result["total_count"] == 1
    assert result["networks"][0]["name"] == "Guest"


@pytest.mark.asyncio
async def test_list_networks_search_matches_vlan_id():
    # Prod semantics: VLAN match is equality on str(vlan), name match is substring.
    p, _ = _patch(networks=NETWORKS)
    try:
        from unifi_network_mcp.tools.network import list_networks

        result = await list_networks(search="20")
    finally:
        p.stop()
    assert result["total_count"] == 1
    assert result["networks"][0]["name"] == "IoT"


@pytest.mark.asyncio
async def test_get_network_details_summary_false_returns_raw():
    raw = {"_id": "n2", "name": "IoT", "dhcpd_enabled": True, "secret": "x"}
    p, _ = _patch(detail=raw)
    try:
        from unifi_network_mcp.tools.network import get_network_details

        result = await get_network_details("n2", summary=False)
    finally:
        p.stop()
    assert result["summary_mode"] is False
    assert result["details"]["secret"] == "x"


@pytest.mark.asyncio
async def test_get_network_details_dhcp_section_is_independent():
    # Each section is independent: include="dhcp" must NOT auto-add basic keys.
    raw = {
        "_id": "n2",
        "name": "IoT",
        "purpose": "corporate",
        "dhcpd_enabled": True,
        "dhcpd_start": "198.51.100.10",
    }
    p, _ = _patch(detail=raw)
    try:
        from unifi_network_mcp.tools.network import get_network_details

        result = await get_network_details("n2", include="dhcp")
    finally:
        p.stop()
    details = result["details"]
    assert details["dhcpd_enabled"] is True
    assert "name" not in details  # basic not requested


@pytest.mark.asyncio
async def test_list_wlans_enabled_only_and_search():
    wlans = [
        {"_id": "w1", "name": "Home", "enabled": True},
        {"_id": "w2", "name": "Guest", "enabled": False},
    ]
    p, _ = _patch(wlans=wlans)
    try:
        from unifi_network_mcp.tools.network import list_wlans

        enabled = await list_wlans(enabled_only=True)
        searched = await list_wlans(search="guest")
    finally:
        p.stop()
    assert enabled["total_count"] == 1 and enabled["wlans"][0]["id"] == "w1"
    assert searched["total_count"] == 1 and searched["wlans"][0]["id"] == "w2"


@pytest.mark.asyncio
async def test_list_networks_routes_through_typed_model():
    # Discriminator for the model-routing path: the Network model coerces vlan to str.
    # A raw `.get("vlan")` would return int 20; routing through network_from_controller
    # yields "20". This test fails if the tool reverts to reading raw dict values.
    p, _ = _patch(networks=[{"_id": "n9", "name": "Lab", "vlan": 20, "enabled": True}])
    try:
        from unifi_network_mcp.tools.network import list_networks

        result = await list_networks()
    finally:
        p.stop()
    net = result["networks"][0]
    assert net["_id"] == "n9"
    assert net["vlan"] == "20"  # str (model coercion), not int 20 from raw
