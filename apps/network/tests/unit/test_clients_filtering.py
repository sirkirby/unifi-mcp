"""Tests for list_clients filtering and field selection."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SAMPLE_CLIENTS = [
    {
        "mac": "aa:bb:cc:00:00:01",
        "name": "Laptop",
        "hostname": "laptop",
        "ip": "192.0.2.10",
        "is_wired": False,
        "essid": "Home",
        "signal": -55,
        "channel": 36,
        "radio": "na",
        "_id": "c1",
    },
    {
        "mac": "aa:bb:cc:00:00:02",
        "name": "Printer",
        "hostname": "printer",
        "ip": "192.0.2.11",
        "is_wired": True,
        "_id": "c2",
    },
    {
        "mac": "aa:bb:cc:00:00:03",
        "name": "Phone",
        "hostname": "phone",
        "ip": "192.0.2.12",
        "is_wired": False,
        "essid": "Home",
        "signal": -61,
        "channel": 6,
        "radio": "ng",
        "_id": "c3",
    },
]


def _patch_mgr(clients):
    mock_conn = MagicMock()
    mock_conn.site = "default"
    p = patch("unifi_network_mcp.tools.clients.client_manager")
    mock = p.start()
    mock.get_clients = AsyncMock(return_value=list(clients))
    mock.get_all_clients = AsyncMock(return_value=list(clients))
    mock._connection = mock_conn
    return p, mock


@pytest.mark.asyncio
async def test_search_filters_by_substring():
    p, _ = _patch_mgr(SAMPLE_CLIENTS)
    try:
        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients(search="phone")
    finally:
        p.stop()
    assert result["success"] is True
    assert result["total_count"] == 1
    assert result["returned_count"] == 1
    assert result["clients"][0]["name"] == "Phone"


@pytest.mark.asyncio
async def test_limit_truncates_but_reports_total():
    p, _ = _patch_mgr(SAMPLE_CLIENTS)
    try:
        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients(limit=1)
    finally:
        p.stop()
    assert result["total_count"] == 3
    assert result["returned_count"] == 1
    assert result["limit"] == 1


@pytest.mark.asyncio
async def test_fields_selects_subset():
    # Valid on this branch: upstream/main (post-#299) emits a distinct `name` key.
    p, _ = _patch_mgr(SAMPLE_CLIENTS)
    try:
        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients(fields="mac,name")
    finally:
        p.stop()
    client = result["clients"][0]
    assert set(client.keys()) == {"mac", "name"}


@pytest.mark.asyncio
async def test_name_and_hostname_are_distinct_post_pr299():
    # Guards the #299 interaction: user alias (name) vs DHCP hostname stay separate.
    p, _ = _patch_mgr(SAMPLE_CLIENTS)
    try:
        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients()
    finally:
        p.stop()
    laptop = next(c for c in result["clients"] if c.get("mac") == "aa:bb:cc:00:00:01")
    assert laptop["name"] == "Laptop"
    assert laptop["hostname"] == "laptop"


# ---------------------------------------------------------------------------
# get_client_details — opt-in section selection (default preserves #300 full object)
# ---------------------------------------------------------------------------

CLIENT_DETAIL_RAW = {
    "mac": "aa:bb:cc:00:00:01",
    "name": "Laptop",
    "hostname": "laptop",
    "ip": "192.0.2.10",
    "is_wired": False,
    "is_online": True,
    "essid": "Home",
    "signal": -55,
    "tx_bytes": 1000,
    "rx_bytes": 2000,
    "oui": "Acme",
    "network_id": "net1",
}


def _patch_detail(client):
    mock_conn = MagicMock()
    mock_conn.site = "default"
    p = patch("unifi_network_mcp.tools.clients.client_manager")
    mock = p.start()
    mock.get_client_details = AsyncMock(return_value=client)
    mock._connection = mock_conn
    return p, mock


@pytest.mark.asyncio
async def test_get_client_details_default_preserves_pr300_full_object():
    # Regression guard: default (no args) must return the full raw object in the
    # {success, site, client} envelope — byte-for-byte the #300 behavior, no trimming.
    p, _ = _patch_detail(CLIENT_DETAIL_RAW)
    try:
        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:00:00:01")
    finally:
        p.stop()
    assert result["success"] is True
    assert "summary_mode" not in result and "include" not in result
    client = result["client"]
    # Full raw fields present (not trimmed away)
    assert client["tx_bytes"] == 1000
    assert client["oui"] == "Acme"
    assert client["essid"] == "Home"


@pytest.mark.asyncio
async def test_get_client_details_summary_trims_to_sections():
    # New behavior: summary=true trims to the named sections.
    p, _ = _patch_detail(CLIENT_DETAIL_RAW)
    try:
        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="basic")
    finally:
        p.stop()
    assert result["summary_mode"] is True
    client = result["client"]
    assert client["mac"] == "aa:bb:cc:00:00:01"
    # basic section excludes traffic + fingerprint
    assert "tx_bytes" not in client
    assert "oui" not in client


@pytest.mark.asyncio
async def test_get_client_details_not_found():
    p, _ = _patch_detail(None)
    try:
        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:99:99:99")
    finally:
        p.stop()
    assert result["success"] is False
    assert "aa:bb:cc:99:99:99" in result["error"]


@pytest.mark.asyncio
async def test_get_client_details_summary_status_offline_without_signal():
    # Offline/historical clients lack `is_online` and active-connection counters;
    # status must be derived as Offline, not defaulted to Online.
    offline_raw = {"mac": "aa:bb:cc:00:00:05", "hostname": "ghost", "is_wired": True}
    p, _ = _patch_detail(offline_raw)
    try:
        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:00:00:05", summary=True, include="basic")
    finally:
        p.stop()
    assert result["client"]["status"] == "Offline"


@pytest.mark.asyncio
async def test_get_client_details_summary_status_online_with_signal():
    online_raw = {"mac": "aa:bb:cc:00:00:06", "hostname": "live", "is_wired": True, "is_online": True}
    p, _ = _patch_detail(online_raw)
    try:
        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:00:00:06", summary=True, include="basic")
    finally:
        p.stop()
    assert result["client"]["status"] == "Online"


@pytest.mark.asyncio
async def test_get_client_details_summary_sections_are_independent():
    # wireless requested but absent-when-wired stays out; traffic populates when requested.
    p, _ = _patch_detail(CLIENT_DETAIL_RAW)  # wireless client with tx_bytes
    try:
        from unifi_network_mcp.tools.clients import get_client_details

        basic_only = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="basic")
        with_traffic = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="traffic")
    finally:
        p.stop()
    # basic excludes wireless + traffic sections
    assert "essid" not in basic_only["client"]
    assert "tx_bytes" not in basic_only["client"]
    # traffic section populates byte counters
    assert with_traffic["client"]["tx_bytes"] == 1000
