"""Shared incident collection: request validation, budget enforcement and combining evidence sets."""

from __future__ import annotations

import asyncio
import itertools
import json
from datetime import datetime, timedelta, timezone

import jsonschema
import pytest
from pydantic import ValidationError
from unifi_core.incident_collection import (
    BudgetMeter,
    IncidentCollectionRequest,
    combine_incident_evidence,
    describe_validation_error,
    read_source_pages,
)
from unifi_core.incident_evidence import (
    BudgetKind,
    BudgetLimits,
    EntityKind,
    EntityRef,
    FailureKind,
    IdKind,
    MappingAssertion,
    MappingSource,
    MappingStatus,
    OverallStatus,
    SourceOutcome,
    evidence_to_json,
    validate_incident_evidence,
)
from unifi_core.network.incident_collection import collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.protect.incident_collection import collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest
from unifi_core.source_page import SourcePage

from .incident_evidence_corpus import SCHEMA_PATH

UTC = timezone.utc
NOW = datetime(2026, 8, 8, 13, 0, tzinfo=UTC)
WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T12:55:00+00:00"}
DEVICE = "02:00:00:00:00:0a"
CAMERA = "cam-fixture-000a"
SCHEMA = json.loads(SCHEMA_PATH.read_text())


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def assert_contract_valid(evidence) -> dict:
    payload = evidence_to_json(evidence)
    jsonschema.validate(payload, SCHEMA)
    assert validate_incident_evidence(payload) == evidence
    return payload


class NetworkLog:
    """A v2 event log of ``total`` rows, newest first, one minute apart from NOW."""

    def __init__(self, total: int, *, report_total: bool = True) -> None:
        self.total = total
        self.report_total = report_total
        self.reads: list[tuple[int, int]] = []

    async def read_events_page(self, *, within, limit, offset=0, window_ms=None):
        start = offset
        self.reads.append((start, limit))
        rows = [
            {
                "id": f"evt-{i:04d}",
                "key": "DEVICE_DISCONNECTED_AP",
                "timestamp": _ms(NOW - timedelta(minutes=1 + i)),
                "parameters": {"DEVICE": {"id": DEVICE if i % 2 == 0 else "02:00:00:00:00:0b"}},
            }
            for i in range(start, min(start + limit, self.total))
        ]
        short = len(rows) < limit
        return SourcePage(
            rows=rows,
            has_more=False if short and not self.report_total else None,
            total_reported=self.total if self.report_total else None,
            offset=start,
            cap=limit,
            api_path="v2",
            submitted_window_ms=window_ms or (_ms(NOW) - within * 3_600_000, _ms(NOW)),
        )


class ProtectLog:
    def __init__(self, total: int) -> None:
        self.total = total
        self.reads: list[tuple[str | None, int, int]] = []

    async def list_events_raw_page(self, *, start, end, limit, offset=0, camera_id=None):
        self.reads.append((camera_id, offset, limit))
        rows = [
            {
                "id": f"p-{camera_id}-{i}",
                "type": "motion",
                "camera": camera_id or CAMERA,
                "start": _ms(NOW) - 600_000 - i,
            }
            for i in range(offset, min(offset + limit, self.total))
        ]
        return SourcePage(
            rows=rows,
            has_more=False if len(rows) < limit else None,
            offset=offset,
            cap=limit,
            submitted_window_ms=(_ms(start), _ms(end)),
        )


def _fixed_now():
    return NOW


# --- request validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-08-08T12:00:00", "2026-08-08T13:00:00Z"),  # no offset: ambiguous
        ("yesterday", "2026-08-08T13:00:00Z"),
        ("2026-08-08T13:00:00Z", "2026-08-08T12:00:00Z"),  # reversed
        ("2026-08-08T13:00:00Z", "2026-08-08T13:00:00Z"),  # empty
    ],
)
def test_window_bounds_need_an_offset_and_an_order(start, end) -> None:
    with pytest.raises(ValidationError) as error:
        IncidentCollectionRequest(start=start, end=end)
    message = describe_validation_error(error.value)
    assert "yesterday" not in message


def test_request_carries_budgets_and_an_exact_window() -> None:
    request = IncidentCollectionRequest(start="2026-08-08T14:00:00+02:00", end="2026-08-08T12:30:00Z", max_events=7)
    assert request.window.start == "2026-08-08T12:00:00.000000Z"
    assert request.limits == BudgetLimits(window_seconds=86_400, events=7, calls=20, elapsed_ms=30_000)


