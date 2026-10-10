"""Contract tests for the versioned incident evidence model."""

from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiAuthError, UniFiPermissionError
from unifi_core.incident_evidence import (
    ABSENT,
    INCIDENT_EVIDENCE_SCHEMA_VERSION,
    ApiFamily,
    BudgetKind,
    BudgetLimits,
    Budgets,
    BudgetUsage,
    Coverage,
    EntityKind,
    EntityRef,
    ExtractedRecord,
    FailureKind,
    IdKind,
    IncidentEvidence,
    MappingAssertion,
    MappingOutcome,
    MappingSource,
    MappingStatus,
    OverallStatus,
    Pagination,
    PartialReason,
    Product,
    Provenance,
    Scope,
    SourceContext,
    SourceFailure,
    SourceOutcome,
    TimePrecision,
    TimestampFormat,
    TimeStatus,
    TimeWindow,
    Truncation,
    assemble_incident_evidence,
    canonical_json,
    collect_source,
    evidence_to_json,
    failure_from_exception,
    parse_event_time,
    records_from_tool_response,
    resolve_mapping,
    source_failed,
    truncation_state,
)

UTC = timezone.utc
START = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
END = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
WINDOW = TimeWindow.from_datetimes(START, END)
COLLECTED = datetime(2026, 8, 8, 13, 5, tzinfo=UTC)
BUDGETS = Budgets(limits=BudgetLimits(window_seconds=7200, events=100, calls=10, elapsed_ms=60_000))
AP = "aa:bb:cc:00:10:01"
CAMERA = "cam-fixture-000a"


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _context(**overrides: Any) -> SourceContext:
    values: dict[str, Any] = {
        "source_id": "network.events",
        "product": Product.NETWORK,
        "api_family": ApiFamily.NETWORK_V2_CONTROLLER,
        "source_tool": "unifi_list_events",
        "scope": Scope(site="default", location_id="loc-fixture-1"),
        "query": {"within_hours": 2, "limit": 10},
        "collected_at": "2026-08-08T13:05:00.000000Z",
        "requested_window": WINDOW,
        "queried_window": TimeWindow.from_datetimes(START - timedelta(hours=1), COLLECTED),
        "cap": 10,
    }
    values.update(overrides)
    return SourceContext(**values)


def _extract(raw: dict[str, Any]) -> ExtractedRecord:
    return ExtractedRecord(
        record_id=raw.get("id"),
        record_id_field="id" if "id" in raw else None,
        time_field="time",
        time_value=raw.get("time", ABSENT) if "time" in raw else ABSENT,
        event_type=raw.get("key"),
        summary=raw.get("msg"),
        entities=tuple(
            EntityRef(kind=EntityKind.NETWORK_DEVICE, id_kind=IdKind.MAC, id=mac, role="AP")
            for mac in raw.get("macs", [])
        ),
        attributes=raw.get("attributes", {}),
    )


def _collect(records: list[Any], **context_overrides: Any):
    return collect_source(_context(**context_overrides), records, _extract)


def _time(value: Any, *, field: str = "time", uncertainty: int | None = None):
    return parse_event_time(field, value, window=WINDOW, clock_uncertainty_ms=uncertainty)


# --- version -----------------------------------------------------------------


def test_evidence_set_declares_schema_name_and_version() -> None:
    evidence = assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[_collect([])])
    payload = evidence_to_json(evidence)
    assert payload["schema"] == "unifi-incident-evidence"
    assert payload["schema_version"] == INCIDENT_EVIDENCE_SCHEMA_VERSION == 1


def test_unknown_schema_version_is_rejected() -> None:
    payload = evidence_to_json(
        assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[_collect([])])
    )
    with pytest.raises(ValidationError):
        IncidentEvidence.model_validate({**payload, "schema_version": 2})
    with pytest.raises(ValidationError):
        IncidentEvidence.model_validate({**payload, "unexpected": True})


# --- provenance --------------------------------------------------------------


