"""Tests for EventManager raw-API metadata passthrough + server-side camera filter.

Covers PR-5:
- `metadata_fields=[...]` opts in to per-event metadata fields. Empty list = no
  metadata (default, backwards-compatible).
- `metadata_fields=["*"]` includes every metadata key UniFi returns.
- `camera_id=<uuid>` triggers server-side filtering via the UniFi `cameras[]=`
  query parameter, rather than the previous client-side filter that fetched
  all-camera events and discarded the wrong ones.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from unifi_core.protect.managers.event_manager import EventManager


def _make_manager() -> EventManager:
    return EventManager(MagicMock())


def _raw_lpr_event(event_id: str = "evt_test") -> dict:
    """Minimal raw UniFi smartDetectLine event dict with the metadata uiprotect drops."""
    return {
        "id": event_id,
        "type": "smartDetectLine",
        "start": 1779200000000,  # epoch ms
        "end": 1779200005000,
        "score": 91,
        "smartDetectTypes": ["licensePlate", "vehicle"],
        "camera": "cam-uuid-xyz",
        "thumbnail": "thumb-xyz",
        "metadata": {
            "linesStatus": {
                "1": {
                    "vehicle": {"crosslineA2BAdd": 1, "crosslineB2AAdd": 0},
                    "direction": None,
                },
            },
            "linesSettings": [{"id": "1", "name": "Arrival", "direction": "AB"}],
            "weather": {"temperature": 16, "temperatureUnit": "C"},
            "detectedThumbnails": [
                {
                    "type": "vehicle",
                    "name": "TEST123",
                    "attributes": {
                        "color": {"val": "white", "confidence": 73},
                        "vehicleType": {"val": "truck", "confidence": 97},
                    },
                }
            ],
        },
    }


# -- server-side camera filter ---------------------------------------------


@pytest.mark.asyncio
async def test_camera_id_triggers_server_side_cameras_filter() -> None:
    """When camera_id is set, list_events must hit api_request_list with cameras=[id]."""
    mgr = _make_manager()
    mgr._cm.client.api_request_list = AsyncMock(return_value=[])

    await mgr.list_events(camera_id="cam-uuid-xyz", limit=500, event_type="smartDetectLine")

    mgr._cm.client.api_request_list.assert_called_once()
    _, kwargs = mgr._cm.client.api_request_list.call_args
    params = kwargs.get("params", {})
    assert params.get("cameras") == ["cam-uuid-xyz"]
    assert params.get("limit") == 500
    assert params.get("types") == ["smartDetectLine"]


@pytest.mark.asyncio
async def test_no_camera_id_uses_existing_uiprotect_path() -> None:
    """Without camera_id (and without metadata_fields), preserves the existing get_events() behavior."""
    mgr = _make_manager()
    mgr._cm.client.get_events = AsyncMock(return_value=[])
    mgr._cm.client.api_request_list = AsyncMock(return_value=[])

    await mgr.list_events(limit=30, event_type="smartDetectLine")

    mgr._cm.client.get_events.assert_called_once()
    mgr._cm.client.api_request_list.assert_not_called()


@pytest.mark.asyncio
async def test_metadata_fields_alone_triggers_raw_path() -> None:
    """metadata_fields set without camera_id must still route to the raw API path,
    because uiprotect's get_events drops the fields we need."""
    mgr = _make_manager()
    mgr._cm.client.get_events = AsyncMock(return_value=[])
    mgr._cm.client.api_request_list = AsyncMock(return_value=[])

    await mgr.list_events(limit=10, metadata_fields=["linesStatus"])

    mgr._cm.client.api_request_list.assert_called_once()
    mgr._cm.client.get_events.assert_not_called()
    _, kwargs = mgr._cm.client.api_request_list.call_args
    params = kwargs.get("params", {})
    assert "cameras" not in params  # no camera filter when caller didn't ask for one


# -- metadata_fields opt-in ------------------------------------------------


@pytest.mark.asyncio
async def test_metadata_fields_empty_default_omits_metadata() -> None:
    """Default empty list = response has no 'metadata' key. Backwards-compatible."""
    mgr = _make_manager()
    mgr._cm.client.api_request_list = AsyncMock(return_value=[_raw_lpr_event()])

    results = await mgr.list_events(camera_id="cam-uuid-xyz", limit=10)

    assert len(results) == 1
    assert "metadata" not in results[0]


@pytest.mark.asyncio
async def test_metadata_fields_filters_to_requested_keys() -> None:
    """Only the keys named in metadata_fields appear under 'metadata'."""
    mgr = _make_manager()
    mgr._cm.client.api_request_list = AsyncMock(return_value=[_raw_lpr_event()])

    results = await mgr.list_events(
        camera_id="cam-uuid-xyz",
        limit=10,
        metadata_fields=["linesStatus", "weather"],
    )

    md = results[0]["metadata"]
    assert set(md.keys()) == {"linesStatus", "weather"}
    assert md["linesStatus"]["1"]["vehicle"]["crosslineA2BAdd"] == 1
    assert md["weather"]["temperature"] == 16


@pytest.mark.asyncio
async def test_metadata_fields_star_includes_everything() -> None:
    """`['*']` returns the full metadata dict as UniFi returned it."""
    mgr = _make_manager()
    mgr._cm.client.api_request_list = AsyncMock(return_value=[_raw_lpr_event()])

    results = await mgr.list_events(
        camera_id="cam-uuid-xyz",
        limit=10,
        metadata_fields=["*"],
    )

    md = results[0]["metadata"]
    expected_keys = {"linesStatus", "linesSettings", "weather", "detectedThumbnails"}
    assert expected_keys.issubset(set(md.keys()))


@pytest.mark.asyncio
async def test_metadata_fields_unknown_key_silently_omitted() -> None:
    """Asking for a key the event doesn't have just leaves it out; no error."""
    mgr = _make_manager()
    mgr._cm.client.api_request_list = AsyncMock(return_value=[_raw_lpr_event()])

    results = await mgr.list_events(
        camera_id="cam-uuid-xyz",
        limit=10,
        metadata_fields=["linesStatus", "doesNotExist"],
    )

    md = results[0]["metadata"]
    assert "linesStatus" in md
    assert "doesNotExist" not in md


@pytest.mark.asyncio
async def test_metadata_fields_all_absent_drops_metadata_key() -> None:
    """When every requested key is missing from the event's metadata, the
    'metadata' key is omitted entirely (consistent with the buffer path)."""
    mgr = _make_manager()
    mgr._cm.client.api_request_list = AsyncMock(return_value=[_raw_lpr_event()])

    results = await mgr.list_events(
        camera_id="cam-uuid-xyz",
        limit=10,
        metadata_fields=["nonexistent1", "nonexistent2"],
    )

    assert "metadata" not in results[0]


@pytest.mark.asyncio
async def test_metadata_fields_star_with_no_raw_metadata_drops_key() -> None:
    """When the event has no metadata at all, even '*' omits the metadata key."""
    mgr = _make_manager()
    event_without_metadata = {
        "id": "evt-empty",
        "type": "smartDetectLine",
        "start": 1779200000000,
        "end": 1779200005000,
        "score": 91,
        "smartDetectTypes": ["vehicle"],
        "camera": "cam-uuid-xyz",
    }
    mgr._cm.client.api_request_list = AsyncMock(return_value=[event_without_metadata])

    results = await mgr.list_events(
        camera_id="cam-uuid-xyz",
        limit=10,
        metadata_fields=["*"],
    )

    assert "metadata" not in results[0]
