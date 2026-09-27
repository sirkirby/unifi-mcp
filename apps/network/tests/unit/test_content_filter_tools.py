"""Tests for content filtering tool preview and confirmation behavior."""

import os
from unittest.mock import AsyncMock, patch

import pytest

from unifi_core.exceptions import UniFiNotFoundError

os.environ.setdefault("UNIFI_HOST", "127.0.0.1")
os.environ.setdefault("UNIFI_USERNAME", "test")
os.environ.setdefault("UNIFI_PASSWORD", "test")


class TestCreateContentFilter:
    @pytest.mark.asyncio
    async def test_preview_stays_public_and_does_not_write(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            from unifi_network_mcp.tools.content_filtering import create_content_filter

            result = await create_content_filter(
                {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"], "schedule_days": ["mon"]},
                confirm=False,
            )
        assert result["requires_confirmation"] is True
        assert result["preview"]["will_create"]["schedule_days"] == ["mon"]
        assert result["preview"]["will_create"]["schedule_mode"] == "ALWAYS"
        assert result["preview"]["will_create"]["schedule_time_all_day"] is True
        assert result["preview"]["will_create"]["enabled"] is False
        manager.create_content_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_preserves_explicit_schedule_choice(self):
        data = {
            "name": "Kids",
            "network_ids": ["net"],
            "blocked_categories": ["FAMILY"],
            "schedule_mode": "EVERY_WEEK",
            "schedule_days": ["mon"],
            "schedule_time_all_day": False,
        }
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            from unifi_network_mcp.tools.content_filtering import create_content_filter

            result = await create_content_filter(data, confirm=False)
        assert result["preview"]["will_create"]["schedule_mode"] == "EVERY_WEEK"
        assert result["preview"]["will_create"]["schedule_days"] == ["mon"]
        assert result["preview"]["will_create"]["schedule_time_all_day"] is False
        manager.create_content_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_confirm_delegates(self):
        data = {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"]}
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            manager.create_content_filter = AsyncMock(
                return_value={
                    "_id": "cf-new",
                    "name": "Kids",
                    "enabled": False,
                    "categories": ["FAMILY"],
                    "network_ids": ["net"],
                    "schedule": {"mode": "EVERY_WEEK", "repeat_on_days": ["mon"]},
                }
            )
            from unifi_network_mcp.tools.content_filtering import create_content_filter

            result = await create_content_filter(data, confirm=True)
        assert result["success"] is True
        assert result["data"]["id"] == "cf-new"
        assert result["data"]["blocked_categories"] == ["FAMILY"]
        assert result["data"]["schedule_mode"] == "EVERY_WEEK"
        assert result["data"]["schedule_days"] == ["mon"]
        assert "_id" not in result["data"]
        assert "categories" not in result["data"]
        assert "schedule" not in result["data"]
        manager.create_content_filter.assert_awaited_once_with(data)

    @pytest.mark.asyncio
    async def test_rejects_ambiguous_scope(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            from unifi_network_mcp.tools.content_filtering import create_content_filter

            result = await create_content_filter({"name": "Kids", "blocked_categories": ["FAMILY"]}, confirm=True)
        assert result["success"] is False
        manager.create_content_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_categories_rejected_before_preview(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            from unifi_network_mcp.tools.content_filtering import create_content_filter

            result = await create_content_filter({"name": "Kids", "network_ids": ["net"]}, confirm=False)
        assert result["success"] is False
        manager.create_content_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_uncertain_result_is_not_reported_as_success(self):
        data = {"name": "Kids", "network_ids": ["net"], "blocked_categories": ["FAMILY"]}
        uncertain = {"success": False, "uncertain": True, "error": "List profiles before retrying."}
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            manager.create_content_filter = AsyncMock(return_value=uncertain)
            from unifi_network_mcp.tools.content_filtering import create_content_filter

            result = await create_content_filter(data, confirm=True)
        assert result == uncertain


class TestUpdateContentFilter:
    @pytest.mark.asyncio
    async def test_preview_preserves_blocked_categories_alias(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as mock_manager:
            mock_manager.get_content_filter_by_id = AsyncMock(
                return_value={"_id": "cf1", "name": "Kids", "categories": ["FAMILY"]}
            )
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"blocked_categories": ["MALWARE", "PHISHING"]},
                confirm=False,
            )

        assert result["requires_confirmation"] is True
        assert result["resource_name"] == "Kids"
        assert result["preview"]["current"] == {"blocked_categories": ["FAMILY"]}
        assert result["preview"]["proposed"] == {"blocked_categories": ["MALWARE", "PHISHING"]}
        mock_manager.get_content_filter_by_id.assert_awaited_once_with("cf1")
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
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            manager.get_content_filter_by_id = AsyncMock(
                return_value={"_id": "cf1", "name": "Kids", "schedule": {"mode": "ALWAYS", "repeat_on_days": ["mon"]}}
            )
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter(
                filter_id="cf1",
                filter_data={"schedule_mode": "EVERY_DAY"},
                confirm=False,
            )

        assert result["requires_confirmation"] is True
        assert result["preview"]["current"] == {"schedule_mode": "ALWAYS"}
        assert result["preview"]["proposed"] == {"schedule_mode": "EVERY_DAY"}

    @pytest.mark.asyncio
    async def test_preview_categories_alias_has_matching_current_key(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            manager.get_content_filter_by_id = AsyncMock(return_value={"_id": "cf1", "categories": ["FAMILY"]})
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter("cf1", {"categories": ["MALWARE"]}, confirm=False)
        assert result["preview"]["current"] == {"categories": ["FAMILY"]}
        assert result["preview"]["proposed"] == {"categories": ["MALWARE"]}

    @pytest.mark.asyncio
    async def test_preview_applies_response_redaction_policy(self):
        with (
            patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager,
            patch("unifi_network_mcp.tools.content_filtering.should_redact_sensitive_fields", return_value=True),
            patch("unifi_network_mcp.tools.content_filtering.redact_sensitive_fields") as redact,
        ):
            manager.get_content_filter_by_id = AsyncMock(return_value={"_id": "cf1", "enabled": True})
            redact.side_effect = lambda payload, *, redact_sensitive: payload
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter("cf1", {"enabled": False}, confirm=False)
        assert result["preview"]["current"] == {"enabled": True}
        assert result["preview"]["proposed"] == {"enabled": False}
        redact.assert_called_once()
        assert redact.call_args.kwargs == {"redact_sensitive": True}

    @pytest.mark.asyncio
    async def test_preview_not_found_is_error_without_write(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            manager.get_content_filter_by_id = AsyncMock(side_effect=UniFiNotFoundError("content_filter", "cf1"))
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter("cf1", {"enabled": False}, confirm=False)
        assert result == {"success": False, "error": "Failed to preview content filter update: profile not found"}
        manager.update_content_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_preview_read_failure_is_safe_error_without_write(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            manager.get_content_filter_by_id = AsyncMock(side_effect=RuntimeError("private controller detail"))
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter("cf1", {"enabled": False}, confirm=False)
        assert result == {"success": False, "error": "Failed to preview content filter update: RuntimeError"}
        manager.update_content_filter.assert_not_called()

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

    @pytest.mark.asyncio
    async def test_bad_schedule_rejected_before_preview(self):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter("cf1", {"schedule_days": ["MONDAY"]}, confirm=False)
        assert result["success"] is False
        manager.update_content_filter.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("filter_data", [{"name": " "}, {"blocked_categories": []}, {"categories": []}])
    async def test_empty_name_or_categories_rejected_before_read_or_write(self, filter_data):
        with patch("unifi_network_mcp.tools.content_filtering.content_filter_manager") as manager:
            from unifi_network_mcp.tools.content_filtering import update_content_filter

            result = await update_content_filter("cf1", filter_data, confirm=False)
        assert result["success"] is False
        manager.get_content_filter_by_id.assert_not_called()
        manager.update_content_filter.assert_not_called()