def test_record_provenance_carries_scope_family_source_query_and_exact_record_id() -> None:
    evidence = _collect([{"id": 4711, "time": _ms(START + timedelta(minutes=5)), "key": "K"}])
    record = evidence.records[0]
    provenance = record.provenance
    assert provenance.product is Product.NETWORK
    assert provenance.api_family is ApiFamily.NETWORK_V2_CONTROLLER
    assert provenance.source_tool == "unifi_list_events"
    assert provenance.scope == Scope(site="default", location_id="loc-fixture-1")
    assert provenance.source_record_id == 4711  # kept as the integer the source returned
    assert provenance.source_record_id_field == "id"
    assert provenance.query == {"limit": 10, "within_hours": 2}
    assert provenance.collected_at == "2026-08-08T13:05:00.000000Z"
    assert record.evidence_id == "network.events:4711"


def test_secret_named_query_and_attribute_keys_are_excluded() -> None:
    context = _context(query={"limit": 10, "api_key": "fake-key", "password": "fake-pass", "x_auth_token": "fake"})
    evidence = collect_source(
        context,
        [{"id": "a", "time": _ms(START), "attributes": {"token": "fake", "severity": "LOW"}}],
        _extract,
    )
    serialized = json.dumps(
        evidence_to_json(assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[evidence]))
    )
    assert "fake" not in serialized
    assert evidence.records[0].attributes == {"severity": "LOW"}
    with pytest.raises(ValidationError):
        Provenance(
            product=Product.NETWORK,
            api_family=None,
            source_tool=None,
            endpoint=None,
            scope=Scope(),
            source_record_id=None,
            source_record_id_field=None,
            query={"api_key": "fake"},
            collected_at="2026-08-08T13:05:00.000000Z",
        )


def test_error_envelope_text_never_enters_evidence() -> None:
    failure = records_from_tool_response({"success": False, "error": "Failed: host fixture-gw.invalid"}, ("events",))
    assert failure == SourceFailure(kind=FailureKind.UNAVAILABLE)
    evidence = assemble_incident_evidence(
        requested_window=WINDOW, budgets=BUDGETS, sources=[source_failed(_context(), failure)]
    )
    assert "fixture-gw" not in canonical_json(evidence)


# --- time --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "fmt", "precision", "utc"),
    [
        (1786191000, TimestampFormat.EPOCH_SECONDS, TimePrecision.SECOND, "2026-08-08T12:10:00.000000Z"),
        (1786191000.25, TimestampFormat.EPOCH_SECONDS, TimePrecision.MICROSECOND, "2026-08-08T12:10:00.250000Z"),
        (1786191000123, TimestampFormat.EPOCH_MILLISECONDS, TimePrecision.MILLISECOND, "2026-08-08T12:10:00.123000Z"),
        ("1786191000123", TimestampFormat.EPOCH_MILLISECONDS, TimePrecision.MILLISECOND, "2026-08-08T12:10:00.123000Z"),
        ("2026-08-08T12:10:00Z", TimestampFormat.ISO8601, TimePrecision.SECOND, "2026-08-08T12:10:00.000000Z"),
        (
            "2026-08-08T17:40:00.5+05:30",
            TimestampFormat.ISO8601,
            TimePrecision.MILLISECOND,
            "2026-08-08T12:10:00.500000Z",
        ),
        (
            "2026-08-08 08:10:00.000001-0400",
            TimestampFormat.ISO8601,
            TimePrecision.MICROSECOND,
            "2026-08-08T12:10:00.000001Z",
        ),
        ("2026-08-08T12:10Z", TimestampFormat.ISO8601, TimePrecision.MINUTE, "2026-08-08T12:10:00.000000Z"),
    ],
)
def test_timestamps_normalize_to_utc_with_format_and_precision(value, fmt, precision, utc) -> None:
    result = _time(value)
    assert result.status is TimeStatus.IN_WINDOW
    assert result.original_value == value
    assert result.original_format is fmt
    assert result.precision is precision
    assert result.utc == utc


def test_offset_and_basis_are_recorded() -> None:
    assert _time("2026-08-08T17:40:00+05:30").utc_offset == "+05:30"
    assert _time("2026-08-08T08:40:00-0400").utc_offset == "-04:00"
    epoch = _time(1786191000)
    assert epoch.utc_offset is None and epoch.timezone_basis.value == "epoch_utc"


