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


def _mock_conn():
    c = MagicMock()
    c.site = "default"
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize("redact", [True, False])
@pytest.mark.parametrize("summary", [True, False])
async def test_network_details_redacts_openvpn_private_keys(monkeypatch, redact, summary):
    monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", str(redact).lower())
    keys = ["x_ca_key", "x_server_key", "x_shared_client_key", "x_auth_key"]
    raw = {"_id": "vpn", "name": "VPN", "purpose": "remote-user-vpn", "x_ca_crt": "public"}
    raw.update(dict.fromkeys(keys, "synthetic-vpn-private-key"))
    with patch("unifi_network_mcp.tools.network.network_manager") as manager:
        manager.get_network_details = AsyncMock(return_value=raw)
        manager._connection = _mock_conn()
        from unifi_network_mcp.tools.network import get_network_details

        result = await get_network_details("vpn", summary=summary, include="all")

    assert result["success"] is True
    for key in keys:
        if summary:
            assert key not in result["details"]
        else:
            assert result["details"][key] == ("***REDACTED***" if redact else raw[key])
        assert raw[key] == "synthetic-vpn-private-key"
    if not summary:
        assert result["details"]["x_ca_crt"] == "public"


@pytest.mark.asyncio
async def test_get_network_details_summary_false_redacts_by_default_and_uses_policy_opt_out(monkeypatch):
    raw = {"_id": "n2", "name": "IoT", "dhcpd_enabled": True, "secret": "x"}
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_nm:
        mock_nm.get_network_details = AsyncMock(return_value=raw)
        mock_nm._connection = _mock_conn()

        from unifi_network_mcp.tools.network import get_network_details

        result = await get_network_details("n2", summary=False)
        monkeypatch.setenv("UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS", "false")
        raw_result = await get_network_details("n2", summary=False)

    assert result["summary_mode"] is False
    assert result["details"]["secret"] == "***REDACTED***"
    assert raw_result["details"]["secret"] == "x"


@pytest.mark.asyncio
async def test_get_network_details_default_preserves_full_object_with_redaction():
    # Regression guard for the default contract: no-args must return the full
    # network object, but sensitive raw keys are redacted unless explicitly requested.
    raw = {"_id": "n2", "name": "IoT", "dhcpd_enabled": True, "secret": "x", "purpose": "corporate"}
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_nm:
        mock_nm.get_network_details = AsyncMock(return_value=raw)
        mock_nm._connection = _mock_conn()

        from unifi_network_mcp.tools.network import get_network_details

        result = await get_network_details("n2")

    assert result["success"] is True
    assert result["summary_mode"] is False
    # extra/unknown keys preserved, sensitive values redacted by default
    assert result["details"]["secret"] == "***REDACTED***"
    assert result["details"]["dhcpd_enabled"] is True


@pytest.mark.asyncio
async def test_list_wlans_enabled_only_and_search():
    wlans = [
        {"_id": "w1", "name": "Home", "enabled": True},
        {"_id": "w2", "name": "Guest", "enabled": False},
    ]
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_nm:
        mock_nm.get_wlans = AsyncMock(return_value=list(wlans))
        mock_nm._connection = _mock_conn()

        from unifi_network_mcp.tools.network import list_wlans

        enabled = await list_wlans(enabled_only=True)
        searched = await list_wlans(search="guest")

    assert enabled["total_count"] == 1 and enabled["wlans"][0]["id"] == "w1"
    assert searched["total_count"] == 1 and searched["wlans"][0]["id"] == "w2"
    # back-compat: legacy `count` key preserved on list_wlans
    assert enabled["count"] == enabled["returned_count"]
    assert searched["count"] == searched["returned_count"]


@pytest.mark.asyncio
async def test_list_networks_routes_through_typed_model():
    # Discriminator for the model-routing path: the Network model coerces vlan to str.
    # A raw `.get("vlan")` would return int 20; routing through network_from_controller
    # yields "20". This test fails if the tool reverts to reading raw dict values.
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_nm:
        mock_nm.get_networks = AsyncMock(return_value=[{"_id": "n9", "name": "Lab", "vlan": 20, "enabled": True}])
        mock_nm._connection = _mock_conn()

        from unifi_network_mcp.tools.network import list_networks

        result = await list_networks()

    net = result["networks"][0]
    assert net["_id"] == "n9"
    assert net["vlan"] == "20"  # str (model coercion), not int 20 from raw


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,total,first_name,keys,unknown_fields",
    [
        # Mixed-case purpose must match the lowercase controller value.
        ({"purpose": "Guest"}, 1, "Guest", None, None),
        ({"purpose": "guest", "fields": "_id,name"}, 1, "Guest", {"_id", "name"}, None),
        # Prod semantics: VLAN match is equality on str(vlan), name match is substring.
        ({"search": "20"}, 1, "IoT", None, None),
        # Typos in fields surface as unknown_fields while known fields are still returned.
        ({"fields": "name,vlann"}, 3, "Default", {"name"}, ["vlann"]),
    ],
)
async def test_list_networks_filters_and_fields(kwargs, total, first_name, keys, unknown_fields):
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_nm:
        mock_nm.get_networks = AsyncMock(return_value=list(NETWORKS))
        mock_nm._connection = _mock_conn()

        from unifi_network_mcp.tools.network import list_networks

        result = await list_networks(**kwargs)

    assert result["total_count"] == total
    assert result["networks"][0]["name"] == first_name
    if keys:
        assert set(result["networks"][0].keys()) == keys
    assert result.get("unknown_fields") == unknown_fields
    # back-compat: legacy `count` key preserved alongside returned_count
    assert result["count"] == result["returned_count"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "include,absent,unknown_sections",
    [
        # Each section is independent: include="dhcp" must not auto-add basic keys.
        ("dhcp", ["name"], None),
        # Typos surface as unknown_sections; the known section is still applied.
        ("dhcp,vpnn", [], ["vpnn"]),
    ],
)
async def test_get_network_details_summary_sections(include, absent, unknown_sections):
    raw = {"_id": "n2", "name": "IoT", "purpose": "corporate", "dhcpd_enabled": True, "dhcpd_start": "198.51.100.10"}
    with patch("unifi_network_mcp.tools.network.network_manager") as mock_nm:
        mock_nm.get_network_details = AsyncMock(return_value=raw)
        mock_nm._connection = _mock_conn()

        from unifi_network_mcp.tools.network import get_network_details

        result = await get_network_details("n2", summary=True, include=include)

    assert result["details"]["dhcpd_enabled"] is True
    for key in absent:
        assert key not in result["details"]
    assert result.get("unknown_sections") == unknown_sections
