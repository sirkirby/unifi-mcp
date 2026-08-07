"""Validation parity tests for guest authorization."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_authorize_guest_rejects_invalid_optional_quota_before_lookup() -> None:
    from unifi_network_mcp.tools import clients

    manager = MagicMock()
    manager.get_client_details = AsyncMock()
    with patch.object(clients, "client_manager", manager):
        result = await clients.authorize_guest(
            "AA:BB:CC:DD:EE:FF",
            up_kbps=0,
            confirm=True,
        )

    assert result["success"] is False
    assert "greater than or equal to 1" in result["error"]
    manager.get_client_details.assert_not_called()