@pytest.mark.parametrize(
    ("value", "status"),
    [
        (ABSENT, TimeStatus.MISSING),
        (None, TimeStatus.MISSING),
        ("", TimeStatus.MALFORMED),
        ("yesterday", TimeStatus.MALFORMED),
        ("2026-02-30T12:00:00Z", TimeStatus.MALFORMED),
        (0, TimeStatus.MALFORMED),
        (-1786191000, TimeStatus.MALFORMED),
        (12345, TimeStatus.MALFORMED),
        (10**15, TimeStatus.MALFORMED),
        (True, TimeStatus.MALFORMED),
        (float("nan"), TimeStatus.MALFORMED),
        ({"ms": 1}, TimeStatus.MALFORMED),
        ([1786191000], TimeStatus.MALFORMED),
        ("2026-08-08T12:10:00", TimeStatus.AMBIGUOUS_TIMEZONE),
    ],
)
def test_unusable_timestamps_are_explicit_states(value, status) -> None:
    result = _time(value)
    assert result.status is status
    assert result.utc is None
    assert result.precision is None


def test_collection_time_never_substitutes_for_event_time() -> None:
    evidence = _collect([{"id": "no-time", "key": "K"}])
    record = evidence.records[0]
    assert record.time.status is TimeStatus.MISSING
    assert record.time.utc is None
    assert record.provenance.collected_at == "2026-08-08T13:05:00.000000Z"
    assert evidence.source.outcome is SourceOutcome.PARTIAL
    assert PartialReason.UNTIMED_RECORDS in evidence.source.partial_reasons


def test_window_is_half_open() -> None:
    assert _time(_ms(START)).status is TimeStatus.IN_WINDOW
    assert _time(_ms(START) - 1).status is TimeStatus.OUT_OF_WINDOW
    assert _time(_ms(END) - 1).status is TimeStatus.IN_WINDOW
    assert _time(_ms(END)).status is TimeStatus.OUT_OF_WINDOW
    assert WINDOW.start_inclusive is True and WINDOW.end_inclusive is False


def test_out_of_window_records_keep_their_time_but_do_not_count_as_in_window() -> None:
    evidence = _collect([{"id": "early", "time": _ms(START - timedelta(minutes=1))}])
    assert evidence.records[0].time.status is TimeStatus.OUT_OF_WINDOW
    assert evidence.records[0].time.utc == "2026-08-08T11:59:00.000000Z"
    assert evidence.source.outcome is SourceOutcome.EMPTY
    assert evidence.source.coverage.counts.out_of_window == 1


def test_known_clock_uncertainty_flags_boundary_events() -> None:
    near = _time(_ms(END) - 500, uncertainty=1000)
    far = _time(_ms(START + timedelta(minutes=30)), uncertainty=1000)
    assert near.clock_uncertainty_ms == 1000 and near.boundary_uncertain
    assert not far.boundary_uncertain
    assert _time(_ms(END) - 500).clock_uncertainty_ms is None


def test_requested_window_must_be_ordered() -> None:
    with pytest.raises(ValidationError):
        TimeWindow.from_datetimes(END, START)
    with pytest.raises(ValidationError):
        TimeWindow(start="2026-08-08T12:00:00Z", end="2026-08-08T13:00:00.000000Z")


# --- mapping -----------------------------------------------------------------


def _device(mac: str) -> EntityRef:
    return EntityRef(kind=EntityKind.NETWORK_DEVICE, id_kind=IdKind.MAC, id=mac)


def _camera(camera_id: str) -> EntityRef:
    return EntityRef(kind=EntityKind.CAMERA, id_kind=IdKind.PROTECT_CAMERA_ID, id=camera_id)


def test_mapping_requires_exact_identifier_and_ignores_case_and_separators_for_macs() -> None:
    assertion = MappingAssertion(entity=_device(AP), target=_camera(CAMERA), source=MappingSource.OPERATOR_INPUT)
    outcome = resolve_mapping([_device("AA-BB-CC-00-10-01")], [assertion])
    assert outcome.status is MappingStatus.VERIFIED
    assert outcome.targets == (_camera(CAMERA),)
    assert outcome.confidence == "exact_identifier"
    assert outcome.sources == (MappingSource.OPERATOR_INPUT,)


