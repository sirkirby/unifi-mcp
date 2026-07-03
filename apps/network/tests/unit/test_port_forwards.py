"""Tests for the port forward delete tool (unifi_delete_port_forward)."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


# ---------------------------------------------------------------------------
# delete_port_forward
# ---------------------------------------------------------------------------


class TestDeletePortForward:
    """Test the unifi_delete_port_forward tool."""

    @pytest.mark.asyncio
    async def test_delete_success(self):
        """Confirmed delete should call the manager and return success."""
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.delete_port_forward = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.port_forwards import delete_port_forward

            result = await delete_port_forward(port_forward_id="pf_001", confirm=True)

        assert result["success"] is True
        assert "deleted successfully" in result["message"]
        mock_fm.delete_port_forward.assert_called_once_with("pf_001")

    @pytest.mark.asyncio
    async def test_delete_preview(self):
        """Unconfirmed delete should return a delete preview and NOT call the manager."""
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.delete_port_forward = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.port_forwards import delete_port_forward

            result = await delete_port_forward(port_forward_id="pf_001", confirm=False)

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        assert result.get("action") == "delete"
        assert result.get("warnings")  # a non-empty warning is surfaced
        mock_fm.delete_port_forward.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_manager_failure(self):
        """Delete should return an error when the manager returns False."""
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.delete_port_forward = AsyncMock(return_value=False)

            from unifi_network_mcp.tools.port_forwards import delete_port_forward

            result = await delete_port_forward(port_forward_id="pf_001", confirm=True)

        assert result["success"] is False
        assert "Failed to delete" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_not_found(self):
        """A UniFiNotFoundError from the manager surfaces as a clean error."""
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.delete_port_forward = AsyncMock(side_effect=UniFiNotFoundError("port_forward", "pf_missing"))

            from unifi_network_mcp.tools.port_forwards import delete_port_forward

            result = await delete_port_forward(port_forward_id="pf_missing", confirm=True)

        assert result["success"] is False
        assert "pf_missing" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_generic_exception_handled(self):
        """A non-UniFi exception from the manager is caught and returned as an error, not raised."""
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.delete_port_forward = AsyncMock(side_effect=RuntimeError("boom"))

            from unifi_network_mcp.tools.port_forwards import delete_port_forward

            result = await delete_port_forward(port_forward_id="pf_001", confirm=True)

        assert result["success"] is False
        assert "Failed to delete port forward" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_requires_id(self):
        """An empty port_forward_id is rejected before any manager call."""
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.delete_port_forward = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.port_forwards import delete_port_forward

            result = await delete_port_forward(port_forward_id="", confirm=True)

        assert result["success"] is False
        assert "required" in result["error"]
        mock_fm.delete_port_forward.assert_not_called()
