"""Evidence can never overstate completeness, and validation recomputes every derived claim."""

from __future__ import annotations

import copy
import itertools
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError
from unifi_core.exceptions import UniFiMalformedResponseError
from unifi_core.incident_evidence import (
    ABSENT,
    ApiFamily,
    BudgetLimits,
    Budgets,
    EntityKind,
    EntityRef,
    ExtractedRecord,
    FailureKind,
    IdKind,
    MappingAssertion,
    MappingSource,
    MappingStatus,
    OverallStatus,
    PartialReason,
    Product,
    Scope,
    SourceContext,
    SourceFailure,
    SourceOutcome,
    TimeStatus,
    TimeWindow,
    Truncation,
    assemble_incident_evidence,
    canonical_json,
    collect_source,
    evidence_to_json,
    failure_from_exception,
    parse_event_time,
    source_failed,
    validate_incident_evidence,
)

UTC = timezone.utc
START = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
END = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
WINDOW = TimeWindow.from_datetimes(START, END)
BUDGETS = Budgets(limits=BudgetLimits(window_seconds=7200, events=100, calls=10, elapsed_ms=60_000))
AP = "aa:bb:cc:00:10:01"


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _context(**overrides: Any) -> SourceContext:
    values: dict[str, Any] = {
        "source_id": "network.events",
        "product": Product.NETWORK,
        "api_family": ApiFamily.NETWORK_V2_CONTROLLER,
        "source_tool": "unifi_list_events",
        "scope": Scope(site="default"),
        "query": {"limit": 100},
        "collected_at": "2026-08-08T13:05:00.000000Z",
        "requested_window": WINDOW,
        "queried_window": TimeWindow.from_datetimes(START - timedelta(hours=1), END),
        "offset": 0,
        "requested_cap": 100,
        "cap": 100,
        # The source said it ran out; without this nothing proves completeness.
        "has_more": False,
    }
    values.update(overrides)
    return SourceContext(**values)


def _extract(raw: dict[str, Any]) -> ExtractedRecord:
    return ExtractedRecord(
        record_id=raw.get("id"),
        record_id_field="id" if "id" in raw else None,
        time_field="time",
        time_value=raw["time"] if "time" in raw else ABSENT,
        event_type=raw.get("key"),
        summary=None,
        entities=tuple(
            EntityRef(kind=EntityKind.NETWORK_DEVICE, id_kind=IdKind.MAC, id=mac, role="AP")
            for mac in raw.get("macs", [])
        ),
    )


def _evidence(records: list[Any], *, mappings=None, **context_overrides: Any):
    source = collect_source(_context(**context_overrides), records, _extract)
    return assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[source], mappings=mappings)


def _valid_payload() -> dict[str, Any]:
    return evidence_to_json(_evidence([{"id": "a", "time": _ms(START + timedelta(minutes=10)), "macs": [AP]}]))


# --- 1: short lists never establish completeness ----------------------------


def test_offset_page_never_establishes_complete_coverage() -> None:
    evidence = _evidence([], offset=100)
    source = evidence.sources[0]
    assert source.outcome is SourceOutcome.PARTIAL
    assert PartialReason.PREFIX_NOT_COLLECTED in source.partial_reasons
    assert source.coverage.population_total is None
    assert evidence.overall is OverallStatus.PARTIAL and not evidence.coverage_complete


def test_offset_page_with_reported_total_is_still_partial() -> None:
    source = _evidence([{"id": "a", "time": _ms(START)}], offset=35, total_reported=36).sources[0]
    assert source.coverage.truncation is Truncation.NOT_TRUNCATED  # nothing after this page
    assert source.partial_reasons == (PartialReason.PREFIX_NOT_COLLECTED,)


def test_post_filtered_short_list_is_never_complete() -> None:
    source = _evidence(
        [{"id": "a", "time": _ms(START)}], cap=30, requested_cap=30, post_filtered=True, has_more=None
    ).sources[0]
    assert source.outcome is SourceOutcome.PARTIAL
    assert set(source.partial_reasons) == {PartialReason.POST_FILTERED, PartialReason.TRUNCATION_UNKNOWN}