def test_similar_names_and_ids_never_establish_a_mapping() -> None:
    assertion = MappingAssertion(entity=_device(AP), target=_camera(CAMERA), source=MappingSource.OPERATOR_INPUT)
    named = EntityRef(kind=EntityKind.NETWORK_DEVICE, id_kind=IdKind.MAC, id="aa:bb:cc:00:10:02", role="front-door")
    assert resolve_mapping([named], [assertion]).status is MappingStatus.MISSING
    # A camera ID that merely resembles the AP's MAC is a different identity kind.
    lookalike = EntityRef(kind=EntityKind.CAMERA, id_kind=IdKind.PROTECT_CAMERA_ID, id=AP)
    assert resolve_mapping([lookalike], [assertion]).status is MappingStatus.MISSING


def test_nearby_timestamps_never_establish_a_mapping() -> None:
    network = collect_source(_context(), [{"id": "n1", "time": _ms(START), "macs": [AP]}], _extract)
    camera_context = _context(source_id="protect.events", product=Product.PROTECT, api_family=ApiFamily.PROTECT_PRIVATE)
    protect = collect_source(camera_context, [{"id": "p1", "time": _ms(START)}], _extract)
    evidence = assemble_incident_evidence(
        requested_window=WINDOW, budgets=BUDGETS, sources=[network, protect], mappings=[]
    )
    assert {r.mapping.status for r in evidence.records} == {MappingStatus.MISSING}


def test_conflicting_assertions_are_ambiguous_and_list_every_candidate() -> None:
    assertions = [
        MappingAssertion(entity=_device(AP), target=_camera("cam-b"), source=MappingSource.OPERATOR_INPUT),
        MappingAssertion(entity=_device(AP), target=_camera("cam-a"), source=MappingSource.PRODUCT_INVENTORY),
    ]
    outcome = resolve_mapping([_device(AP)], assertions)
    assert outcome.status is MappingStatus.AMBIGUOUS
    assert [t.id for t in outcome.targets] == ["cam-a", "cam-b"]
    assert outcome.confidence is None


def test_mapping_not_evaluated_without_assertions_and_outcomes_are_validated() -> None:
    assert resolve_mapping([_device(AP)], None).status is MappingStatus.NOT_EVALUATED
    with pytest.raises(ValidationError):
        MappingOutcome(
            status=MappingStatus.VERIFIED, targets=(_camera("a"), _camera("b")), confidence="exact_identifier"
        )
    with pytest.raises(ValidationError):
        MappingOutcome(status=MappingStatus.MISSING, targets=(_camera("a"),))


# --- coverage ----------------------------------------------------------------


def test_coverage_reports_requested_queried_filters_pagination_and_counts() -> None:
    context = _context(filters={"event_type": "K"}, offset=20, cap=3)
    raw = [
        {"id": "1", "time": _ms(START)},
        {"id": "1", "time": _ms(START)},
        "garbage",
        {"id": "2", "time": "bad"},
    ]
    source = collect_source(context, raw, _extract).source
    coverage = source.coverage
    assert coverage.requested_window == WINDOW
    assert coverage.queried_window == context.queried_window
    assert coverage.filters == {"event_type": "K"}
    assert coverage.pagination.offset == 20 and coverage.pagination.cap == 3
    assert coverage.counts.received == 4
    assert coverage.counts.duplicates_dropped == 1
    assert coverage.counts.malformed_dropped == 1
    assert coverage.counts.untimed == 1
    assert coverage.population_total is None
    assert source.partial_reasons == (
        PartialReason.MALFORMED_RECORDS,
        PartialReason.TRUNCATION_UNKNOWN,
        PartialReason.UNTIMED_RECORDS,
    )


@pytest.mark.parametrize(
    ("pagination", "expected"),
    [
        (Pagination(cap=10, returned=3), Truncation.NOT_TRUNCATED),
        (Pagination(cap=3, returned=3), Truncation.UNKNOWN),
        (Pagination(cap=None, returned=3), Truncation.UNKNOWN),
        (Pagination(cap=3, returned=3, has_more=False), Truncation.NOT_TRUNCATED),
        (Pagination(cap=10, returned=3, has_more=True), Truncation.TRUNCATED),
        (Pagination(offset=10, cap=10, returned=5, total_reported=40), Truncation.TRUNCATED),
        (Pagination(offset=35, cap=10, returned=5, total_reported=40), Truncation.NOT_TRUNCATED),
        (Pagination(cap=10, returned=3, interrupted=True), Truncation.UNKNOWN),
    ],
)
def test_truncation_follows_only_from_reported_pagination(pagination, expected) -> None:
    assert truncation_state(pagination) is expected