@pytest.mark.parametrize("field", ["max_events", "max_calls", "max_elapsed_ms", "max_window_seconds"])
def test_budgets_are_bounded(field) -> None:
    with pytest.raises(ValidationError):
        IncidentCollectionRequest(**WINDOW, **{field: 0})
    with pytest.raises(ValidationError):
        IncidentCollectionRequest(**WINDOW, **{field: 10**9})


def test_device_filters_are_exact_macs_never_names() -> None:
    request = NetworkIncidentRequest(**WINDOW, device_macs=["02-00-00-00-00-0A", DEVICE])
    assert request.device_macs == (DEVICE,)
    with pytest.raises(ValidationError):
        NetworkIncidentRequest(**WINDOW, device_macs=["fixture-ap-1"])


def test_camera_filters_are_exact_ids() -> None:
    assert ProtectIncidentRequest(**WINDOW, camera_ids=["b", "a", "a"]).camera_ids == ("a", "b")
    with pytest.raises(ValidationError):
        ProtectIncidentRequest(**WINDOW, camera_ids=["Front Door"])


# --- budgets -------------------------------------------------------------------------------


async def _network(total=40, **budget):
    log = NetworkLog(total)
    request = NetworkIncidentRequest(**WINDOW, **budget)
    return log, await collect_network_incident_evidence(log, request, now=_fixed_now)


@pytest.mark.asyncio
async def test_a_single_page_that_proves_its_end_is_complete() -> None:
    log, evidence = await _network(total=40)
    assert_contract_valid(evidence)
    assert log.reads == [(0, 100)]
    (source,) = evidence.sources
    assert source.outcome is SourceOutcome.COMPLETE
    assert source.coverage.truncation.value == "not_truncated"
    assert evidence.budgets.exhausted == ()


@pytest.mark.asyncio
async def test_reading_several_offset_pages_never_claims_the_end() -> None:
    """Offsets have no snapshot: an event moving between reads can be skipped while totals stay equal."""
    log, evidence = await _network(total=250)
    payload = assert_contract_valid(evidence)
    assert log.reads == [(0, 100), (100, 100), (200, 100)]
    (source,) = evidence.sources
    assert source.outcome is SourceOutcome.PARTIAL
    assert [reason.value for reason in source.partial_reasons] == ["truncation_unknown"]
    assert source.coverage.pagination.total_reported is None and source.coverage.complete is False
    assert len(evidence.records) == 250
    assert payload["budgets"]["usage"] == {
        "events": 250,
        "calls": 3,
        "elapsed_ms": payload["budgets"]["usage"]["elapsed_ms"],
    }
    assert evidence.budgets.exhausted == ()


@pytest.mark.asyncio
async def test_event_budget_stops_reading_and_names_itself() -> None:
    log, evidence = await _network(total=250, max_events=150)
    assert_contract_valid(evidence)
    assert log.reads == [(0, 100), (100, 50)]  # never asks for more rows than remain
    (source,) = evidence.sources
    assert evidence.budgets.exhausted == (BudgetKind.EVENTS,)
    assert evidence.budgets.usage.events == 150
    assert source.outcome is SourceOutcome.PARTIAL
    assert [reason.value for reason in source.partial_reasons] == ["budget_exhausted", "truncation_unknown"]
    assert source.coverage.pagination.interrupted is True
    assert evidence.overall is OverallStatus.PARTIAL and evidence.coverage_complete is False


@pytest.mark.asyncio
async def test_call_budget_stops_reading_and_names_itself() -> None:
    log, evidence = await _network(total=250, max_calls=2)
    assert_contract_valid(evidence)
    assert len(log.reads) == 2
    assert evidence.budgets.exhausted == (BudgetKind.CALLS,)
    assert evidence.budgets.usage.calls == 2
    assert "budget_exhausted" in [r.value for r in evidence.sources[0].partial_reasons]


