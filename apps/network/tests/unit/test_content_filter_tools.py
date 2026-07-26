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
    async def test_confirm_passes_public_alias_to_manager(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as mock_manager:
            mock_manager.update_content_filter = AsyncMock(return_value={"name": "Default"})
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"blocked_categories": ["MALWARE", "PHISHING"]},
                confirm=True,
            )

        assert result["success"] is True
        mock_manager.update_content_filter.assert_awaited_once_with(
            "cf1", {"blocked_categories": ["MALWARE", "PHISHING"]}
        )
