"""Tests for the cross-product location timeline tool."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from unifi_core.event_timeline import NormalizedEvent
from unifi_mcp_relay.location_timeline import (
    TOOL_ANNOTATIONS,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    _normalize_product_events,
    build_timeline_response,
    build_timeline_summary,
    handle_location_timeline,
    validate_timeline_input,
)


class TestValidateTimelineInput:
    """Test input validation for the timeline tool."""

    def test_valid_input(self):
        errors = validate_timeline_input(
            start_time="2026-03-24T00:00:00Z",
            end_time="2026-03-24T23:59:59Z",
        )
        assert errors == []

    def test_missing_start_time(self):
        errors = validate_timeline_input(start_time="", end_time="2026-03-24T23:59:59Z")
        assert any("start_time" in e for e in errors)

    def test_end_before_start(self):
        errors = validate_timeline_input(
            start_time="2026-03-24T23:59:59Z",
            end_time="2026-03-24T00:00:00Z",
        )
        assert any("before" in e.lower() or "after" in e.lower() for e in errors)

    def test_invalid_iso_format(self):
        errors = validate_timeline_input(
            start_time="not-a-date",
            end_time="2026-03-24T23:59:59Z",
        )
        assert any("start_time" in e for e in errors)

    def test_location_id_in_local_mode_returns_error(self):
        errors = validate_timeline_input(
            start_time="2026-03-24T00:00:00Z",
            end_time="2026-03-24T23:59:59Z",
            location_id="loc_123",
            is_relay_mode=False,
        )
        assert any("relay" in e.lower() for e in errors)

    def test_location_id_in_relay_mode_ok(self):
        errors = validate_timeline_input(
            start_time="2026-03-24T00:00:00Z",
            end_time="2026-03-24T23:59:59Z",
            location_id="loc_123",
            is_relay_mode=True,
        )
        assert errors == []


class TestBuildTimelineSummary:
    """Test summary generation from events."""

    def test_empty_events(self):
        summary = build_timeline_summary([])
        assert summary["total_events"] == 0
        assert summary["by_location"] == {}

    def test_counts_by_product(self):
        events = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
                product="network",
                event_type="a",
                summary="a",
            ),
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 2, 0, tzinfo=timezone.utc),
                product="network",
                event_type="b",
                summary="b",
            ),
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 3, 0, tzinfo=timezone.utc),
                product="protect",
                event_type="c",
                summary="c",
            ),
        ]
        summary = build_timeline_summary(events)
        assert summary["by_product"]["network"] == 2
        assert summary["by_product"]["protect"] == 1

    def test_counts_by_location(self):
        events = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
                product="network",
                event_type="a",
                summary="a",
                location_id="loc_1",
                location_name="Home",
            ),
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 2, 0, tzinfo=timezone.utc),
                product="protect",
                event_type="b",
                summary="b",
                location_id="loc_2",
                location_name="Office",
            ),
        ]
        summary = build_timeline_summary(events)
        assert summary["by_location"]["loc_1"] == 1
        assert summary["by_location"]["loc_2"] == 1


class TestBuildTimelineResponse:
    """Test final response construction."""

    def test_success_response_shape(self):
        events = [
            NormalizedEvent(
                timestamp=datetime(2026, 3, 24, 1, 0, tzinfo=timezone.utc),
                product="network",
                event_type="a",
                summary="a",
            ),
        ]
        response = build_timeline_response(events)
        assert response["success"] is True
        assert "timeline" in response["data"]
        assert "summary" in response["data"]
        assert len(response["data"]["timeline"]) == 1


class TestToolConstants:
    """Verify the relay-native tool constants are well-formed."""

    def test_tool_name(self):
        assert TOOL_NAME == "unifi_location_timeline"

    def test_input_schema_has_required_fields(self):
        assert "start_time" in TOOL_INPUT_SCHEMA["properties"]
        assert "end_time" in TOOL_INPUT_SCHEMA["properties"]
        assert TOOL_INPUT_SCHEMA["required"] == ["start_time", "end_time"]

    def test_annotations_read_only(self):
        assert TOOL_ANNOTATIONS["readOnlyHint"] is True
        assert TOOL_ANNOTATIONS["destructiveHint"] is False


class TestNormalizeProductEvents:
    """Test raw event normalization."""

    def test_normalizes_iso_timestamp(self):
        raw = [{"timestamp": "2026-03-24T10:00:00+00:00", "type": "motion", "msg": "Motion detected"}]
        events = _normalize_product_events("protect", raw, location_id="loc_1", location_name="Home")
        assert len(events) == 1
        assert events[0].product == "protect"
        assert events[0].event_type == "motion"
        assert events[0].summary == "Motion detected"
        assert events[0].location_id == "loc_1"
        assert events[0].location_name == "Home"

    def test_normalizes_epoch_ms_timestamp(self):
        # 2026-03-24T10:00:00Z in epoch ms
        epoch_ms = 1774440000000
        raw = [{"timestamp": epoch_ms, "type": "badge_scan", "description": "Badge scanned"}]
        events = _normalize_product_events("access", raw)
        assert len(events) == 1
        assert events[0].product == "access"
        assert events[0].event_type == "badge_scan"
        assert events[0].summary == "Badge scanned"

    def test_skips_unparseable_events(self):
        raw = [
            {"timestamp": "2026-03-24T10:00:00+00:00", "type": "ok", "msg": "ok"},
            {"no_timestamp_field_at_all": True},
        ]
        events = _normalize_product_events("network", raw)
        # The second event has no timestamp field, falls back to empty string
        # which will fail fromisoformat — should be skipped gracefully
        assert len(events) == 1

    def test_uses_event_type_fallback(self):
        raw = [{"timestamp": "2026-03-24T10:00:00+00:00", "event_type": "custom_type"}]
        events = _normalize_product_events("network", raw)
        assert events[0].event_type == "custom_type"

    def test_uses_description_fallback_for_summary(self):
        raw = [{"timestamp": "2026-03-24T10:00:00+00:00", "type": "x", "description": "A description"}]
        events = _normalize_product_events("network", raw)
        assert events[0].summary == "A description"


class TestHandleLocationTimeline:
    """Test the async handler function."""

    @pytest.mark.asyncio
    async def test_returns_error_on_invalid_input(self):
        forwarder = AsyncMock()
        result = await handle_location_timeline(
            arguments={"start_time": "", "end_time": "2026-03-24T23:59:59Z"},
            forwarder=forwarder,
        )
        assert result["success"] is False
        assert "start_time" in result["error"]
        forwarder.forward.assert_not_called()

    @pytest.mark.asyncio
    async def test_fans_out_to_all_products_by_default(self):
        forwarder = AsyncMock()
        forwarder.forward = AsyncMock(return_value={"success": True, "data": []})

        result = await handle_location_timeline(
            arguments={
                "start_time": "2026-03-24T00:00:00Z",
                "end_time": "2026-03-24T23:59:59Z",
            },
            forwarder=forwarder,
        )
        assert result["success"] is True
        # Should have called forward for network, protect, and access
        assert forwarder.forward.call_count == 3
        called_tools = [call.kwargs["tool_name"] for call in forwarder.forward.call_args_list]
        assert "unifi_list_events" in called_tools
        assert "unifi_protect_list_events" in called_tools
        assert "unifi_access_list_events" in called_tools

    @pytest.mark.asyncio
    async def test_limits_to_specified_products(self):
        forwarder = AsyncMock()
        forwarder.forward = AsyncMock(return_value={"success": True, "data": []})

        result = await handle_location_timeline(
            arguments={
                "start_time": "2026-03-24T00:00:00Z",
                "end_time": "2026-03-24T23:59:59Z",
                "products": ["network"],
            },
            forwarder=forwarder,
        )
        assert result["success"] is True
        assert forwarder.forward.call_count == 1
        assert forwarder.forward.call_args.kwargs["tool_name"] == "unifi_list_events"

    @pytest.mark.asyncio
    async def test_merges_events_from_multiple_products(self):
        async def mock_forward(tool_name, arguments):
            if tool_name == "unifi_list_events":
                return {
                    "success": True,
                    "data": [
                        {"timestamp": "2026-03-24T10:00:00+00:00", "type": "client_connect", "msg": "Client connected"},
                    ],
                }
            elif tool_name == "unifi_protect_list_events":
                return {
                    "success": True,
                    "data": [
                        {"timestamp": "2026-03-24T09:00:00+00:00", "type": "motion", "msg": "Motion detected"},
                    ],
                }
            return {"success": True, "data": []}

        forwarder = AsyncMock()
        forwarder.forward = AsyncMock(side_effect=mock_forward)

        result = await handle_location_timeline(
            arguments={
                "start_time": "2026-03-24T00:00:00Z",
                "end_time": "2026-03-24T23:59:59Z",
            },
            forwarder=forwarder,
            location_id="loc_1",
            location_name="Home",
        )
        assert result["success"] is True
        timeline = result["data"]["timeline"]
        assert len(timeline) == 2
        # Should be sorted by timestamp (protect event first at 09:00)
        assert timeline[0]["product"] == "protect"
        assert timeline[1]["product"] == "network"

    @pytest.mark.asyncio
    async def test_filters_by_event_types(self):
        forwarder = AsyncMock()
        forwarder.forward = AsyncMock(
            return_value={
                "success": True,
                "data": [
                    {"timestamp": "2026-03-24T10:00:00+00:00", "type": "client_connect", "msg": "Connected"},
                    {"timestamp": "2026-03-24T11:00:00+00:00", "type": "client_disconnect", "msg": "Disconnected"},
                ],
            }
        )

        result = await handle_location_timeline(
            arguments={
                "start_time": "2026-03-24T00:00:00Z",
                "end_time": "2026-03-24T23:59:59Z",
                "products": ["network"],
                "event_types": ["client_connect"],
            },
            forwarder=forwarder,
        )
        assert result["success"] is True
        timeline = result["data"]["timeline"]
        assert len(timeline) == 1
        assert timeline[0]["event_type"] == "client_connect"

    @pytest.mark.asyncio
    async def test_handles_forward_failure_gracefully(self):
        forwarder = AsyncMock()
        forwarder.forward = AsyncMock(side_effect=ConnectionError("refused"))

        result = await handle_location_timeline(
            arguments={
                "start_time": "2026-03-24T00:00:00Z",
                "end_time": "2026-03-24T23:59:59Z",
                "products": ["network"],
            },
            forwarder=forwarder,
        )
        # Should succeed with empty timeline, not crash
        assert result["success"] is True
        assert result["data"]["timeline"] == []

    @pytest.mark.asyncio
    async def test_handles_forward_returning_none(self):
        """When a product tool is unknown to the forwarder (returns None), skip it."""
        forwarder = AsyncMock()
        forwarder.forward = AsyncMock(return_value=None)

        result = await handle_location_timeline(
            arguments={
                "start_time": "2026-03-24T00:00:00Z",
                "end_time": "2026-03-24T23:59:59Z",
                "products": ["network"],
            },
            forwarder=forwarder,
        )
        assert result["success"] is True
        assert result["data"]["timeline"] == []