def test_effective_cap_below_request_is_retained_and_reached_cap_is_unknown() -> None:
    rows = [{"id": str(i), "time": _ms(START) + i} for i in range(3)]
    source = _evidence(rows, requested_cap=5000, cap=3, has_more=None).sources[0]
    assert source.coverage.pagination.requested_cap == 5000
    assert source.coverage.pagination.cap == 3
    assert source.coverage.truncation is Truncation.UNKNOWN
    with pytest.raises(ValidationError):
        _context(requested_cap=10, cap=20)


# --- 4: identity and conflicting versions -------------------------------------


def test_integer_and_string_ids_are_distinct_records() -> None:
    evidence = _evidence([{"id": 7, "time": _ms(START)}, {"id": "7", "time": _ms(START) + 1}])
    assert [r.evidence_id for r in evidence.records] == ["network.events|int|7", "network.events|str|7"]
    assert evidence.sources[0].coverage.counts.duplicates_dropped == 0


def test_identical_duplicates_collapse() -> None:
    row = {"id": "a", "time": _ms(START), "key": "K"}
    evidence = _evidence([row, dict(reversed(list(row.items())))])
    assert len(evidence.records) == 1
    assert evidence.sources[0].coverage.counts.duplicates_dropped == 1
    assert evidence.overall is OverallStatus.COMPLETE


CONFLICT = [
    {"id": "fixture-conflict", "time": _ms(START - timedelta(hours=1)), "key": "EVT_AP_Connected"},
    {"id": "fixture-conflict", "time": _ms(START + timedelta(minutes=10)), "key": "EVT_AP_Lost_Contact"},
    {"id": "fixture-conflict", "time": _ms(START + timedelta(minutes=10)), "key": "EVT_AP_Lost_Contact"},
]


def test_conflicting_versions_stay_visible_and_block_completeness() -> None:
    evidence = _evidence(CONFLICT)
    source = evidence.sources[0]
    assert {r.event_type for r in evidence.records} == {"EVT_AP_Connected", "EVT_AP_Lost_Contact"}
    assert {r.conflict_group for r in evidence.records} == {"network.events|str|fixture-conflict"}
    assert source.coverage.counts.conflicting == 2
    assert source.coverage.counts.duplicates_dropped == 1
    assert PartialReason.CONFLICTING_RECORDS in source.partial_reasons
    assert evidence.overall is OverallStatus.PARTIAL and not evidence.coverage_complete


def test_collection_does_not_depend_on_input_order() -> None:
    outputs = {canonical_json(_evidence(list(order))) for order in itertools.permutations(CONFLICT)}
    assert len(outputs) == 1


# --- 5/6: validation recomputes derived claims -------------------------------


def test_forged_mapping_without_supporting_assertion_is_rejected() -> None:
    payload = _valid_payload()
    payload["mappings"] = []
    payload["records"][0]["mapping"] = {
        "status": "verified",
        "targets": [{"kind": "camera", "id_kind": "protect_camera_id", "id": "fixture-unrelated", "role": None}],
        "matched_on": [{"kind": "network_device", "id_kind": "mac", "id": "aa:bb:cc:00:00:ff", "role": None}],
        "sources": ["product_inventory"],
        "confidence": "exact_identifier",
    }
    with pytest.raises(ValidationError, match="mapping outcome"):
        validate_incident_evidence(payload)


def test_genuine_mapping_survives_round_trip() -> None:
    assertion = MappingAssertion(
        entity=EntityRef(kind=EntityKind.NETWORK_DEVICE, id_kind=IdKind.MAC, id=AP),
        target=EntityRef(kind=EntityKind.CAMERA, id_kind=IdKind.PROTECT_CAMERA_ID, id="cam-fixture-000a"),
        source=MappingSource.OPERATOR_INPUT,
    )
    evidence = _evidence([{"id": "a", "time": _ms(START), "macs": [AP]}], mappings=[assertion])
    assert evidence.records[0].mapping.status is MappingStatus.VERIFIED
    assert validate_incident_evidence(evidence_to_json(evidence)) == evidence


