"""Tests for Dynamic DNS tool functions.

Tests tool-layer behavior: validation, preview/confirm flow, response format,
and secret redaction. Manager-level tests are in test_dynamic_dns_manager.py.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.redaction import REDACTED

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


# A sample without secrets, for generic list/get success assertions.
SAMPLE_ENTRY = {
    "_id": "ddns001",
    "site_id": "site1",
    "host_name": "home.example.com",
    "service": "dyndns",
    "login": "user",
    "interface": "wan",
}

# A sample carrying the secret, for redaction assertions.
SAMPLE_ENTRY_SECRET = {**SAMPLE_ENTRY, "x_password": "super-secret-token"}


# ---------------------------------------------------------------------------
# list_dynamic_dns
# ---------------------------------------------------------------------------


class TestListDynamicDns:
    @pytest.mark.asyncio
    async def test_list_success(self):
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.list_dynamic_dns = AsyncMock(return_value=[SAMPLE_ENTRY])
            mock_mgr._connection = mock_conn

            from unifi_network_mcp.tools.dynamic_dns import list_dynamic_dns

            result = await list_dynamic_dns()

        assert result["success"] is True
        assert result["count"] == 1
        assert result["entries"][0]["host_name"] == "home.example.com"
        assert result["entries"][0]["id"] == "ddns001"

    @pytest.mark.asyncio
    async def test_list_redacts_secret_when_policy_on(self):
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with (
            patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr,
            patch("unifi_network_mcp.tools.dynamic_dns.should_redact_sensitive_fields", return_value=True),
        ):
            mock_mgr.list_dynamic_dns = AsyncMock(return_value=[SAMPLE_ENTRY_SECRET])
            mock_mgr._connection = mock_conn

            from unifi_network_mcp.tools.dynamic_dns import list_dynamic_dns

            result = await list_dynamic_dns()

        assert result["entries"][0]["x_password"] == REDACTED

    @pytest.mark.asyncio
    async def test_list_shows_secret_when_policy_off(self):
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with (
            patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr,
            patch("unifi_network_mcp.tools.dynamic_dns.should_redact_sensitive_fields", return_value=False),
        ):
            mock_mgr.list_dynamic_dns = AsyncMock(return_value=[SAMPLE_ENTRY_SECRET])
            mock_mgr._connection = mock_conn

            from unifi_network_mcp.tools.dynamic_dns import list_dynamic_dns

            result = await list_dynamic_dns()

        assert result["entries"][0]["x_password"] == "super-secret-token"

    @pytest.mark.asyncio
    async def test_list_empty(self):
        mock_conn = MagicMock()
        mock_conn.site = "default"

        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.list_dynamic_dns = AsyncMock(return_value=[])
            mock_mgr._connection = mock_conn

            from unifi_network_mcp.tools.dynamic_dns import list_dynamic_dns

            result = await list_dynamic_dns()

        assert result["success"] is True
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_exception(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.list_dynamic_dns = AsyncMock(side_effect=Exception("Connection lost"))

            from unifi_network_mcp.tools.dynamic_dns import list_dynamic_dns

            result = await list_dynamic_dns()

        assert result["success"] is False
        assert "Failed to list" in result["error"]


# ---------------------------------------------------------------------------
# get_dynamic_dns_entry_details
# ---------------------------------------------------------------------------


class TestGetDynamicDnsDetails:
    @pytest.mark.asyncio
    async def test_get_found(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.get_dynamic_dns = AsyncMock(return_value=SAMPLE_ENTRY)

            from unifi_network_mcp.tools.dynamic_dns import get_dynamic_dns_entry_details

            result = await get_dynamic_dns_entry_details(entry_id="ddns001")

        assert result["success"] is True
        assert result["entry_id"] == "ddns001"
        assert result["details"]["host_name"] == "home.example.com"
        # get_details normalizes like list: '_id' -> 'id'
        assert result["details"]["id"] == "ddns001"
        assert "_id" not in result["details"]

    @pytest.mark.asyncio
    async def test_get_redacts_secret_when_policy_on(self):
        with (
            patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr,
            patch("unifi_network_mcp.tools.dynamic_dns.should_redact_sensitive_fields", return_value=True),
        ):
            mock_mgr.get_dynamic_dns = AsyncMock(return_value=SAMPLE_ENTRY_SECRET)

            from unifi_network_mcp.tools.dynamic_dns import get_dynamic_dns_entry_details

            result = await get_dynamic_dns_entry_details(entry_id="ddns001")

        assert result["details"]["x_password"] == REDACTED

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.get_dynamic_dns = AsyncMock(side_effect=UniFiNotFoundError("dynamic_dns", "nonexistent"))

            from unifi_network_mcp.tools.dynamic_dns import get_dynamic_dns_entry_details

            result = await get_dynamic_dns_entry_details(entry_id="nonexistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_get_exception(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.get_dynamic_dns = AsyncMock(side_effect=Exception("Timeout"))

            from unifi_network_mcp.tools.dynamic_dns import get_dynamic_dns_entry_details

            result = await get_dynamic_dns_entry_details(entry_id="ddns001")

        assert result["success"] is False
        assert "Failed to get" in result["error"]


# ---------------------------------------------------------------------------
# create_dynamic_dns
# ---------------------------------------------------------------------------


class TestCreateDynamicDns:
    @pytest.mark.asyncio
    async def test_create_preview(self):
        from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

        result = await create_dynamic_dns(
            entry_data={"host_name": "home.example.com", "service": "dyndns", "interface": "wan"},
            confirm=False,
        )

        assert result["success"] is True
        assert result.get("requires_confirmation") is True

    @pytest.mark.asyncio
    async def test_create_confirm_success(self):
        created = {"_id": "ddns_new", "host_name": "home.example.com", "service": "dyndns", "interface": "wan"}

        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.create_dynamic_dns = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

            result = await create_dynamic_dns(
                entry_data={"host_name": "home.example.com", "service": "dyndns", "interface": "wan"},
                confirm=True,
            )

        assert result["success"] is True
        assert "created successfully" in result["message"]
        assert result["details"]["_id"] == "ddns_new"

    @pytest.mark.asyncio
    async def test_create_confirm_redacts_secret(self):
        created = {"_id": "ddns_new", "host_name": "home.example.com", "service": "dyndns", "x_password": "sekret"}

        with (
            patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr,
            patch("unifi_network_mcp.tools.dynamic_dns.should_redact_sensitive_fields", return_value=True),
        ):
            mock_mgr.create_dynamic_dns = AsyncMock(return_value=created)

            from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

            result = await create_dynamic_dns(
                entry_data={"host_name": "home.example.com", "service": "dyndns", "x_password": "sekret"},
                confirm=True,
            )

        assert result["details"]["x_password"] == REDACTED

    @pytest.mark.asyncio
    async def test_create_preview_redacts_secret(self):
        """Preview (confirm=False) must not echo x_password in cleartext."""
        with patch("unifi_network_mcp.tools.dynamic_dns.should_redact_sensitive_fields", return_value=True):
            from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

            result = await create_dynamic_dns(
                entry_data={"host_name": "home.example.com", "service": "dyndns", "x_password": "sekret"},
                confirm=False,
            )

        assert result["preview"]["will_create"]["x_password"] == REDACTED

    @pytest.mark.asyncio
    async def test_create_missing_required_field(self):
        from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

        result = await create_dynamic_dns(
            entry_data={"host_name": "home.example.com"},  # no service
            confirm=True,
        )

        assert result["success"] is False
        assert "Validation error" in result["error"]

    @pytest.mark.asyncio
    async def test_create_manager_failure(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.create_dynamic_dns = AsyncMock(return_value=None)

            from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

            result = await create_dynamic_dns(
                entry_data={"host_name": "home.example.com", "service": "dyndns"},
                confirm=True,
            )

        assert result["success"] is False
        assert "Failed to create" in result["error"]

    @pytest.mark.asyncio
    async def test_create_rejects_unknown_fields(self):
        """Unknown/read-only keys are rejected with an actionable error, not
        silently dropped."""
        from unifi_network_mcp.tools.dynamic_dns import create_dynamic_dns

        result = await create_dynamic_dns(
            entry_data={
                "host_name": "home.example.com",
                "service": "dyndns",
                "bogus_field": "x",
            },
            confirm=False,
        )

        assert result["success"] is False
        assert "bogus_field" in result["error"]


# ---------------------------------------------------------------------------
# update_dynamic_dns
# ---------------------------------------------------------------------------


class TestUpdateDynamicDns:
    @pytest.mark.asyncio
    async def test_update_preview(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.get_dynamic_dns = AsyncMock(return_value=SAMPLE_ENTRY)

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="ddns001",
                update_data={"service": "noip"},
                confirm=False,
            )

        assert result["success"] is True
        assert result.get("requires_confirmation") is True

    @pytest.mark.asyncio
    async def test_update_preview_shows_current_state(self):
        """The preview fetches the current entry so the before/after is real,
        not an empty current_state."""
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.get_dynamic_dns = AsyncMock(return_value=SAMPLE_ENTRY)

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="ddns001",
                update_data={"service": "noip"},
                confirm=False,
            )

        # current reflects the fetched entry (was "dyndns"), proposed the change.
        assert result["preview"]["current"]["service"] == "dyndns"
        assert result["preview"]["proposed"]["service"] == "noip"

    @pytest.mark.asyncio
    async def test_update_preview_not_found(self):
        """A preview for a missing entry surfaces the not-found error."""
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.get_dynamic_dns = AsyncMock(side_effect=UniFiNotFoundError("dynamic_dns", "nope"))

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="nope",
                update_data={"service": "noip"},
                confirm=False,
            )

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_update_rejects_unknown_fields(self):
        """Unknown/read-only keys are rejected with an actionable error before
        any controller call, not silently dropped."""
        from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

        result = await update_dynamic_dns(
            entry_id="ddns001",
            update_data={"service": "noip", "bogus_field": "x"},
            confirm=True,
        )

        assert result["success"] is False
        assert "bogus_field" in result["error"]

    @pytest.mark.asyncio
    async def test_update_confirm_success(self):
        merged = {**SAMPLE_ENTRY, "service": "noip"}
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.update_dynamic_dns = AsyncMock(return_value=merged)

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="ddns001",
                update_data={"service": "noip"},
                confirm=True,
            )

        assert result["success"] is True
        assert "updated successfully" in result["message"]

    @pytest.mark.asyncio
    async def test_update_preview_redacts_secret(self):
        """Preview (confirm=False) must not echo x_password in cleartext."""
        with (
            patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr,
            patch("unifi_network_mcp.tools.dynamic_dns.should_redact_sensitive_fields", return_value=True),
        ):
            mock_mgr.get_dynamic_dns = AsyncMock(return_value=SAMPLE_ENTRY)

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="ddns001",
                update_data={"x_password": "sekret"},
                confirm=False,
            )

        assert result["preview"]["proposed"]["x_password"] == REDACTED

    @pytest.mark.asyncio
    async def test_update_not_found(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.update_dynamic_dns = AsyncMock(side_effect=UniFiNotFoundError("dynamic_dns", "nonexistent"))

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="nonexistent",
                update_data={"service": "noip"},
                confirm=True,
            )

        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_update_empty_data(self):
        from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

        result = await update_dynamic_dns(
            entry_id="ddns001",
            update_data={},
            confirm=True,
        )

        assert result["success"] is False
        assert "No fields provided" in result["error"]

    @pytest.mark.asyncio
    async def test_update_manager_exception(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.update_dynamic_dns = AsyncMock(side_effect=Exception("Connection refused"))

            from unifi_network_mcp.tools.dynamic_dns import update_dynamic_dns

            result = await update_dynamic_dns(
                entry_id="ddns001",
                update_data={"service": "noip"},
                confirm=True,
            )

        assert result["success"] is False
        assert "Failed to update" in result["error"]


# ---------------------------------------------------------------------------
# delete_dynamic_dns
# ---------------------------------------------------------------------------


class TestDeleteDynamicDns:
    @pytest.mark.asyncio
    async def test_delete_preview(self):
        from unifi_network_mcp.tools.dynamic_dns import delete_dynamic_dns

        result = await delete_dynamic_dns(entry_id="ddns001", confirm=False)

        assert result["success"] is True
        assert result.get("requires_confirmation") is True

    @pytest.mark.asyncio
    async def test_delete_confirm_success(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.delete_dynamic_dns = AsyncMock(return_value=True)

            from unifi_network_mcp.tools.dynamic_dns import delete_dynamic_dns

            result = await delete_dynamic_dns(entry_id="ddns001", confirm=True)

        assert result["success"] is True
        assert "deleted successfully" in result["message"]
        mock_mgr.delete_dynamic_dns.assert_called_once_with("ddns001")

    @pytest.mark.asyncio
    async def test_delete_manager_failure(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.delete_dynamic_dns = AsyncMock(return_value=False)

            from unifi_network_mcp.tools.dynamic_dns import delete_dynamic_dns

            result = await delete_dynamic_dns(entry_id="ddns001", confirm=True)

        assert result["success"] is False
        assert "Failed to delete" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_exception(self):
        with patch("unifi_network_mcp.tools.dynamic_dns.dynamic_dns_manager") as mock_mgr:
            mock_mgr.delete_dynamic_dns = AsyncMock(side_effect=Exception("Connection refused"))

            from unifi_network_mcp.tools.dynamic_dns import delete_dynamic_dns

            result = await delete_dynamic_dns(entry_id="ddns001", confirm=True)

        assert result["success"] is False
        assert "Connection refused" in result["error"]
