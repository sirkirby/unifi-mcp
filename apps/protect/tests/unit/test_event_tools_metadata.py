"""Tool-level tests for metadata_fields parameter on event-listing MCP tools.

Verifies that each tool correctly threads metadata_fields through to the
manager (or, for the buffer-backed tool, applies filtering in the tool layer).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# protect_list_events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protect_list_events_passes_metadata_fields_to_manager() -> None:
    from unifi_protect_mcp.tools.events import protect_list_events

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.list_events = AsyncMock(return_value=[])
        await protect_list_events(metadata_fields=["linesStatus"])
        mgr.list_events.assert_called_once()
        _, kwargs = mgr.list_events.call_args
        assert kwargs.get("metadata_fields") == ["linesStatus"]


@pytest.mark.asyncio
async def test_protect_list_events_empty_list_passes_none_to_manager() -> None:
    from unifi_protect_mcp.tools.events import protect_list_events

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.list_events = AsyncMock(return_value=[])
        await protect_list_events()  # default = []
        _, kwargs = mgr.list_events.call_args
        assert kwargs.get("metadata_fields") is None


# ---------------------------------------------------------------------------
# protect_get_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protect_get_event_passes_metadata_fields_to_manager() -> None:
    from unifi_protect_mcp.tools.events import protect_get_event

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.get_event = AsyncMock(return_value={"id": "evt-1", "type": "motion"})
        await protect_get_event(event_id="evt-1", metadata_fields=["linesStatus"])
        mgr.get_event.assert_called_once()
        args, kwargs = mgr.get_event.call_args
        assert kwargs.get("metadata_fields") == ["linesStatus"]


@pytest.mark.asyncio
async def test_protect_get_event_empty_list_passes_none_to_manager() -> None:
    from unifi_protect_mcp.tools.events import protect_get_event

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.get_event = AsyncMock(return_value={"id": "evt-1", "type": "motion"})
        await protect_get_event(event_id="evt-1")  # default = []
        _, kwargs = mgr.get_event.call_args
        assert kwargs.get("metadata_fields") is None


# ---------------------------------------------------------------------------
# protect_list_smart_detections
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protect_list_smart_detections_passes_metadata_fields_to_manager() -> None:
    from unifi_protect_mcp.tools.events import protect_list_smart_detections

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.list_smart_detections = AsyncMock(return_value=[])
        await protect_list_smart_detections(metadata_fields=["linesStatus"])
        mgr.list_smart_detections.assert_called_once()
        _, kwargs = mgr.list_smart_detections.call_args
        assert kwargs.get("metadata_fields") == ["linesStatus"]


@pytest.mark.asyncio
async def test_protect_list_smart_detections_empty_list_passes_none_to_manager() -> None:
    from unifi_protect_mcp.tools.events import protect_list_smart_detections

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.list_smart_detections = AsyncMock(return_value=[])
        await protect_list_smart_detections()  # default = []
        _, kwargs = mgr.list_smart_detections.call_args
        assert kwargs.get("metadata_fields") is None


# ---------------------------------------------------------------------------
# protect_recent_events — metadata filtering in the tool layer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_protect_recent_events_no_metadata_fields_strips_metadata() -> None:
    """Default (empty list) strips metadata from buffer events."""
    from unifi_protect_mcp.tools.events import protect_recent_events

    raw_event = {
        "id": "evt-buf-001",
        "type": "motion",
        "camera_id": "cam-001",
        "camera": "cam-001",
        "start": 1779200000000,
        "end": 1779200005000,
        "score": 80,
        "smartDetectTypes": [],
        "metadata": {"linesStatus": {"1": {"vehicle": {}}}, "weather": {"temperature": 16}},
        "_buffered_at": 9999999999.0,
    }

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.get_recent_from_buffer = MagicMock(return_value=[raw_event])
        mgr.buffer_size = 1
        result = await protect_recent_events()

    assert result["success"] is True
    # metadata should not appear in any event
    for ev in result["data"]["events"]:
        assert "metadata" not in ev


@pytest.mark.asyncio
async def test_protect_recent_events_named_metadata_fields_filtered() -> None:
    """Named metadata_fields returns only those keys."""
    from unifi_protect_mcp.tools.events import protect_recent_events

    raw_event = {
        "id": "evt-buf-002",
        "type": "smartDetectZone",
        "camera_id": "cam-001",
        "camera": "cam-001",
        "start": 1779200000000,
        "end": 1779200005000,
        "score": 85,
        "smartDetectTypes": ["vehicle"],
        "metadata": {"linesStatus": {"1": {}}, "weather": {"temperature": 20}},
        "_buffered_at": 9999999999.0,
    }

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.get_recent_from_buffer = MagicMock(return_value=[raw_event])
        mgr.buffer_size = 1
        result = await protect_recent_events(metadata_fields=["weather"])

    assert result["success"] is True
    events = result["data"]["events"]
    assert len(events) == 1
    md = events[0].get("metadata", {})
    assert "weather" in md
    assert "linesStatus" not in md


@pytest.mark.asyncio
async def test_protect_recent_events_star_returns_full_metadata() -> None:
    """['*'] returns the full metadata dict."""
    from unifi_protect_mcp.tools.events import protect_recent_events

    raw_event = {
        "id": "evt-buf-003",
        "type": "smartDetectZone",
        "camera_id": "cam-001",
        "camera": "cam-001",
        "start": 1779200000000,
        "end": 1779200005000,
        "score": 85,
        "smartDetectTypes": ["vehicle"],
        "metadata": {"linesStatus": {"1": {}}, "weather": {"temperature": 20}},
        "_buffered_at": 9999999999.0,
    }

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.get_recent_from_buffer = MagicMock(return_value=[raw_event])
        mgr.buffer_size = 1
        result = await protect_recent_events(metadata_fields=["*"])

    assert result["success"] is True
    events = result["data"]["events"]
    assert len(events) == 1
    md = events[0].get("metadata", {})
    assert "linesStatus" in md
    assert "weather" in md


@pytest.mark.asyncio
async def test_protect_recent_events_does_not_mutate_buffer_event() -> None:
    """The tool must not mutate the dict stored in the buffer."""
    from unifi_protect_mcp.tools.events import protect_recent_events

    original_metadata = {"linesStatus": {"1": {}}, "weather": {"temperature": 20}}
    raw_event = {
        "id": "evt-buf-004",
        "type": "motion",
        "camera_id": "cam-001",
        "camera": "cam-001",
        "start": 1779200000000,
        "end": None,
        "score": 70,
        "smartDetectTypes": [],
        "metadata": original_metadata,
        "_buffered_at": 9999999999.0,
    }

    with patch("unifi_protect_mcp.tools.events.event_manager") as mgr:
        mgr.get_recent_from_buffer = MagicMock(return_value=[raw_event])
        mgr.buffer_size = 1
        # Call with no metadata_fields — should strip metadata from outgoing event
        await protect_recent_events()

    # The buffer's event dict must still have its metadata intact
    assert raw_event.get("metadata") is original_metadata