@pytest.mark.parametrize(
    "forge",
    [
        lambda p: p["records"][0]["time"].update(utc="2026-08-09T12:10:00.000000Z"),
        lambda p: p["records"][0]["time"].update(status="out_of_window"),
        lambda p: p["records"][0]["time"].update(original_value=_ms(START + timedelta(minutes=11))),
        lambda p: p["records"][0]["time"].update(precision="second"),
        lambda p: p["sources"][0]["coverage"].update(
            requested_window={**p["requested_window"], "end": "2026-08-08T12:30:00.000000Z"}
        ),
        lambda p: p["sources"][0]["coverage"]["pagination"].update(interrupted=True, total_reported=1),
        lambda p: p["sources"][0]["coverage"].update(observed_last_utc="2026-08-08T12:50:00.000000Z"),
        lambda p: p["records"][0]["provenance"].update(collected_at="2026-08-08T13:06:00.000000Z"),
        lambda p: p["records"][0].update(evidence_id="network.events|str|other"),
        lambda p: p["records"][0]["provenance"].update(source_record_id=1),
    ],
    ids=[
        "event-utc",
        "time-status",
        "original-value",
        "precision",
        "source-window",
        "interrupted-complete",
        "observed-bounds",
        "record-provenance",
        "evidence-id",
        "id-type",
    ],
)
def test_inconsistent_serialized_claims_are_rejected(forge) -> None:
    payload = copy.deepcopy(_valid_payload())
    forge(payload)
    with pytest.raises(ValidationError):
        validate_incident_evidence(payload)


# --- 7: secrets ---------------------------------------------------------------


def test_secret_named_coverage_filter_is_rejected() -> None:
    payload = _valid_payload()
    payload["sources"][0]["coverage"]["filters"] = {"api_key": "fixture-secret-value"}
    with pytest.raises(ValidationError, match="secret"):
        validate_incident_evidence(payload)
    assert _context(filters={"api_key": "x", "event_type": "K"}).filters == {"event_type": "K"}


# --- 8: failure construction --------------------------------------------------


@pytest.mark.parametrize("claims", [{"has_more": True}, {"total_reported": 100}, {"total_reported": 0}])
def test_failed_source_discards_pagination_claims(claims) -> None:
    source = source_failed(_context(**claims), SourceFailure(kind=FailureKind.TIMEOUT)).source
    assert source.outcome is SourceOutcome.TIMEOUT
    assert source.coverage.pagination.has_more is None
    assert source.coverage.pagination.total_reported is None
    assert source.coverage.truncation is Truncation.UNKNOWN
    assert source.coverage.queried_window is None


# --- 10: classification never raises ------------------------------------------


class _OpaqueError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("fixture opaque renderer")


@pytest.mark.parametrize(
    ("exc", "kind", "status"),
    [
        (_OpaqueError(), FailureKind.UNAVAILABLE, None),
        (RuntimeError({"errorCode": 999}), FailureKind.UNAVAILABLE, None),
        (RuntimeError({"errorCode": 42}), FailureKind.UNAVAILABLE, None),
        (RuntimeError({"errorCode": 404}), FailureKind.UNSUPPORTED, 404),
        (UniFiMalformedResponseError("Unexpected response shape from /stat/event"), FailureKind.PARSE_FAILED, None),
    ],
)
def test_failure_classification_never_raises(exc, kind, status) -> None:
    assert failure_from_exception(exc) == SourceFailure(kind=kind, http_status=status)


# --- 11: ISO edge inputs ------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "status"),
    [
        ("0001-01-01T00:00:00+01:00", TimeStatus.MALFORMED),
        ("9999-12-31T23:59:59-01:00", TimeStatus.MALFORMED),
        ("2026-08-08T12:00:00+00:60", TimeStatus.MALFORMED),
        ("2026-08-08T12:00:00+24:00", TimeStatus.MALFORMED),
        ("2026-02-30T12:00:00", TimeStatus.MALFORMED),
        ("2026-08-08T25:00:00", TimeStatus.MALFORMED),
        ("2026-08-08T12:00:00", TimeStatus.AMBIGUOUS_TIMEZONE),
        ("0001-01-01T00:00:00Z", TimeStatus.OUT_OF_WINDOW),
    ],
)
def test_iso_edge_inputs_are_explicit_states(value, status) -> None:
    assert parse_event_time("time", value, window=WINDOW).status is status


def test_far_past_utc_keeps_the_fixed_width_form() -> None:
    assert parse_event_time("time", "0001-01-01T00:00:00Z", window=WINDOW).utc == "0001-01-01T00:00:00.000000Z"


