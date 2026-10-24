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


def _mock_conn():
    c = MagicMock()
    c.site = "default"
    return c


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,total,returned",
    [({"search": "phone"}, 1, 1), ({"limit": 1}, 3, 1)],
)
async def test_list_clients_search_and_limit_report_total(kwargs, total, returned):
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_clients = AsyncMock(return_value=list(SAMPLE_CLIENTS))
        mock_cm.get_all_clients = AsyncMock(return_value=list(SAMPLE_CLIENTS))
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients(**kwargs)

    assert result["success"] is True
    assert result["total_count"] == total
    assert result["returned_count"] == returned
    # back-compat: legacy `count` key preserved alongside returned_count
    assert result["count"] == result["returned_count"]
    if "limit" in kwargs:
        assert result["limit"] == kwargs["limit"]
    if "search" in kwargs:
        assert result["clients"][0]["name"] == "Phone"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fields,expected_keys,unknown_fields",
    [("mac,name", {"mac", "name"}, None), ("mac,naame", {"mac"}, ["naame"])],
)
async def test_list_clients_fields_selects_subset_and_surfaces_unknown(fields, expected_keys, unknown_fields):
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_clients = AsyncMock(return_value=list(SAMPLE_CLIENTS))
        mock_cm.get_all_clients = AsyncMock(return_value=list(SAMPLE_CLIENTS))
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients(fields=fields)

    assert set(result["clients"][0].keys()) == expected_keys
    # typos surface so callers can self-correct
    assert result.get("unknown_fields") == unknown_fields


@pytest.mark.asyncio
async def test_name_and_hostname_are_distinct():
    # User alias (name) and DHCP hostname must stay separate.
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_clients = AsyncMock(return_value=list(SAMPLE_CLIENTS))
        mock_cm.get_all_clients = AsyncMock(return_value=list(SAMPLE_CLIENTS))
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients()

    laptop = next(c for c in result["clients"] if c.get("mac") == "aa:bb:cc:00:00:01")
    assert laptop["name"] == "Laptop"
    assert laptop["hostname"] == "laptop"


# ---------------------------------------------------------------------------
# get_client_details — opt-in section selection (default preserves the full object)
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


@pytest.mark.asyncio
async def test_get_client_details_summary_include_all_returns_every_section():
    # include="all" must populate every section: basic + network + wireless (wireless
    # only when the client isn't wired) + traffic + fingerprint.
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_client_details = AsyncMock(return_value=CLIENT_DETAIL_RAW)
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="all")

    c = result["client"]
    assert c["mac"] == "aa:bb:cc:00:00:01"  # basic
    assert c["network_id"] == "net1"  # network
    assert c["essid"] == "Home"  # wireless (client is wireless)
    assert c["tx_bytes"] == 1000  # traffic
    assert c["oui"] == "Acme"  # fingerprint


@pytest.mark.asyncio
async def test_list_clients_zero_items_case():
    # Controller returns empty -> total_count=0, returned_count=0, count=0, clients=[].
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_clients = AsyncMock(return_value=[])
        mock_cm.get_all_clients = AsyncMock(return_value=[])
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import list_clients

        result = await list_clients()

    assert result["success"] is True
    assert result["total_count"] == 0
    assert result["returned_count"] == 0
    assert result["count"] == 0
    assert result["clients"] == []


@pytest.mark.asyncio
async def test_get_client_details_not_found():
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_client_details = AsyncMock(return_value=None)
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:99:99:99")

    assert result["success"] is False
    assert "aa:bb:cc:99:99:99" in result["error"]


@pytest.mark.asyncio
async def test_get_client_details_reports_an_undetermined_lookup_as_an_error():
    from unifi_core.exceptions import UniFiOperationError

    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_client_details = AsyncMock(side_effect=UniFiOperationError("existence could not be determined"))
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:99:99:99")

    assert result == {
        "success": False,
        "error": "Failed to get client details for aa:bb:cc:99:99:99: existence could not be determined",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{}, {"summary": False}])
async def test_get_client_details_default_and_summary_false_preserve_full_object(kwargs):
    # Regression guard: default (and explicit summary=False) returns the full raw object in the
    # {success, site, client} envelope, no trimming and no summary_mode.
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_client_details = AsyncMock(return_value=CLIENT_DETAIL_RAW)
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details("aa:bb:cc:00:00:01", **kwargs)

    assert result["success"] is True
    assert "summary_mode" not in result and "include" not in result
    client = result["client"]
    assert client["tx_bytes"] == 1000
    assert client["oui"] == "Acme"
    assert client["essid"] == "Home"


@pytest.mark.asyncio
async def test_get_client_details_summary_sections_are_independent():
    # Each section is independent: basic excludes wireless/traffic/fingerprint, traffic populates
    # byte counters, and typos in include surface as `unknown_sections` while known ones still apply.
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_client_details = AsyncMock(return_value=CLIENT_DETAIL_RAW)
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import get_client_details

        basic_only = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="basic")
        with_traffic = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="traffic")
        with_typo = await get_client_details("aa:bb:cc:00:00:01", summary=True, include="basix,traffic")

    assert basic_only["summary_mode"] is True
    assert basic_only["client"]["mac"] == "aa:bb:cc:00:00:01"
    for key in ("essid", "tx_bytes", "oui"):
        assert key not in basic_only["client"]
    assert with_traffic["client"]["tx_bytes"] == 1000
    assert with_typo["client"]["tx_bytes"] == 1000
    assert with_typo.get("unknown_sections") == ["basix"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw,expected_status",
    [
        # Offline/historical clients lack `is_online`; status must be Offline, not defaulted to Online.
        ({"mac": "aa:bb:cc:00:00:05", "hostname": "ghost", "is_wired": True}, "Offline"),
        ({"mac": "aa:bb:cc:00:00:06", "hostname": "live", "is_wired": True, "is_online": True}, "Online"),
    ],
)
async def test_get_client_details_summary_status(raw, expected_status):
    with patch("unifi_network_mcp.tools.clients.client_manager") as mock_cm:
        mock_cm.get_client_details = AsyncMock(return_value=raw)
        mock_cm._connection = _mock_conn()

        from unifi_network_mcp.tools.clients import get_client_details

        result = await get_client_details(raw["mac"], summary=True, include="basic")

    assert result["client"]["status"] == expected_status
