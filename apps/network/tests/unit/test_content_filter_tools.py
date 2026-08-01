"""Tests for content filtering tool preview and confirmation behavior."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


class TestUpdateContentFilter:
    @pytest.mark.asyncio
    async def test_preview_preserves_blocked_categories_alias(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as mock_manager:
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"blocked_categories": ["MALWARE", "PHISHING"]},
                confirm=False,
            )

        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"] == {"blocked_categories": ["MALWARE", "PHISHING"]}
        mock_manager.update_content_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_translates_alias_to_controller_dialect(self):
        """The controller rejects blocked_categories outright, so the write path must rename it."""
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as mock_manager:
            mock_manager.update_content_filter = AsyncMock(return_value={"name": "Default"})
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"blocked_categories": ["MALWARE", "PHISHING"]},
                confirm=True,
            )

        assert result["success"] is True
        mock_manager.update_content_filter.assert_awaited_once_with("cf1", {"categories": ["MALWARE", "PHISHING"]})

    @pytest.mark.asyncio
    async def test_confirm_nests_schedule_mode(self):
        """schedule_mode must reach the manager nested, or the controller 400s."""
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as mock_manager:
            mock_manager.update_content_filter = AsyncMock(return_value={"name": "Default"})
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"schedule_mode": "EVERY_DAY"},
                confirm=True,
            )

        assert result["success"] is True
        mock_manager.update_content_filter.assert_awaited_once_with("cf1", {"schedule": {"mode": "EVERY_DAY"}})

    @pytest.mark.asyncio
    async def test_preview_keeps_schedule_mode_in_caller_dialect(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager"):
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"schedule_mode": "EVERY_DAY"},
                confirm=False,
            )

        assert result["requires_confirmation"] is True
        assert result["preview"]["proposed"] == {"schedule_mode": "EVERY_DAY"}

    @pytest.mark.asyncio
    async def test_unknown_fields_are_rejected(self):
        """The endpoint 400s on unrecognised fields, so they must never reach the controller."""
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as mock_manager:
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"not_a_real_field": "x"},
                confirm=True,
            )

        assert result["success"] is False
        mock_manager.update_content_filter.assert_not_called()