def test_cap_reached_count_is_not_a_population_total() -> None:
    source = _collect([{"id": str(i), "time": _ms(START) + i} for i in range(10)]).source
    assert source.coverage.counts.in_window == 10
    assert source.coverage.population_total is None
    assert source.outcome is SourceOutcome.PARTIAL


def test_complete_coverage_establishes_the_total() -> None:
    source = _collect([{"id": "a", "time": _ms(START)}]).source
    assert source.outcome is SourceOutcome.COMPLETE
    assert source.coverage.population_total == 1


def test_window_not_covered_or_unknown_is_partial() -> None:
    short = _context(queried_window=TimeWindow.from_datetimes(START + timedelta(minutes=5), COLLECTED))
    assert collect_source(short, [], _extract).source.partial_reasons == (PartialReason.WINDOW_NOT_COVERED,)
    unknown = collect_source(_context(queried_window=None), [], _extract).source
    assert unknown.outcome is SourceOutcome.PARTIAL
    assert unknown.partial_reasons == (PartialReason.WINDOW_COVERAGE_UNKNOWN,)


def test_coverage_rejects_a_total_without_completeness() -> None:
    complete = _collect([{"id": "a", "time": _ms(START)}]).source.coverage
    payload = complete.model_dump()
    payload["pagination"] = {**payload["pagination"], "has_more": True}
    with pytest.raises(ValidationError):
        Coverage.model_validate({**payload, "truncation": "truncated"})


# --- failure -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "kind", "status"),
    [
        (asyncio.TimeoutError(), FailureKind.TIMEOUT, None),
        (UniFiAuthError("fixture"), FailureKind.AUTH_FAILED, None),
        (UniFiPermissionError("fixture"), FailureKind.PERMISSION_DENIED, None),
        (ConnectionRefusedError(), FailureKind.UNAVAILABLE, None),
        (RuntimeError("Call https://fixture.invalid/x received 404 Not Found"), FailureKind.UNSUPPORTED, 404),
        (RuntimeError("Call https://fixture.invalid/x received 401 Unauthorized"), FailureKind.AUTH_FAILED, 401),
        (RuntimeError("Call https://fixture.invalid/x received 403 Forbidden"), FailureKind.PERMISSION_DENIED, 403),
        (json.JSONDecodeError("bad", "x", 0), FailureKind.PARSE_FAILED, None),
        (RuntimeError("anything else"), FailureKind.UNAVAILABLE, None),
    ],
)
def test_exceptions_classify_without_reading_messages_into_evidence(exc, kind, status) -> None:
    failure = failure_from_exception(exc)
    assert failure == SourceFailure(kind=kind, http_status=status)


@pytest.mark.parametrize(
    ("kind", "outcome"),
    [
        (FailureKind.UNAVAILABLE, SourceOutcome.UNAVAILABLE),
        (FailureKind.AUTH_FAILED, SourceOutcome.AUTH_FAILED),
        (FailureKind.PERMISSION_DENIED, SourceOutcome.PERMISSION_DENIED),
        (FailureKind.TIMEOUT, SourceOutcome.TIMEOUT),
        (FailureKind.UNSUPPORTED, SourceOutcome.UNSUPPORTED),
        (FailureKind.PARSE_FAILED, SourceOutcome.PARSE_FAILED),
        (FailureKind.BUDGET_EXHAUSTED, SourceOutcome.NOT_ATTEMPTED),
    ],
)
def test_failed_sources_are_distinct_from_empty_success(kind, outcome) -> None:
    source = source_failed(_context(), SourceFailure(kind=kind)).source
    assert source.outcome is outcome
    assert source.outcome is not SourceOutcome.EMPTY
    assert source.coverage.complete is False
    assert source.coverage.window_coverage.value == "unknown"
    assert source.coverage.truncation is Truncation.UNKNOWN