# --- clock uncertainty at a boundary -----------------------------------------


def test_out_of_window_event_within_clock_uncertainty_blocks_an_all_clear() -> None:
    evidence = _evidence([{"id": "u", "time": _ms(END) + 500}], clock_uncertainty_ms=1000)
    record, source = evidence.records[0], evidence.sources[0]
    assert record.time.status is TimeStatus.OUT_OF_WINDOW and record.time.boundary_uncertain
    assert source.partial_reasons == (PartialReason.BOUNDARY_UNCERTAIN,)
    assert evidence.overall is OverallStatus.PARTIAL and not evidence.coverage_complete


# --- item 7: unambiguous identity -------------------------------------------


def test_a_legitimate_id_cannot_collide_with_a_conflict_version() -> None:
    raw = {"id": "fixture-event", "time": _ms(START), "key": "A"}
    first = _evidence([raw, dict(raw, key="B")])
    version_suffix = first.records[0].evidence_id.split("|", 2)[2]
    evidence = _evidence([raw, dict(raw, key="B"), dict(raw, id=version_suffix)])
    ids = [r.evidence_id for r in evidence.records]
    assert len(ids) == len(set(ids)) == 3


def test_source_and_record_ids_cannot_combine_into_a_collision() -> None:
    raw = {"time": _ms(START), "key": "K"}
    one = collect_source(_context(source_id="network"), [dict(raw, id="a:str:b")], _extract)
    two = collect_source(_context(source_id="network:str:a"), [dict(raw, id="b")], _extract)
    evidence = assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[one, two])
    assert {r.evidence_id for r in evidence.records} == {"network|str|a%3Astr%3Ab", "network:str:a|str|b"}


@pytest.mark.parametrize("record_id", ["a|str|b", "x#y", "100%", "spaces and/slashes", "naïve"])
def test_record_ids_are_escaped_and_round_trip(record_id) -> None:
    evidence = _evidence([{"id": record_id, "time": _ms(START)}])
    record = evidence.records[0]
    assert record.provenance.source_record_id == record_id
    assert record.evidence_id.count("|") == 2
    assert validate_incident_evidence(evidence_to_json(evidence)) == evidence


def test_forged_evidence_digest_is_rejected() -> None:
    payload = evidence_to_json(_evidence([{"time": _ms(START), "key": "K"}]))
    payload["records"][0]["evidence_id"] = "network.events|sha256|" + "a" * 24
    with pytest.raises(ValidationError, match="evidence_id"):
        validate_incident_evidence(payload)


# --- item 8: observed bounds ---------------------------------------------------


@pytest.mark.parametrize("field", ["observed_first_utc", "observed_last_utc"])
def test_a_missing_observed_bound_is_a_validation_error(field) -> None:
    payload = _valid_payload()
    payload["sources"][0]["coverage"][field] = None
    with pytest.raises(ValidationError, match="observed bounds"):
        validate_incident_evidence(payload)


# --- item 3: evidence key grammar ------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["api_key", "Authorization", "password", "access_token", "private_key", "apiKey", "x_passphrase", "cookie"],
)
def test_secret_named_or_non_snake_keys_are_rejected(key) -> None:
    payload = _valid_payload()
    payload["sources"][0]["coverage"]["filters"] = {key: "fixture-secret-value"}
    with pytest.raises(ValidationError, match="keys are not allowed"):
        validate_incident_evidence(payload)


def test_key_deny_pattern_covers_every_sensitive_key_name() -> None:
    from unifi_core import redaction
    from unifi_core.incident_evidence import EVIDENCE_KEY_DENY_PATTERN, evidence_key_allowed

    names = (
        set(redaction._SENSITIVE_EXACT)
        | set(redaction._SENSITIVE_COMPOUNDS)
        | set(redaction._SENSITIVE_SEGMENTS)
        | {"sha512passwd", "wireguard_client_private_key", "x_ipsec_pre_shared_key"}
    )
    for name in names:
        assert redaction.is_sensitive_key(name)
        assert not evidence_key_allowed(name), name
        assert __import__("re").search(EVIDENCE_KEY_DENY_PATTERN, name), name
    for allowed in ["event_type", "categories", "min_confidence_effective", "smart_detect_types", "within_hours"]:
        assert evidence_key_allowed(allowed)