@pytest.mark.asyncio
async def test_elapsed_budget_stops_reading_between_pages() -> None:
    ticks = itertools.count(0.0, 0.6)  # every clock read advances 600 ms
    log = NetworkLog(250)
    request = NetworkIncidentRequest(**WINDOW, max_elapsed_ms=1_000)
    evidence = await collect_network_incident_evidence(log, request, now=_fixed_now, clock=lambda: next(ticks))
    assert_contract_valid(evidence)
    assert len(log.reads) == 1
    assert evidence.budgets.exhausted == (BudgetKind.ELAPSED,)
    assert evidence.budgets.usage.elapsed_ms >= 1_000
    assert evidence.sources[0].outcome is SourceOutcome.PARTIAL


@pytest.mark.asyncio
async def test_elapsed_budget_cancels_a_read_still_running() -> None:
    class Hanging:
        async def read_events_page(self, **_):
            await asyncio.sleep(30)

    request = NetworkIncidentRequest(**WINDOW, max_elapsed_ms=50)
    evidence = await collect_network_incident_evidence(Hanging(), request, now=_fixed_now)
    assert_contract_valid(evidence)
    (source,) = evidence.sources
    assert evidence.budgets.exhausted == (BudgetKind.ELAPSED,)
    assert source.outcome is SourceOutcome.NOT_ATTEMPTED
    assert source.failure.kind is FailureKind.BUDGET_EXHAUSTED
    assert evidence.overall is OverallStatus.FAILED


@pytest.mark.asyncio
async def test_window_budget_reads_nothing_and_names_itself() -> None:
    log, evidence = await _network(max_window_seconds=600)
    assert_contract_valid(evidence)
    assert log.reads == []
    assert evidence.budgets.exhausted == (BudgetKind.WINDOW,)
    assert evidence.sources[0].outcome is SourceOutcome.NOT_ATTEMPTED
    assert evidence.overall is OverallStatus.FAILED


@pytest.mark.asyncio
async def test_a_budget_spent_on_one_camera_leaves_later_cameras_not_attempted() -> None:
    log = ProtectLog(250)
    request = ProtectIncidentRequest(**WINDOW, camera_ids=["cam-b", "cam-a"], max_calls=2)
    evidence = await collect_protect_incident_evidence(log, request, now=_fixed_now)
    assert_contract_valid(evidence)
    assert [read[0] for read in log.reads] == ["cam-a", "cam-a"]
    first, second = evidence.sources
    assert first.coverage.filters == {"camera_id": "cam-a"}
    assert first.outcome is SourceOutcome.PARTIAL and second.outcome is SourceOutcome.NOT_ATTEMPTED
    assert second.coverage.filters == {"camera_id": "cam-b"}
    assert evidence.budgets.exhausted == (BudgetKind.CALLS,)


@pytest.mark.asyncio
async def test_meter_reports_every_spent_budget_and_never_under_its_limit() -> None:
    meter = BudgetMeter(BudgetLimits(window_seconds=60, events=1, calls=1, elapsed_ms=10_000), clock=lambda: 0.0)
    meter.events, meter.calls = 1, 1
    assert meter.blocking() is BudgetKind.CALLS
    budgets = meter.budgets(window_exhausted=False)
    assert budgets.exhausted == (BudgetKind.CALLS, BudgetKind.EVENTS)


# --- reading pages -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_moving_totals_between_reads_withdraw_the_end_claim() -> None:
    totals = iter([150, 151])

    async def read(offset, limit):
        rows = [{"id": str(offset + i)} for i in range(min(limit, 150 - offset))]
        return SourcePage(rows=rows, total_reported=next(totals), offset=offset, cap=limit, api_path="v2")

    meter = BudgetMeter(BudgetLimits(window_seconds=60, events=1000, calls=10, elapsed_ms=10_000))
    result = await read_source_pages(read, meter, page_size=100)
    assert result.page.has_more is None and result.page.total_reported is None