def test_empty_success_is_its_own_outcome() -> None:
    source = _collect([]).source
    assert source.outcome is SourceOutcome.EMPTY
    assert source.coverage.population_total == 0


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        ({"success": False, "error": "x"}, FailureKind.UNAVAILABLE),
        ({"success": True}, FailureKind.PARSE_FAILED),
        ({"success": True, "events": {"not": "a list"}}, FailureKind.PARSE_FAILED),
        ("not an envelope", FailureKind.PARSE_FAILED),
        ({"events": []}, FailureKind.PARSE_FAILED),
    ],
)
def test_tool_envelopes_that_carry_no_records_fail(response, kind) -> None:
    assert records_from_tool_response(response, ("events",)) == SourceFailure(kind=kind)


def test_unparseable_record_container_is_parse_failed() -> None:
    assert collect_source(_context(), {"not": "a list"}, _extract).source.outcome is SourceOutcome.PARSE_FAILED


def test_partial_response_keeps_records_and_the_failure() -> None:
    timeout = SourceFailure(kind=FailureKind.TIMEOUT)
    evidence = collect_source(_context(), [{"id": "a", "time": _ms(START)}], _extract, failure=timeout)
    assert evidence.source.outcome is SourceOutcome.PARTIAL
    assert evidence.source.failure == timeout
    assert PartialReason.PARTIAL_RESPONSE in evidence.source.partial_reasons
    assert evidence.source.coverage.truncation is Truncation.UNKNOWN
    assert len(evidence.records) == 1
    empty_timeout = collect_source(_context(), [], _extract, failure=timeout)
    assert empty_timeout.source.outcome is SourceOutcome.TIMEOUT


def test_total_failure_never_becomes_an_empty_timeline() -> None:
    evidence = assemble_incident_evidence(
        requested_window=WINDOW,
        budgets=BUDGETS,
        sources=[
            source_failed(_context(), SourceFailure(kind=FailureKind.AUTH_FAILED, http_status=401)),
            source_failed(_context(source_id="protect.events"), SourceFailure(kind=FailureKind.TIMEOUT)),
        ],
    )
    assert evidence.overall is OverallStatus.FAILED
    assert evidence.coverage_complete is False
    payload = evidence_to_json(evidence)
    for forged in ("empty", "complete", "partial"):
        with pytest.raises(ValidationError):
            IncidentEvidence.model_validate({**payload, "overall": forged})


def test_partial_evidence_keeps_per_source_status_and_is_never_an_all_clear() -> None:
    evidence = assemble_incident_evidence(
        requested_window=WINDOW,
        budgets=BUDGETS,
        sources=[
            _collect([]),
            source_failed(_context(source_id="protect.events"), SourceFailure(kind=FailureKind.UNAVAILABLE)),
        ],
    )
    assert evidence.overall is OverallStatus.PARTIAL
    assert [s.outcome for s in evidence.sources] == [SourceOutcome.EMPTY, SourceOutcome.UNAVAILABLE]
    assert evidence.coverage_complete is False
    with pytest.raises(ValidationError):
        IncidentEvidence.model_validate({**evidence_to_json(evidence), "coverage_complete": True})


def test_only_all_empty_complete_sources_are_empty_overall() -> None:
    evidence = assemble_incident_evidence(
        requested_window=WINDOW, budgets=BUDGETS, sources=[_collect([]), _collect([], source_id="protect.events")]
    )
    assert evidence.overall is OverallStatus.EMPTY and evidence.coverage_complete


def test_failed_source_cannot_claim_records_or_coverage() -> None:
    source = source_failed(_context(), SourceFailure(kind=FailureKind.TIMEOUT)).source
    with pytest.raises(ValidationError):
        type(source).model_validate({**source.model_dump(), "outcome": "empty", "failure": None})
    with pytest.raises(ValidationError):
        type(source).model_validate({**source.model_dump(), "outcome": "unavailable"})


# --- budgets -----------------------------------------------------------------


