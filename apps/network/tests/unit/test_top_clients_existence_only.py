"""``unifi_get_top_clients`` enriches names through ``get_client_details``.

Every entry it enriches costs a client lookup; a client past the /rest/user
row cap would otherwise cost a per-MAC controller request per entry, and the
name enrichment only needs to know the client exists (Core ``existence_only``).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_top_clients_enrichment_asks_for_existence_only():
    with (
        patch("unifi_network_mcp.tools.stats.stats_manager") as mock_sm,
        patch("unifi_network_mcp.tools.stats.client_manager") as mock_cm,
    ):
        mock_sm._connection = MagicMock(site="default")
        mock_sm.get_top_clients = AsyncMock(return_value=[{"mac": "aa:bb:cc:dd:ee:ff", "rx_bytes": 1, "tx_bytes": 2}])
        mock_cm.get_client_details = AsyncMock(
            return_value=SimpleNamespace(mac="aa:bb:cc:dd:ee:ff", raw={"mac": "aa:bb:cc:dd:ee:ff", "name": "printer"})
        )

        from unifi_network_mcp.tools.stats import get_top_clients

        result = await get_top_clients(duration="daily", limit=1)

    assert result["success"] is True
    mock_cm.get_client_details.assert_awaited_once_with("aa:bb:cc:dd:ee:ff", existence_only=True)


@pytest.mark.asyncio
async def test_top_clients_name_lookup_is_best_effort_per_row(caplog):
    """A client that left inventory since the window keeps its row, MAC and bytes."""
    import logging

    from unifi_core.exceptions import UniFiNotFoundError

    gone_mac = "aa:bb:cc:00:00:01"
    rows = [
        {"mac": gone_mac, "upload_bytes": 50 * 1024**3, "download_bytes": 1, "total_bytes": 50 * 1024**3 + 1},
        {"mac": "aa:bb:cc:00:00:02", "upload_bytes": 5, "download_bytes": 5, "total_bytes": 10},
    ]

    async def lookup(mac, existence_only=False):
        if mac == gone_mac:
            raise UniFiNotFoundError("client", gone_mac)
        return SimpleNamespace(raw={"mac": mac, "name": "laptop"})

    with (
        patch("unifi_network_mcp.tools.stats.stats_manager") as mock_sm,
        patch("unifi_network_mcp.tools.stats.client_manager") as mock_cm,
        caplog.at_level(logging.DEBUG),
    ):
        mock_sm._connection = MagicMock(site="default")
        mock_sm.get_top_clients = AsyncMock(return_value=rows)
        mock_cm.get_client_details = AsyncMock(side_effect=lookup)

        from unifi_network_mcp.tools.stats import get_top_clients

        result = await get_top_clients(duration="daily", limit=2)

    assert result["success"] is True
    first, second = result["top_clients"]
    assert first["mac"] == gone_mac and first["upload_bytes"] == 50 * 1024**3
    assert second["hostname"] == "laptop"
    assert gone_mac not in caplog.text
    assert "name" not in rows[1], "enrichment must not mutate the manager's (cached) rows"
