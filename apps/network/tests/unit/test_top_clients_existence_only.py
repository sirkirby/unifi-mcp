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
