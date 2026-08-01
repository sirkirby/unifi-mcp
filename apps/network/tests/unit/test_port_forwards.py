"""Tests for port-forward tools."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError, UniFiOperationError

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


# ---------------------------------------------------------------------------
# create_port_forward
# ---------------------------------------------------------------------------


class TestCreatePortForward:
    @pytest.mark.asyncio
    async def test_full_create_maps_to_controller_fields(self):
        created = {"_id": "pf_001", "name": "Web Server", "fwd": "192.168.1.10"}
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.create_port_forward = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.port_forwards import create_port_forward

            result = await create_port_forward(
                {
                    "name": "Web Server",
                    "dst_port": "443",
                    "fwd_port": "8443",
                    "fwd_ip": "192.168.1.10",
                    "protocol": "tcp_udp",
                }
            )

        assert result["success"] is True
        payload = mock_fm.create_port_forward.await_args.args[0]
        assert payload["fwd"] == "192.168.1.10"
        assert payload["proto"] == "tcp/udp"
        assert "fwd_ip" not in payload
        assert "fwd_protocol" not in payload

    @pytest.mark.asyncio
    async def test_full_create_omits_empty_source(self):
        created = {"_id": "pf_001", "name": "Web Server", "fwd": "192.168.1.10"}
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.create_port_forward = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.port_forwards import create_port_forward

            await create_port_forward(
                {
                    "name": "Web Server",
                    "dst_port": "443",
                    "fwd_port": "8443",
                    "fwd_ip": "192.168.1.10",
                    "src_ip": "",
                }
            )

        payload = mock_fm.create_port_forward.await_args.args[0]
        assert "src" not in payload

    @pytest.mark.asyncio
    async def test_simple_create_preview_stays_user_facing(self):
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            from unifi_network_mcp.tools.port_forwards import create_simple_port_forward

            result = await create_simple_port_forward(
                {"name": "Web Server", "ext_port": "443", "to_ip": "192.168.1.10"},
                confirm=False,
            )

        assert result["preview"]["fwd_ip"] == "192.168.1.10"
        assert result["preview"]["protocol"] == "tcp_udp"
        assert "fwd" not in result["preview"]
        mock_fm.create_port_forward.assert_not_called()

    @pytest.mark.asyncio
    async def test_simple_create_confirm_maps_to_controller_fields(self):
        created = {"_id": "pf_001", "name": "Web Server", "fwd": "192.168.1.10"}
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.create_port_forward = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.port_forwards import create_simple_port_forward

            result = await create_simple_port_forward(
                {
                    "name": "Web Server",
                    "ext_port": "443",
                    "int_port": "8443",
                    "to_ip": "192.168.1.10",
                    "protocol": "both",
                    "enabled": False,
                },
                confirm=True,
            )

        assert result["success"] is True
        payload = mock_fm.create_port_forward.await_args.args[0]
        assert payload == {
            "name": "Web Server",
            "dst_port": "443",
            "fwd_port": "8443",
            "fwd": "192.168.1.10",
            "proto": "tcp/udp",
            "enabled": False,
        }


# ---------------------------------------------------------------------------
# update_port_forward
# ---------------------------------------------------------------------------


class TestUpdatePortForward:
    @pytest.mark.asyncio
    async def test_preview_uses_normalized_current_state(self):
        current = MagicMock(
            raw={
                "_id": "pf_001",
                "name": "Web Server",
                "fwd": "192.168.1.10",
                "proto": "tcp",
            }
        )
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(return_value=current)

            from unifi_network_mcp.tools.port_forwards import update_port_forward

            result = await update_port_forward(
                port_forward_id="pf_001",
                update_data={"fwd_ip": "192.168.1.20"},
                confirm=False,
            )

        assert result["success"] is True
        assert result["resource_name"] == "Web Server"
        assert result["preview"]["current"]["fwd_ip"] == "192.168.1.10"
        assert result["preview"]["proposed"]["fwd_ip"] == "192.168.1.20"
        mock_fm.update_port_forward.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_normalizes_protocol_to_public_value(self):
        current = MagicMock(raw={"_id": "pf_001", "name": "Web Server", "proto": "tcp/udp"})
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(return_value=current)

            from unifi_network_mcp.tools.port_forwards import update_port_forward

            result = await update_port_forward(
                port_forward_id="pf_001",
                update_data={"protocol": "tcp_udp"},
                confirm=False,
            )

        assert result["preview"]["current"]["protocol"] == "tcp_udp"
        assert result["preview"]["proposed"]["protocol"] == "tcp_udp"

    @pytest.mark.asyncio
    async def test_confirm_maps_forward_ip_to_controller_field(self):
        current = MagicMock(raw={"_id": "pf_001", "name": "Web Server", "fwd": "192.168.1.10"})
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(return_value=current)
            mock_fm.update_port_forward = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.port_forwards import update_port_forward

            result = await update_port_forward(
                port_forward_id="pf_001",
                update_data={"fwd_ip": "192.168.1.20"},
                confirm=True,
            )

        assert result["success"] is True
        assert result["updated_fields"] == ["fwd_ip"]
        mock_fm.update_port_forward.assert_awaited_once_with("pf_001", {"fwd": "192.168.1.20"})

    @pytest.mark.asyncio
    async def test_persistence_failure_returns_structured_error(self):
        current = MagicMock(raw={"_id": "pf_001", "name": "Web Server", "fwd": "192.168.1.10"})
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(return_value=current)
            mock_fm.update_port_forward = AsyncMock(
                side_effect=UniFiOperationError("Controller accepted the request but did not persist field(s): fwd")
            )

            from unifi_network_mcp.tools.port_forwards import update_port_forward

            result = await update_port_forward(
                port_forward_id="pf_001",
                update_data={"fwd_ip": "192.168.1.20"},
                confirm=True,
            )

        assert result["success"] is False
        assert "did not persist field(s): fwd" in result["error"]

    @pytest.mark.asyncio
    async def test_prefetch_not_found_returns_structured_error(self):
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(side_effect=UniFiNotFoundError("port_forward", "missing"))

            from unifi_network_mcp.tools.port_forwards import update_port_forward

            result = await update_port_forward(
                port_forward_id="missing",
                update_data={"fwd_ip": "192.168.1.20"},
                confirm=False,
            )

        assert result == {"success": False, "error": "port_forward 'missing' not found"}


# ---------------------------------------------------------------------------
# toggle_port_forward
# ---------------------------------------------------------------------------


class TestTogglePortForward:
    @pytest.mark.asyncio
    async def test_preview_normalizes_forward_ip(self):
        current = MagicMock(
            raw={
                "_id": "pf_001",
                "name": "Web Server",
                "enabled": True,
                "fwd": "192.168.1.10",
                "fwd_port": "8443",
            }
        )
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(return_value=current)

            from unifi_network_mcp.tools.port_forwards import toggle_port_forward

            result = await toggle_port_forward("pf_001", confirm=False)

        assert result["preview"]["current"]["fwd_ip"] == "192.168.1.10"
        mock_fm.update_port_forward.assert_not_called()

    @pytest.mark.asyncio
    async def test_persistence_failure_returns_structured_error(self):
        current = MagicMock(raw={"_id": "pf_001", "name": "Web Server", "enabled": True})
        with patch("unifi_network_mcp.tools.port_forwards.firewall_manager") as mock_fm:
            mock_fm.get_port_forward_by_id = AsyncMock(return_value=current)
            mock_fm.update_port_forward = AsyncMock(
                side_effect=UniFiOperationError("Controller accepted the request but did not persist field(s): enabled")
            )

            from unifi_network_mcp.tools.port_forwards import toggle_port_forward

            result = await toggle_port_forward("pf_001", confirm=True)

        assert result["success"] is False
        assert "did not persist field(s): enabled" in result["error"]


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
