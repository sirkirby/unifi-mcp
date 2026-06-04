"""Tests for the detection-search MCP tools.

Covers protect_search_detections and protect_detection_search_labels, which
wrap EventManager.search_detections / get_detection_search_labels and apply the
standard {"success": ..., "data"/"error": ...} envelope.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeDetection:
    """Stand-in for a SmartDetection model with a model_dump method."""

    def __init__(self, payload: dict):
        self._payload = payload

    def model_dump(self, *, exclude_none: bool = False) -> dict:
        if exclude_none:
            return {k: v for k, v in self._payload.items() if v is not None}
        return dict(self._payload)


@pytest.fixture
def mock_event_manager():
    """Patch the event_manager singleton imported into the tools module."""
    mgr = MagicMock()
    with patch("unifi_protect_mcp.tools.events.event_manager", mgr):
        yield mgr


# ---------------------------------------------------------------------------
# protect_search_detections
# ---------------------------------------------------------------------------


class TestProtectSearchDetections:
    @pytest.mark.asyncio
    async def test_success_serializes_detections_and_count(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(
            return_value={
                "detections": [
                    _FakeDetection({"id": "d1", "type": "smartDetectZone", "score": None}),
                    _FakeDetection({"id": "d2", "type": "smartDetectZone", "score": 90}),
                ],
                "count": 2,
            }
        )

        result = await protect_search_detections(labels=["vehicleType:truck"])

        assert result["success"] is True
        assert result["data"]["count"] == 2
        assert len(result["data"]["detections"]) == 2
        # model_dump(exclude_none=True) drops the None score on d1
        assert result["data"]["detections"][0] == {"id": "d1", "type": "smartDetectZone"}
        assert result["data"]["detections"][1] == {"id": "d2", "type": "smartDetectZone", "score": 90}

    @pytest.mark.asyncio
    async def test_passes_params_through_to_manager(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(return_value={"detections": [], "count": 0})

        await protect_search_detections(
            labels=["color:black", "vehicleType:truck"],
            limit=50,
            order="asc",
            exclude_motion=False,
        )

        call_kwargs = mock_event_manager.search_detections.call_args.kwargs
        assert call_kwargs["labels"] == ["color:black", "vehicleType:truck"]
        assert call_kwargs["limit"] == 50
        assert call_kwargs["order"] == "asc"
        assert call_kwargs["exclude_motion"] is False

    @pytest.mark.asyncio
    async def test_passes_optional_filters_through(self, mock_event_manager):
        from datetime import datetime

        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(return_value={"detections": [], "count": 0})

        await protect_search_detections(
            labels=["color:black"],
            min_confidence=70,
            start="2026-05-28T07:00:00+00:00",
            end="2026-06-04T13:51:59.999+00:00",
        )

        call_kwargs = mock_event_manager.search_detections.call_args.kwargs
        assert call_kwargs["min_confidence"] == 70
        # The tool parses ISO strings into datetimes before handing off to the manager.
        assert isinstance(call_kwargs["start"], datetime)
        assert isinstance(call_kwargs["end"], datetime)
        assert call_kwargs["start"].isoformat().startswith("2026-05-28T07:00:00")

    @pytest.mark.asyncio
    async def test_optional_filters_default_to_none(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(return_value={"detections": [], "count": 0})

        await protect_search_detections(labels=["color:black"])

        call_kwargs = mock_event_manager.search_detections.call_args.kwargs
        assert call_kwargs["min_confidence"] is None
        assert call_kwargs["start"] is None
        assert call_kwargs["end"] is None

    @pytest.mark.asyncio
    async def test_unparseable_start_end_coerce_to_none(self, mock_event_manager):
        # Mirrors protect_list_events/list_smart_detections: an unparseable ISO
        # timestamp is coerced to None (no bound) rather than raising.
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(return_value={"detections": [], "count": 0})

        result = await protect_search_detections(labels=["color:black"], start="not-a-date", end="garbage")

        assert result["success"] is True
        call_kwargs = mock_event_manager.search_detections.call_args.kwargs
        assert call_kwargs["start"] is None
        assert call_kwargs["end"] is None

    @pytest.mark.asyncio
    async def test_defaults_passed_through(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(return_value={"detections": [], "count": 0})

        await protect_search_detections(labels=["color:black"])

        call_kwargs = mock_event_manager.search_detections.call_args.kwargs
        assert call_kwargs["labels"] == ["color:black"]
        assert call_kwargs["limit"] == 100
        assert call_kwargs["order"] == "desc"
        assert call_kwargs["exclude_motion"] is True

    @pytest.mark.asyncio
    async def test_empty_results(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(return_value={"detections": [], "count": 0})

        result = await protect_search_detections(labels=["color:black"])

        assert result["success"] is True
        assert result["data"]["count"] == 0
        assert result["data"]["detections"] == []

    @pytest.mark.asyncio
    async def test_value_error_returns_clean_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(side_effect=ValueError("unknown label prefix 'bogus'"))

        result = await protect_search_detections(labels=["bogus:value"])

        assert result["success"] is False
        assert result["error"] == "unknown label prefix 'bogus'"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_search_detections

        mock_event_manager.search_detections = AsyncMock(side_effect=RuntimeError("connection lost"))

        result = await protect_search_detections(labels=["color:black"])

        assert result["success"] is False
        assert "connection lost" in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_annotation(self):
        # Importing the tools module runs its @server.tool registrations on THIS
        # worker. Without it the test only imports runtime.server and depends on
        # another test having imported tools.events first, which pytest-xdist
        # load-distribution (-n auto) does not guarantee.
        import unifi_protect_mcp.tools.events  # noqa: F401
        from unifi_protect_mcp.runtime import server

        tools = {tool.name: tool for tool in await server.list_tools()}
        assert tools["protect_search_detections"].annotations.readOnlyHint is True
        assert tools["protect_search_detections"].annotations.openWorldHint is False


# ---------------------------------------------------------------------------
# protect_detection_search_labels
# ---------------------------------------------------------------------------


class TestProtectDetectionSearchLabels:
    @pytest.mark.asyncio
    async def test_success_returns_vocabulary(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_detection_search_labels

        labels = {
            "colors": [{"label": "Black", "value": "color:black"}],
            "vehicle_types": [{"label": "Truck", "value": "vehicleType:truck"}],
        }
        mock_event_manager.get_detection_search_labels = AsyncMock(return_value=labels)

        result = await protect_detection_search_labels()

        assert result["success"] is True
        assert result["data"] == labels

    @pytest.mark.asyncio
    async def test_value_error_returns_clean_error(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_detection_search_labels

        mock_event_manager.get_detection_search_labels = AsyncMock(side_effect=ValueError("bad"))

        result = await protect_detection_search_labels()

        assert result["success"] is False
        assert result["error"] == "bad"

    @pytest.mark.asyncio
    async def test_unexpected_error_returns_failure(self, mock_event_manager):
        from unifi_protect_mcp.tools.events import protect_detection_search_labels

        mock_event_manager.get_detection_search_labels = AsyncMock(side_effect=RuntimeError("connection lost"))

        result = await protect_detection_search_labels()

        assert result["success"] is False
        assert "connection lost" in result["error"]

    @pytest.mark.asyncio
    async def test_read_only_annotation(self):
        # Importing the tools module runs its @server.tool registrations on THIS
        # worker. Without it the test only imports runtime.server and depends on
        # another test having imported tools.events first, which pytest-xdist
        # load-distribution (-n auto) does not guarantee.
        import unifi_protect_mcp.tools.events  # noqa: F401
        from unifi_protect_mcp.runtime import server

        tools = {tool.name: tool for tool in await server.list_tools()}
        assert tools["protect_detection_search_labels"].annotations.readOnlyHint is True
        assert tools["protect_detection_search_labels"].annotations.openWorldHint is False