@pytest.mark.asyncio
async def test_a_failed_later_read_keeps_earlier_rows_as_a_partial_response() -> None:
    log = NetworkLog(250)
    original = log.read_events_page

    async def flaky(*, within, limit, offset=0, window_ms=None):
        if offset:
            raise TimeoutError("controller text that must not travel")
        return await original(within=within, limit=limit, offset=offset, window_ms=window_ms)

    log.read_events_page = flaky
    evidence = await collect_network_incident_evidence(log, NetworkIncidentRequest(**WINDOW), now=_fixed_now)
    payload = assert_contract_valid(evidence)
    (source,) = evidence.sources
    assert source.outcome is SourceOutcome.PARTIAL
    assert source.failure.kind is FailureKind.TIMEOUT
    assert "partial_response" in [r.value for r in source.partial_reasons]
    assert "controller text" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_device_filter_keeps_exact_matches_and_still_proves_the_end() -> None:
    log = NetworkLog(40)
    request = NetworkIncidentRequest(**WINDOW, device_macs=[DEVICE.upper()])
    evidence = await collect_network_incident_evidence(log, request, now=_fixed_now)
    assert_contract_valid(evidence)
    (source,) = evidence.sources
    assert source.coverage.filters["device_macs"] == (DEVICE,)
    assert source.coverage.pagination.post_filtered is True
    assert source.coverage.counts.received == 20
    assert source.outcome is SourceOutcome.COMPLETE
    assert all(DEVICE in {e.id for e in record.entities} for record in evidence.records)
    assert evidence.budgets.usage.events == 40


@pytest.mark.asyncio
async def test_device_filter_without_proof_of_the_end_is_visibly_post_filtered() -> None:
    request = NetworkIncidentRequest(**WINDOW, device_macs=[DEVICE], max_events=100)
    evidence = await collect_network_incident_evidence(NetworkLog(250), request, now=_fixed_now)
    assert_contract_valid(evidence)
    reasons = [r.value for r in evidence.sources[0].partial_reasons]
    assert "budget_exhausted" in reasons and "truncation_unknown" in reasons and "post_filtered" in reasons


# --- combining -----------------------------------------------------------------------------


def _assertion(mac: str, camera: str) -> MappingAssertion:
    return MappingAssertion(
        entity=EntityRef(kind=EntityKind.NETWORK_DEVICE, id_kind=IdKind.MAC, id=mac),
        target=EntityRef(kind=EntityKind.CAMERA, id_kind=IdKind.PROTECT_CAMERA_ID, id=camera),
        source=MappingSource.OPERATOR_INPUT,
    )


async def _documents():
    network = await collect_network_incident_evidence(
        NetworkLog(250),
        NetworkIncidentRequest(**WINDOW, max_events=150, mappings=[_assertion(DEVICE, CAMERA)]),
        now=_fixed_now,
    )
    protect = await collect_protect_incident_evidence(
        ProtectLog(20), ProtectIncidentRequest(**WINDOW, camera_ids=[CAMERA]), now=_fixed_now
    )

    class Down:
        async def list_events_raw_page(self, **_):
            raise PermissionError("denied")

    denied = await collect_protect_incident_evidence(Down(), ProtectIncidentRequest(**WINDOW), now=_fixed_now)
    return network, protect, denied


@pytest.mark.asyncio
async def test_combine_is_order_independent_and_keeps_every_source_status() -> None:
    documents = await _documents()
    outputs = {
        json.dumps(evidence_to_json(combine_incident_evidence(order)), sort_keys=True)
        for order in itertools.permutations(documents)
    }
    assert len(outputs) == 1
    combined = combine_incident_evidence(documents)
    assert_contract_valid(combined)
    statuses = {source.source_id: source.outcome for source in combined.sources}
    assert statuses == {
        "network.events": SourceOutcome.PARTIAL,
        "protect.events": SourceOutcome.PERMISSION_DENIED,
        "protect.events.camera.01": SourceOutcome.COMPLETE,
    }
    originals = {source.source_id: source for doc in documents for source in doc.sources}
    assert {source.source_id: source for source in combined.sources} == originals
    assert combined.overall is OverallStatus.PARTIAL


@pytest.mark.asyncio
async def test_combine_resolves_every_record_against_the_union_of_assertions() -> None:
    network, protect, _ = await _documents()
    combined = combine_incident_evidence([protect, network])
    mapped = [r for r in combined.records if r.source_id == "network.events" and DEVICE in {e.id for e in r.entities}]
    assert mapped and all(r.mapping.status is MappingStatus.VERIFIED for r in mapped)
    protect_records = [r for r in combined.records if r.source_id.startswith("protect")]
    assert protect_records and all(r.mapping.status is MappingStatus.MISSING for r in protect_records)


