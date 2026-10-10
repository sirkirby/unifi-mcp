"""Network normalizers against real-shaped payloads and the current tool manifest."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from unifi_core.incident_evidence import (
    ApiFamily,
    EntityKind,
    FailureKind,
    PartialReason,
    Product,
    SourceOutcome,
    TimeStatus,
    TimeWindow,
    Truncation,
    WindowCoverage,
)
from unifi_core.network.incident_evidence import (
    LEGACY_EVENTS_CAP,
    LIST_ALARMS_TOOL,
    LIST_EVENTS_TOOL,
    TOOL_RECORD_PATHS,
    V2_ALARMS_PAGE_CAP,
    network_alarms_context,
    network_events_context,
    normalize_network_page,
    normalize_network_records,
    normalize_network_tool_response,
)
from unifi_core.network.models.events import threat_event_log_from_controller
from unifi_core.network.models.system import alarm_from_controller
from unifi_core.source_page import SourcePage

REPO = Path(__file__).resolve().parents[4]
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "system_log_events_response.json").read_text())["data"]
MANIFEST = json.loads((REPO / "apps/network/src/unifi_network_mcp/tools_manifest.json").read_text())
UTC = timezone.utc
# The fixture's events fall between 2026-08-08T21:38:16Z and 21:38:21Z.
WINDOW = TimeWindow.from_datetimes(datetime(2026, 8, 8, 21, 0, tzinfo=UTC), datetime(2026, 8, 8, 22, 0, tzinfo=UTC))
COLLECTED = datetime(2026, 8, 8, 22, 5, tzinfo=UTC)
REQUEST_STARTED = COLLECTED - timedelta(minutes=1)


def _manifest_properties(tool: str) -> set[str]:
    entry = next(t for t in MANIFEST["tools"] if t["name"] == tool)
    return set(entry["schema"]["input"]["properties"])


def _events_context(**kwargs):
    kwargs.setdefault("within_hours", 2)
    return network_events_context(
        requested_window=WINDOW, request_started_at=REQUEST_STARTED, collected_at=COLLECTED, **kwargs
    )


def test_query_arguments_match_the_current_manifest() -> None:
    assert set(_events_context().query) == _manifest_properties(LIST_EVENTS_TOOL)
    alarms = network_alarms_context(requested_window=WINDOW, collected_at=COLLECTED)
    assert set(alarms.query) == _manifest_properties(LIST_ALARMS_TOOL)
    # The tools take no start_time/end_time; ``start`` is a pagination offset.
    assert not {"start_time", "end_time"} & _manifest_properties(LIST_EVENTS_TOOL)


def test_v2_system_log_records_normalize_with_role_scoped_entities() -> None:
    # The page from the manager is what proves the read reached the end.
    page = SourcePage(rows=FIXTURE, has_more=False, offset=0, cap=100, api_path="v2")
    evidence = normalize_network_page(page, _events_context(page=page))
    assert evidence.source.outcome is SourceOutcome.COMPLETE
    assert [r.provenance.source_record_id for r in evidence.records] == ["evt-0001", "evt-0002", "evt-0003", "evt-0004"]
    first = evidence.records[0]
    assert first.provenance.api_family is ApiFamily.NETWORK_V2_CONTROLLER
    assert first.time.original_field == "timestamp"
    assert first.time.original_value == 1786225096952
    assert first.time.utc == "2026-08-08T21:38:16.952000Z"
    assert first.event_type == "TRAFFIC_BLOCKED_KNOWN_SOURCE_CLIENT"
    assert first.summary.startswith("Lab-Camera was blocked")
    assert [(e.kind, e.role, e.id) for e in first.entities] == [
        (EntityKind.NETWORK_CLIENT, "SRC_CLIENT", "aa:bb:cc:00:00:01")
    ]
    threat = evidence.records[1]
    assert [(e.kind, e.role) for e in threat.entities] == [
        (EntityKind.NETWORK_CLIENT, "SRC_CLIENT"),
        (EntityKind.NETWORK_DEVICE, "DEVICE"),
    ]
    assert threat.attributes["severity"] == "HIGH"
    # Address roles (DST_IP) are never treated as station identities.
    assert evidence.records[3].entities == ()


def test_tool_projection_yields_the_same_events_as_manager_records() -> None:
    projected = [threat_event_log_from_controller(e).model_dump(exclude_none=True) for e in FIXTURE]
    response = {"success": True, "site": "default", "count": len(projected), "filters": {}, "events": projected}
    from_tool = normalize_network_tool_response(response, _events_context())
    from_manager = normalize_network_records(FIXTURE, _events_context())
    assert [r.evidence_id for r in from_tool.records] == [r.evidence_id for r in from_manager.records]
    assert [r.time.utc for r in from_tool.records] == [r.time.utc for r in from_manager.records]
    assert from_tool.records[0].time.original_field == "time"
    # The projection keeps a single MAC without its role.
    assert [e.kind for e in from_tool.records[0].entities] == [EntityKind.NETWORK_STATION]


def test_list_events_records_live_under_top_level_events_not_data() -> None:
    assert TOOL_RECORD_PATHS[LIST_EVENTS_TOOL] == ("events",)
    misread = {"success": True, "data": [{"id": "x"}]}
    assert normalize_network_tool_response(misread, _events_context()).source.outcome is SourceOutcome.PARSE_FAILED


def test_legacy_stat_event_records_use_flat_mac_keys() -> None:
    legacy = {
        "_id": "legacy-1",
        "key": "EVT_WU_Disconnected",
        "msg": "Client disconnected",
        "time": int(datetime(2026, 8, 8, 21, 30, tzinfo=UTC).timestamp() * 1000),
        "datetime": "2026-08-08T21:30:00Z",
        "user": "aa:bb:cc:00:00:09",
        "ap": "aa:bb:cc:00:00:0a",
    }
    record = normalize_network_records([legacy], _events_context()).records[0]
    assert record.provenance.source_record_id_field == "_id"
    assert record.time.original_field == "time"
    assert [(e.kind, e.role) for e in record.entities] == [
        (EntityKind.NETWORK_CLIENT, "user"),
        (EntityKind.NETWORK_DEVICE, "ap"),
    ]


def test_queried_window_comes_from_the_captured_request_bounds() -> None:
    # The manager reads its clock between request start and completion, so only
    # [completion - lookback, request start] is certainly covered.
    covering = _events_context()
    assert covering.queried_window == TimeWindow.from_datetimes(COLLECTED - timedelta(hours=2), REQUEST_STARTED)
    short = _events_context(within_hours=1)
    source = normalize_network_records([], short).source
    assert source.coverage.window_coverage is WindowCoverage.NOT_COVERED
    assert source.outcome is SourceOutcome.PARTIAL


def test_request_that_started_before_the_requested_end_does_not_cover_it() -> None:
    window = TimeWindow.from_datetimes(COLLECTED - timedelta(hours=1), COLLECTED)
    context = network_events_context(
        requested_window=window,
        request_started_at=COLLECTED - timedelta(minutes=1),
        collected_at=COLLECTED,
        within_hours=2,
    )
    source = normalize_network_records([], context).source
    assert source.coverage.queried_window.end == "2026-08-08T22:04:00.000000Z"
    assert PartialReason.WINDOW_NOT_COVERED in source.partial_reasons


def test_request_start_after_completion_is_rejected() -> None:
    with pytest.raises(ValueError):
        network_events_context(requested_window=WINDOW, request_started_at=COLLECTED, collected_at=REQUEST_STARTED)


def test_offset_page_is_never_complete() -> None:
    context = _events_context(limit=100, start=100)
    source = normalize_network_records([], context).source
    assert PartialReason.PREFIX_NOT_COLLECTED in source.partial_reasons
    assert source.coverage.population_total is None
    # Even with proof that the read reached the end, the skipped prefix stays uncollected.
    page = SourcePage(rows=[], has_more=False, offset=100, cap=100, api_path="v2")
    proven = normalize_network_page(page, _events_context(limit=100, start=100, page=page)).source
    assert proven.partial_reasons == (PartialReason.PREFIX_NOT_COLLECTED,)


def test_offset_and_limit_drive_pagination_and_filters() -> None:
    context = _events_context(limit=2, start=4, event_type="CLIENT_CONNECTED_WIRELESS_2", categories=["SECURITY"])
    assert context.offset == 4 and context.cap == 2
    assert context.filters == {"categories": ("SECURITY",), "event_type": "CLIENT_CONNECTED_WIRELESS_2"}
    source = normalize_network_records(FIXTURE[:2], context).source
    assert PartialReason.TRUNCATION_UNKNOWN in source.partial_reasons
    assert PartialReason.PREFIX_NOT_COLLECTED in source.partial_reasons


@pytest.mark.parametrize(
    ("api_path", "cap", "endpoint"),
    [("legacy", LEGACY_EVENTS_CAP, "/stat/event"), (None, LEGACY_EVENTS_CAP, None), ("v2", 5000, "/system-log/all")],
)
def test_events_cap_is_the_effective_cap(api_path, cap, endpoint) -> None:
    context = _events_context(limit=5000, api_path=api_path)
    assert context.requested_cap == 5000 and context.cap == cap and context.endpoint == endpoint


def test_legacy_clamped_full_page_is_not_complete() -> None:
    rows = [{"_id": f"legacy-{i}", "key": "K", "time": 1786227600000 + i} for i in range(LEGACY_EVENTS_CAP)]
    source = normalize_network_records(rows, _events_context(limit=5000, api_path="legacy")).source
    assert source.coverage.truncation is Truncation.UNKNOWN
    assert source.outcome is SourceOutcome.PARTIAL


@pytest.mark.parametrize(("api_path", "cap"), [("v2", V2_ALARMS_PAGE_CAP), (None, V2_ALARMS_PAGE_CAP), ("legacy", 200)])
def test_alarm_cap_is_the_effective_cap(api_path, cap) -> None:
    context = network_alarms_context(requested_window=WINDOW, collected_at=COLLECTED, limit=200, api_path=api_path)
    assert context.cap == cap


def test_v2_alarm_window_uses_the_captured_bounds() -> None:
    context = network_alarms_context(
        requested_window=WINDOW, collected_at=COLLECTED, api_path="v2", request_started_at=REQUEST_STARTED
    )
    assert context.queried_window == TimeWindow.from_datetimes(COLLECTED - timedelta(days=30), REQUEST_STARTED)
    rows = [{"id": f"alarm-{i}", "key": "K", "timestamp": 1786227600000} for i in range(V2_ALARMS_PAGE_CAP)]
    assert normalize_network_records(rows, context).source.coverage.truncation is Truncation.UNKNOWN


def test_alarms_without_a_known_lookback_are_never_complete() -> None:
    alarms = [alarm_from_controller(a).model_dump() for a in FIXTURE[:1]]
    context = network_alarms_context(requested_window=WINDOW, collected_at=COLLECTED)
    evidence = normalize_network_tool_response({"success": True, "alarms": alarms}, context)
    assert evidence.source.outcome is SourceOutcome.PARTIAL
    assert PartialReason.WINDOW_COVERAGE_UNKNOWN in evidence.source.partial_reasons
    assert evidence.records[0].attributes["archived"] is False


def test_error_envelope_is_unavailable() -> None:
    evidence = normalize_network_tool_response(
        {"success": False, "error": "Failed to list events: x"}, _events_context()
    )
    assert evidence.source.outcome is SourceOutcome.UNAVAILABLE
    assert evidence.source.failure.kind is FailureKind.UNAVAILABLE
    assert evidence.source.product is Product.NETWORK


def test_records_without_any_event_fields_are_malformed() -> None:
    source = normalize_network_records([{}, {"unrelated": 1}], _events_context()).source
    assert source.coverage.counts.malformed_dropped == 2


def test_malformed_time_is_kept_as_an_explicit_state() -> None:
    evidence = normalize_network_records([{"id": "x", "key": "K", "time": "soon"}], _events_context())
    assert evidence.records[0].time.status is TimeStatus.MALFORMED
    assert evidence.records[0].time.original_value == "soon"


def test_integer_record_ids_are_kept_as_integers() -> None:
    evidence = normalize_network_records(
        [{"id": 7, "key": "K", "time": 1786227600000}, {"id": "7", "key": "K", "time": 1786227601000}],
        _events_context(),
    )
    assert evidence.source.coverage.counts.malformed_dropped == 0
    assert [r.provenance.source_record_id for r in evidence.records] == [7, "7"]
    assert [r.evidence_id for r in evidence.records] == ["network.events|int|7", "network.events|str|7"]


def test_tool_responses_alone_never_prove_completeness() -> None:
    # The tool envelope carries no continuation state, so a short list is not an all-clear.
    projected = [threat_event_log_from_controller(e).model_dump(exclude_none=True) for e in FIXTURE]
    source = normalize_network_tool_response({"success": True, "events": projected}, _events_context()).source
    assert source.coverage.truncation is Truncation.UNKNOWN
    assert source.outcome is SourceOutcome.PARTIAL


def test_page_api_path_must_agree_with_the_declared_path() -> None:
    page = SourcePage(rows=[], has_more=False, cap=100, api_path="legacy")
    with pytest.raises(ValueError):
        _events_context(api_path="v2", page=page)
    assert _events_context(page=page).endpoint == "/stat/event"


@pytest.mark.parametrize("field", ["api_key", "_buffered_at", "recognized_person_name", "password"])
def test_excluded_fields_do_not_change_identity_or_create_conflicts(field) -> None:
    base = {"id": "fixture-event", "key": "K", "time": 1786227600000}
    evidence = normalize_network_records([dict(base, **{field: "a"}), dict(base, **{field: "b"})], _events_context())
    assert len(evidence.records) == 1 and evidence.source.coverage.counts.conflicting == 0
    no_id = {"key": "K", "time": 1786227600000}
    first = normalize_network_records([dict(no_id, **{field: "a"})], _events_context()).records[0]
    second = normalize_network_records([dict(no_id, **{field: "b"})], _events_context()).records[0]
    assert first.evidence_id == second.evidence_id