def test_budgets_are_contract_inputs_and_exhaustion_makes_evidence_partial() -> None:
    budgets = Budgets(
        limits=BudgetLimits(window_seconds=7200, events=1, calls=5, elapsed_ms=1000),
        usage=BudgetUsage(events=1, calls=1, elapsed_ms=10),
        exhausted=(BudgetKind.EVENTS,),
    )
    evidence = assemble_incident_evidence(
        requested_window=WINDOW, budgets=budgets, sources=[_collect([{"id": "a", "time": _ms(START)}])]
    )
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE
    assert evidence.overall is OverallStatus.PARTIAL
    assert evidence.coverage_complete is False


def test_window_longer_than_budget_must_report_window_exhaustion() -> None:
    tight = Budgets(limits=BudgetLimits(window_seconds=60, events=10, calls=5, elapsed_ms=1000))
    with pytest.raises(ValidationError):
        assemble_incident_evidence(requested_window=WINDOW, budgets=tight, sources=[_collect([])])
    reported = tight.model_copy(update={"exhausted": (BudgetKind.WINDOW,)})
    evidence = assemble_incident_evidence(requested_window=WINDOW, budgets=reported, sources=[_collect([])])
    assert evidence.overall is OverallStatus.PARTIAL


def test_budget_overrun_must_be_reported_and_exhaustion_must_be_real() -> None:
    limits = BudgetLimits(window_seconds=7200, events=10, calls=2, elapsed_ms=1000)
    with pytest.raises(ValidationError):
        Budgets(limits=limits, usage=BudgetUsage(elapsed_ms=1500))
    with pytest.raises(ValidationError):
        Budgets(limits=limits, usage=BudgetUsage(calls=1), exhausted=(BudgetKind.CALLS,))
    Budgets(limits=limits, usage=BudgetUsage(elapsed_ms=1500), exhausted=(BudgetKind.ELAPSED,))


def test_budget_stop_marks_the_source_partial() -> None:
    source = collect_source(_context(), [{"id": "a", "time": _ms(START)}], _extract, budget_exhausted=True).source
    assert source.outcome is SourceOutcome.PARTIAL
    assert PartialReason.BUDGET_EXHAUSTED in source.partial_reasons


# --- ordering ----------------------------------------------------------------


def test_ordering_is_utc_then_product_source_and_record_id_with_untimed_last() -> None:
    same = _ms(START + timedelta(minutes=10))
    network = collect_source(
        _context(), [{"id": "n2", "time": same}, {"id": "n1", "time": same}, {"id": "nx"}], _extract
    )
    protect = collect_source(
        _context(source_id="protect.events", product=Product.PROTECT, api_family=ApiFamily.PROTECT_PRIVATE),
        [{"id": "p1", "time": same}, {"id": "p0", "time": same - 1}],
        _extract,
    )
    evidence = assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[protect, network])
    assert [r.evidence_id for r in evidence.records] == [
        "protect.events:p0",
        "network.events:n1",
        "network.events:n2",
        "protect.events:p1",
        "network.events:nx",
    ]
    shuffled_sources = [protect, network]
    random.Random(7).shuffle(shuffled_sources)
    again = assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=shuffled_sources)
    assert canonical_json(again) == canonical_json(evidence)


def test_records_without_ids_get_stable_content_hash_ids() -> None:
    first = _collect([{"key": "K", "time": _ms(START)}]).records[0]
    second = _collect([{"time": _ms(START), "key": "K"}]).records[0]
    assert first.evidence_id == second.evidence_id
    assert first.evidence_id.startswith("network.events:sha256:")
    assert first.evidence_id_basis == "content_hash"
    assert first.provenance.source_record_id is None


def test_out_of_order_records_are_rejected() -> None:
    evidence = assemble_incident_evidence(
        requested_window=WINDOW,
        budgets=BUDGETS,
        sources=[_collect([{"id": "a", "time": _ms(START)}, {"id": "b", "time": _ms(START) + 1}])],
    )
    payload = evidence_to_json(evidence)
    payload["records"] = list(reversed(payload["records"]))
    with pytest.raises(ValidationError):
        IncidentEvidence.model_validate(payload)


def test_sources_must_share_the_requested_window() -> None:
    other = TimeWindow.from_datetimes(START, END + timedelta(minutes=1))
    with pytest.raises(ValueError):
        assemble_incident_evidence(requested_window=other, budgets=BUDGETS, sources=[_collect([])])