@pytest.mark.asyncio
async def test_combined_budgets_add_up_and_never_hide_an_exhausted_budget() -> None:
    network, protect, _ = await _documents()
    assert network.budgets.exhausted == (BudgetKind.EVENTS,) and protect.budgets.exhausted == ()
    for combined in (combine_incident_evidence([network, protect]), combine_incident_evidence([protect, network])):
        assert_contract_valid(combined)
        assert combined.budgets.limits.events == 150 + 1_000
        assert combined.budgets.usage.events == network.budgets.usage.events + protect.budgets.usage.events
        # Protect's unused share does not undo the Network collection running out of events.
        assert combined.budgets.usage.events < combined.budgets.limits.events
        assert combined.budgets.exhausted == (BudgetKind.EVENTS,)
        assert combined.overall is OverallStatus.PARTIAL and combined.coverage_complete is False


@pytest.mark.asyncio
async def test_combined_exhaustion_is_the_union_of_every_set() -> None:
    _, protect, _ = await _documents()
    calls = await collect_network_incident_evidence(
        NetworkLog(250), NetworkIncidentRequest(**WINDOW, max_calls=1), now=_fixed_now
    )
    window = await collect_protect_incident_evidence(
        ProtectLog(3), ProtectIncidentRequest(**WINDOW, max_window_seconds=600), now=_fixed_now
    )
    combined = combine_incident_evidence([protect, window, calls])
    assert_contract_valid(combined)
    assert combined.budgets.exhausted == (BudgetKind.CALLS, BudgetKind.WINDOW)


@pytest.mark.asyncio
async def test_combine_rejects_conflicting_sets() -> None:
    network, protect, _ = await _documents()
    other = await collect_network_incident_evidence(NetworkLog(3), NetworkIncidentRequest(**WINDOW), now=_fixed_now)
    with pytest.raises(ValueError, match="disagree"):
        combine_incident_evidence([network, other])
    shifted = await collect_protect_incident_evidence(
        ProtectLog(3),
        ProtectIncidentRequest(start="2026-08-08T11:00:00Z", end=WINDOW["end"]),
        now=_fixed_now,
    )
    with pytest.raises(ValueError, match="same requested window"):
        combine_incident_evidence([protect, shifted])
    with pytest.raises(ValueError):
        combine_incident_evidence([])


@pytest.mark.asyncio
async def test_combining_one_set_with_itself_changes_nothing() -> None:
    network, _, _ = await _documents()
    assert combine_incident_evidence([network, network]) == network


@pytest.mark.parametrize("path", sorted((SCHEMA_PATH.parent / "cases").glob("*.json")), ids=lambda p: p.stem)
def test_egress_redaction_has_nothing_to_remove_from_evidence(path) -> None:
    """Adapters return evidence unchanged: the contract already excludes every secret-like key."""
    from unifi_core.redaction import redact_sensitive_fields

    expected = json.loads(path.read_text())["expected"]
    assert redact_sensitive_fields(expected, redact_sensitive=True) == expected


# --- shared retry: never retries a budget refusal, never logs exception text -----------------


@pytest.mark.asyncio
async def test_retry_logs_only_the_class_and_never_retries_a_budget_refusal(caplog) -> None:
    from unifi_core.request_budget import RequestBudgetSpent
    from unifi_core.retry import RetryPolicy, retry_with_backoff

    attempts: list[str] = []

    async def failing() -> None:
        attempts.append("x")
        raise RuntimeError("fixture-private-controller-text")

    policy = RetryPolicy(max_retries=2, base_delay=0, retryable_exceptions=(Exception,))
    with caplog.at_level("DEBUG"), pytest.raises(RuntimeError):
        await retry_with_backoff(failing, policy=policy)
    assert len(attempts) == 3
    assert "fixture-private-controller-text" not in caplog.text and "RuntimeError" in caplog.text

    async def refused() -> None:
        attempts.append("refused")
        raise RequestBudgetSpent("call budget spent")

    with pytest.raises(RequestBudgetSpent):
        await retry_with_backoff(refused, policy=policy)
    assert attempts.count("refused") == 1


@pytest.mark.asyncio
async def test_a_charge_reaches_only_the_task_that_installed_it() -> None:
    from unifi_core.request_budget import charge_request, charging_requests, create_uncharged_task

    charged: list[str] = []

    async def background(label: str) -> None:
        charge_request()
        charged.append(f"{label} ran")

    with charging_requests(lambda: charged.append("charged")):
        charge_request()
        await asyncio.create_task(background("inherited"))  # copies the context, is never charged
        await create_uncharged_task(background("uncharged"))  # starts with no charge at all
    assert charged == ["charged", "inherited ran", "uncharged ran"]
