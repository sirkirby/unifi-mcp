"""Protect normalizers against real-shaped payloads and the current tool manifest."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from unifi_core.incident_evidence import (
    ApiFamily,
    EntityKind,
    IdKind,
    PartialReason,
    SourceOutcome,
    TimestampFormat,
    TimeWindow,
)
from unifi_core.protect.incident_evidence import (
    LIST_EVENTS_TOOL,
    LIST_SMART_DETECTIONS_TOOL,
    TOOL_RECORD_PATHS,
    normalize_protect_records,
    normalize_protect_tool_response,
    protect_events_context,
)
from unifi_core.protect.models.events import from_controller, smart_detection_from_controller

REPO = Path(__file__).resolve().parents[4]
MANIFEST = json.loads((REPO / "apps/protect/src/unifi_protect_mcp/tools_manifest.json").read_text())
UTC = timezone.utc
START = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
WINDOW = TimeWindow.from_datetimes(START, START + timedelta(hours=1))
COLLECTED = START + timedelta(hours=1, minutes=5)
CAMERA = "cam-fixture-000a"

# EventManager._event_to_dict / _raw_event_to_dict output.
MANAGER_EVENT = {
    "id": "evt-protect-1",
    "type": "smartDetectZone",
    "camera_id": CAMERA,
    "camera_name": "fixture-camera",
    "start": "2026-08-08T12:10:07.500000+00:00",
    "end": "2026-08-08T12:10:19+00:00",
    "score": 91,
    "smart_detect_types": ["person"],
    "recognized_person_id": "group-fixture-1",
    "recognized_person_name": "fixture-person",
    "recognized_plate_text": "FIXTURE1",
    "thumbnail_id": "thumb-fixture-1",
}
# Raw NVR row from the private events endpoint.
RAW_NVR_EVENT = {
    "id": "evt-protect-2",
    "type": "motion",
    "camera": CAMERA,
    "start": int(datetime(2026, 8, 8, 12, 20, tzinfo=UTC).timestamp() * 1000),
    "end": int(datetime(2026, 8, 8, 12, 20, 9, tzinfo=UTC).timestamp() * 1000),
    "score": 40,
    "smartDetectTypes": [],
}


def _manifest_properties(tool: str) -> set[str]:
    entry = next(t for t in MANIFEST["tools"] if t["name"] == tool)
    return set(entry["schema"]["input"]["properties"])


def _context(**kwargs):
    kwargs.setdefault("start", "2026-08-08T12:00:00Z")
    kwargs.setdefault("end", "2026-08-08T13:00:00Z")
    return protect_events_context(requested_window=WINDOW, collected_at=COLLECTED, **kwargs)


@pytest.mark.parametrize("tool", [LIST_EVENTS_TOOL, LIST_SMART_DETECTIONS_TOOL])
def test_query_arguments_are_current_manifest_arguments(tool: str) -> None:
    query = set(_context(source_tool=tool).query)
    assert query <= _manifest_properties(tool)
    assert {"start", "end", "limit"} <= _manifest_properties(tool)
    assert not {"start_time", "end_time"} & _manifest_properties(tool)


def test_tool_names_exist_in_the_manifest() -> None:
    names = {t["name"] for t in MANIFEST["tools"]}
    assert {LIST_EVENTS_TOOL, LIST_SMART_DETECTIONS_TOOL} <= names
    assert "unifi_protect_list_events" not in names


def test_manager_records_normalize_without_identity_fields() -> None:
    record = normalize_protect_records([MANAGER_EVENT], _context()).records[0]
    assert record.provenance.api_family is ApiFamily.PROTECT_PRIVATE
    assert record.provenance.source_record_id == "evt-protect-1"
    assert record.time.original_value == "2026-08-08T12:10:07.500000+00:00"
    assert record.time.utc == "2026-08-08T12:10:07.500000Z"
    assert [(e.kind, e.id_kind, e.id) for e in record.entities] == [
        (EntityKind.CAMERA, IdKind.PROTECT_CAMERA_ID, CAMERA)
    ]
    assert record.summary == "smartDetectZone: person"
    serialized = record.model_dump_json()
    for forbidden in ("fixture-person", "FIXTURE1", "group-fixture-1", 'fixture-camera"'):
        assert forbidden not in serialized


def test_raw_nvr_rows_use_epoch_milliseconds() -> None:
    record = normalize_protect_records([RAW_NVR_EVENT], _context()).records[0]
    assert record.time.original_format is TimestampFormat.EPOCH_MILLISECONDS
    assert record.time.utc == "2026-08-08T12:20:00.000000Z"
    assert record.entities[0].id == CAMERA
    assert record.attributes["end"] == RAW_NVR_EVENT["end"]


@pytest.mark.parametrize(
    ("tool", "project", "key", "outcome"),
    [
        (LIST_EVENTS_TOOL, from_controller, "events", SourceOutcome.COMPLETE),
        # Confidence filtering runs after the controller's limit, so a short list proves nothing.
        (LIST_SMART_DETECTIONS_TOOL, smart_detection_from_controller, "detections", SourceOutcome.PARTIAL),
    ],
)
def test_tool_projection_envelopes_normalize(tool, project, key, outcome) -> None:
    projected = [project(MANAGER_EVENT).model_dump(exclude_none=True)]
    response = {"success": True, "data": {key: projected, "count": 1}}
    evidence = normalize_protect_tool_response(response, _context(source_tool=tool))
    assert TOOL_RECORD_PATHS[tool] == ("data", key)
    assert evidence.source.outcome is outcome
    record = evidence.records[0]
    assert record.entities[0].id == CAMERA
    assert record.time.utc == "2026-08-08T12:10:07.500000Z"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (None, None),
        ("2026-08-08T12:00:00Z", None),
        (None, "2026-08-08T13:00:00Z"),
        ("last tuesday", "2026-08-08T13:00:00Z"),
        ("2026-08-08T13:00:00Z", "2026-08-08T12:00:00Z"),
    ],
)
def test_omitted_or_unparseable_bounds_leave_the_queried_window_unknown(start, end) -> None:
    # The manager sends no bound for an omitted or unparseable argument, so no
    # 24-hour default is assumed.
    context = protect_events_context(requested_window=WINDOW, collected_at=COLLECTED, start=start, end=end)
    assert context.queried_window is None
    assert context.query["start"] == start
    source = normalize_protect_records([], context).source
    assert source.outcome is SourceOutcome.PARTIAL
    assert PartialReason.WINDOW_COVERAGE_UNKNOWN in source.partial_reasons


def test_naive_bounds_are_read_as_utc_like_the_tool() -> None:
    naive = _context(start="2026-08-08T12:00:00", end="2026-08-08T13:00:00")
    assert naive.queried_window == WINDOW


def test_metadata_fields_and_compact_are_part_of_the_recorded_query() -> None:
    context = _context(metadata_fields=["linesStatus"], compact=True)
    record = normalize_protect_records([RAW_NVR_EVENT], context).records[0]
    assert record.provenance.query["metadata_fields"] == ("linesStatus",)
    assert record.provenance.query["compact"] is True
    assert set(context.query) <= _manifest_properties(LIST_EVENTS_TOOL)


@pytest.mark.parametrize(("requested", "effective"), [(None, 50), (80, 80), (0, 0)])
def test_smart_detection_filters_record_the_effective_confidence(requested, effective) -> None:
    context = _context(source_tool=LIST_SMART_DETECTIONS_TOOL, min_confidence=requested)
    assert context.query["min_confidence"] == requested
    assert context.filters["min_confidence_effective"] == effective
    assert context.post_filtered is (effective > 0)


def test_server_configured_confidence_default_is_used() -> None:
    context = _context(source_tool=LIST_SMART_DETECTIONS_TOOL, server_min_confidence=70)
    assert context.filters["min_confidence_effective"] == 70


def test_confidence_filtered_short_list_is_partial() -> None:
    # 30 fetched, confidence filtering left one: a short list after a post-filter.
    source = normalize_protect_records([RAW_NVR_EVENT], _context(source_tool=LIST_SMART_DETECTIONS_TOOL)).source
    assert source.outcome is SourceOutcome.PARTIAL
    assert set(source.partial_reasons) == {PartialReason.POST_FILTERED, PartialReason.TRUNCATION_UNKNOWN}


def test_manager_exposes_its_confidence_default() -> None:
    from unifi_core.protect.managers.event_manager import EventManager

    assert EventManager(None).smart_detection_min_confidence == 50
    assert EventManager(None, {"smart_detection_min_confidence": 65}).smart_detection_min_confidence == 65


def test_limit_reached_is_not_a_complete_listing() -> None:
    source = normalize_protect_records([MANAGER_EVENT, RAW_NVR_EVENT], _context(limit=2)).source
    assert source.outcome is SourceOutcome.PARTIAL
    assert source.partial_reasons == (PartialReason.TRUNCATION_UNKNOWN,)
    assert source.coverage.population_total is None


def test_window_after_requested_start_is_partial() -> None:
    source = normalize_protect_records([], _context(start="2026-08-08T12:30:00Z")).source
    assert source.partial_reasons == (PartialReason.WINDOW_NOT_COVERED,)


def test_camera_reference_objects_resolve_to_their_id() -> None:
    record = normalize_protect_records([{**RAW_NVR_EVENT, "camera": {"id": CAMERA}}], _context()).records[0]
    assert record.entities[0].id == CAMERA


def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(ValueError):
        protect_events_context(requested_window=WINDOW, collected_at=COLLECTED, source_tool="unifi_protect_list_events")
