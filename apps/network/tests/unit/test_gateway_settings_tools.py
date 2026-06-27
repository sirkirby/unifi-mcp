"""Tests for the gateway (USG) settings tools — preview/confirm, warnings, errors."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")

SAMPLE_USG = {
    "_id": "usg1",
    "key": "usg",
    "upnp_enabled": False,
    "geo_ip_filtering_enabled": False,
    "ftp_module": True,
    "tcp_established_timeout": 7440,
    "dns_verification": {"setting_preference": "auto", "primary_dns_server": "1.1.1.1"},
}

_MGR = "unifi_network_mcp.tools.gateway_settings.gateway_settings_manager"


class TestGetGatewaySettings:
    @pytest.mark.asyncio
    async def test_get_returns_settings(self):
        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(return_value=SAMPLE_USG)
            from unifi_network_mcp.tools.gateway_settings import get_gateway_settings

            result = await get_gateway_settings()

        assert result["success"] is True
        assert result["settings"]["upnp_enabled"] is False
        assert result["settings"]["key"] == "usg"


class TestUpdateGatewaySettings:
    @pytest.mark.asyncio
    async def test_empty_update_data(self):
        from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

        result = await update_gateway_settings(update_data={}, confirm=True)
        assert result["success"] is False
        assert "cannot be empty" in result["error"]

    @pytest.mark.asyncio
    async def test_no_valid_fields(self):
        from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

        result = await update_gateway_settings(update_data={"bogus": 1, "id": "x"}, confirm=True)
        assert result["success"] is False
        assert "No valid mutable fields" in result["error"]

    @pytest.mark.asyncio
    async def test_preview_security_sensitive_warns(self):
        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(return_value=SAMPLE_USG)
            from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

            result = await update_gateway_settings(update_data={"upnp_enabled": True}, confirm=False)

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        assert result.get("warnings")
        assert "upnp_enabled" in result["warnings"][0]

    @pytest.mark.asyncio
    async def test_preview_non_sensitive_no_warning(self):
        # ALG modules are not in SECURITY_SENSITIVE_FIELDS → no warning.
        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(return_value=SAMPLE_USG)
            from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

            result = await update_gateway_settings(update_data={"ftp_module": False}, confirm=False)

        assert result["success"] is True
        assert result.get("requires_confirmation") is True
        assert result.get("warnings") is None

    @pytest.mark.asyncio
    async def test_confirm_success(self):
        updated = {**SAMPLE_USG, "upnp_enabled": True}
        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(side_effect=[SAMPLE_USG, updated])
            mgr.update_gateway_settings = AsyncMock(return_value=(True, None))
            from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

            result = await update_gateway_settings(update_data={"upnp_enabled": True}, confirm=True)

        assert result["success"] is True
        assert "upnp_enabled" in result["updated_fields"]
        assert result["settings"]["upnp_enabled"] is True

    @pytest.mark.asyncio
    async def test_confirm_error_surfaces(self):
        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(return_value=SAMPLE_USG)
            mgr.update_gateway_settings = AsyncMock(return_value=(False, "did not persist field(s): upnp_enabled"))
            from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

            result = await update_gateway_settings(update_data={"upnp_enabled": True}, confirm=True)

        assert result["success"] is False
        assert "upnp_enabled" in result["error"]

    @pytest.mark.asyncio
    async def test_every_sensitive_field_warns(self):
        from unifi_network_mcp.tools.gateway_settings import (
            SECURITY_SENSITIVE_FIELDS,
            update_gateway_settings,
        )

        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(return_value=SAMPLE_USG)
            for field in sorted(SECURITY_SENSITIVE_FIELDS):
                val = {"setting_preference": "manual"} if field == "dns_verification" else True
                result = await update_gateway_settings(update_data={field: val}, confirm=False)
                assert result.get("warnings"), f"{field} should warn"
                assert field in result["warnings"][0], f"{field} missing from warning text"

    @pytest.mark.asyncio
    async def test_confirm_manager_raises_surfaces_error(self):
        with patch(_MGR) as mgr:
            mgr.get_gateway_settings = AsyncMock(return_value=SAMPLE_USG)
            mgr.update_gateway_settings = AsyncMock(side_effect=RuntimeError("boom"))
            from unifi_network_mcp.tools.gateway_settings import update_gateway_settings

            result = await update_gateway_settings(update_data={"upnp_enabled": True}, confirm=True)

        assert result["success"] is False
        assert "Failed to update gateway settings" in result["error"]


def test_security_sensitive_is_subset_of_mutable():
    from unifi_core.network.models.gateway_settings import MUTABLE_FIELDS
    from unifi_network_mcp.tools.gateway_settings import SECURITY_SENSITIVE_FIELDS

    assert SECURITY_SENSITIVE_FIELDS <= MUTABLE_FIELDS
