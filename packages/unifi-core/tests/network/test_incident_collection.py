"""Network incident collection through aiounifi's real decoding: statuses, budgets and read-only reads."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import aiohttp
import jsonschema
import pytest
from unifi_core.incident_evidence import (
    BudgetKind,
    OverallStatus,
    SourceOutcome,
    Truncation,
    evidence_to_json,
    parse_utc,
    validate_incident_evidence,
)
from unifi_core.network.incident_collection import READ_METHODS, collect_network_incident_evidence
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest

from ..incident_evidence_corpus import CORPUS_DIR, SCHEMA_PATH
from .sdk_transport import paging_event_manager, sdk_event_manager

RESPONSES = json.loads((CORPUS_DIR / "collection" / "controller_responses.json").read_text())
NOW = parse_utc(RESPONSES["now"])
REQUEST = RESPONSES["request"]
PRIVATE = "fixture-private-controller-text"
DEVICE = "02:00:00:00:00:0a"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

# Network event reads are POST queries by API design; these are the only ones
# the collector may send. Any other method or path is a mutation risk.
READ_QUERIES = frozenset({("post", "/system-log/count"), ("post", "/system-log/all"), ("post", "/stat/event")})


def _body(response):
    if isinstance(response, dict) and "raise" in response:
        return {"timeout": asyncio.TimeoutError(), "unavailable": aiohttp.ClientConnectionError(PRIVATE)}[
            response["raise"]
        ]
    return response


def manager_for(scenario: str, *, v2: bool | None = True):
    manager = sdk_event_manager(*[_body(r) for r in RESPONSES["network"][scenario]["responses"]], v2=bool(v2))
    if v2 is None:
        manager._use_v2 = None  # let the manager probe for the API version
    return manager


async def collect(manager, **arguments):
    request = NetworkIncidentRequest(**{**REQUEST, **arguments})
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()):
        return await collect_network_incident_evidence(manager, request, site="default", now=lambda: NOW)


def contract_json(evidence) -> dict:
    payload = evidence_to_json(evidence)
    jsonschema.validate(payload, SCHEMA)
    assert validate_incident_evidence(payload) == evidence
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(RESPONSES["network"]))
async def test_each_controller_answer_keeps_its_source_status(scenario) -> None:
    evidence = await collect(manager_for(scenario))
    payload = contract_json(evidence)
    (source,) = evidence.sources
    assert source.outcome.value == RESPONSES["network"][scenario]["outcome"]
    assert source.scope.site == "default" and source.scope.location_id == "fixture-location-a"
    assert PRIVATE not in json.dumps(payload)
    if source.outcome in (SourceOutcome.COMPLETE, SourceOutcome.EMPTY):
        assert evidence.coverage_complete is True
    else:
        assert evidence.overall is OverallStatus.FAILED and evidence.coverage_complete is False
        assert source.failure is not None and evidence.records == ()


@pytest.mark.asyncio
async def test_v2_reads_record_the_filters_the_controller_applied() -> None:
    manager = manager_for("events")
    evidence = await collect(manager)
    sent = manager.sent_requests[0]
    (source,) = evidence.sources
    assert source.coverage.filters["categories"] == tuple(sent.data["categories"])
    assert source.coverage.filters["severities"] == tuple(sent.data["severities"])
    assert source.coverage.queried_window.start <= evidence.requested_window.start
    assert len(evidence.records) == 3


def _rows(count: int, *, mac: str | None = None) -> list[dict]:
    stamp = int(NOW.timestamp() * 1000) - 600_000
    rows = [{"id": f"evt-{i}", "key": "K", "timestamp": stamp - i} for i in range(count)]
    if mac:
        for row in rows:
            row["mac"] = "02:00:00:00:00:0b"
    return rows


@pytest.mark.asyncio
async def test_pages_follow_the_controller_but_never_claim_its_end() -> None:
    manager = paging_event_manager(_rows(230))
    evidence = await collect(manager)
    contract_json(evidence)
    assert [request.data["pageNumber"] for request in manager.sent_requests] == [0, 1, 2]
    (source,) = evidence.sources
    assert source.outcome is SourceOutcome.PARTIAL
    assert [r.value for r in source.partial_reasons] == ["truncation_unknown"]
    assert evidence.budgets.usage.calls == 3 and evidence.budgets.usage.events == 230


@pytest.mark.asyncio
async def test_an_event_moving_across_an_offset_with_an_unchanged_total_is_no_all_clear() -> None:
    """The incident row is unseen on page one and moves ahead of the next offset; the total stays 230."""
    rows = _rows(230, mac="other")
    rows[130]["mac"] = DEVICE
    moved = [rows[130], *rows[:130], *rows[131:]]
    manager = paging_event_manager(lambda index: rows if index == 0 else moved)
    evidence = await collect(manager, device_macs=[DEVICE])
    contract_json(evidence)
    (source,) = evidence.sources
    assert evidence.records == ()  # the row was skipped by the offsets...
    assert source.outcome is SourceOutcome.PARTIAL  # ...so the empty result is never an all-clear
    assert evidence.overall is OverallStatus.PARTIAL and evidence.coverage_complete is False
    assert "truncation_unknown" in [r.value for r in source.partial_reasons]


@pytest.mark.asyncio
async def test_the_version_probe_is_a_charged_request() -> None:
    manager = paging_event_manager(_rows(30), v2=None)
    evidence = await collect(manager, max_calls=1)
    contract_json(evidence)
    assert [request.path for request in manager.sent_requests] == ["/system-log/count"]
    assert evidence.budgets.usage.calls == 1 and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    assert evidence.sources[0].outcome is SourceOutcome.NOT_ATTEMPTED
    with_room = paging_event_manager(_rows(30), v2=None)
    evidence = await collect(with_room, max_calls=2)
    assert len(with_room.sent_requests) == evidence.budgets.usage.calls == 2
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE


@pytest.mark.asyncio
async def test_every_request_and_every_fetched_row_is_charged_and_never_beyond_budget() -> None:
    manager = paging_event_manager(_rows(240))
    evidence = await collect(manager, max_calls=2, max_events=170)
    contract_json(evidence)
    sent = [(request.data["pageNumber"], request.data["pageSize"]) for request in manager.sent_requests]
    assert sent == [(0, 100), (2, 50)]  # the last read stays page-aligned and inside the events left
    assert evidence.budgets.usage.calls == len(sent) == 2
    assert evidence.budgets.usage.events == 150 == evidence.sources[0].coverage.counts.received
    assert evidence.budgets.exhausted == (BudgetKind.CALLS,)


@pytest.mark.asyncio
async def test_a_spent_budget_leaves_the_missing_tail_visible() -> None:
    evidence = await collect(paging_event_manager(_rows(230)), max_events=150)
    contract_json(evidence)
    (source,) = evidence.sources
    assert evidence.budgets.exhausted == (BudgetKind.EVENTS,) and evidence.budgets.usage.events == 150
    assert source.coverage.truncation is Truncation.UNKNOWN and source.coverage.pagination.returned == 150
    assert [r.value for r in source.partial_reasons] == ["budget_exhausted", "truncation_unknown"]


@pytest.mark.asyncio
async def test_the_retry_after_a_relogin_is_charged() -> None:
    from aiounifi.errors import LoginRequired

    manager = sdk_event_manager(LoginRequired("fixture"), {"data": [], "total_element_count": 0})
    manager._connection._reauthenticate = AsyncMock(return_value=True)
    evidence = await collect(manager, max_calls=1)
    assert len(manager.sent_requests) == 1 and evidence.budgets.exhausted == (BudgetKind.CALLS,)
    assert evidence.sources[0].outcome is SourceOutcome.NOT_ATTEMPTED
    manager = sdk_event_manager(LoginRequired("fixture"), {"data": [], "total_element_count": 0})
    manager._connection._reauthenticate = AsyncMock(return_value=True)
    evidence = await collect(manager, max_calls=2)
    assert len(manager.sent_requests) == evidence.budgets.usage.calls == 2
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


@pytest.mark.asyncio
@pytest.mark.parametrize("v2", [True, False, None])
async def test_only_read_queries_reach_the_controller(v2) -> None:
    responses = [{"data": [], "total_element_count": 0}] if v2 is not False else [{"meta": {"rc": "ok"}, "data": []}]
    manager = sdk_event_manager(*responses, v2=bool(v2))
    if v2 is None:
        manager._use_v2 = None
    evidence = await collect(manager)
    sent = {(request.method.lower(), request.path) for request in manager.sent_requests}
    assert sent and sent <= READ_QUERIES
    assert evidence.sources[0].outcome is SourceOutcome.EMPTY


class ReadOnlyView:
    """Exposes only the manager methods a collector is allowed to call."""

    def __init__(self, target, allowed: frozenset[str]) -> None:
        self._target, self._allowed = target, allowed

    def __getattr__(self, name: str):
        if name not in self._allowed:
            raise AssertionError(f"incident collection called {name}, which is not a read method")
        return getattr(self._target, name)


@pytest.mark.asyncio
async def test_collector_calls_nothing_but_read_methods() -> None:
    assert READ_METHODS == frozenset({"read_events_page"})
    evidence = await collect(ReadOnlyView(manager_for("events"), READ_METHODS))
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE


def test_window_bounds_are_parsed_as_given() -> None:
    request = NetworkIncidentRequest(start="2026-08-08T08:00:00-04:00", end="2026-08-08T13:00:00Z")
    assert parse_utc(request.window.start) == datetime.fromisoformat("2026-08-08T12:00:00+00:00")


# --- absolute window bounds on the v2 path -------------------------------------------------


def _ms(value: str) -> int:
    return int(parse_utc(value).timestamp() * 1000)


@pytest.mark.asyncio
async def test_a_quiet_window_on_a_busy_controller_is_one_page_and_complete() -> None:
    """5,000 events across the day, 12 of them in a quiet half hour: one request answers the whole window."""
    day = _ms("2026-08-08T00:00:00.000000Z")
    quiet_start, quiet_end = _ms("2026-08-08T09:00:00.000000Z"), _ms("2026-08-08T09:30:00.000000Z")
    busy = [{"id": f"busy-{i}", "key": "K", "timestamp": day + i * 9_000} for i in range(5_000)]
    rows = [row for row in busy if not quiet_start <= row["timestamp"] < quiet_end]
    rows += [{"id": f"quiet-{i}", "key": "K", "timestamp": quiet_start + i * 120_000} for i in range(12)]
    manager = paging_event_manager(rows)
    evidence = await collect(manager, start="2026-08-08T09:00:00Z", end="2026-08-08T09:30:00Z")
    contract_json(evidence)
    (source,) = evidence.sources
    assert len(manager.sent_requests) == evidence.budgets.usage.calls == 1
    assert source.outcome is SourceOutcome.COMPLETE and evidence.coverage_complete is True
    assert source.coverage.counts.in_window == source.coverage.population_total == 12
    # The busy event at exactly 09:30:00.000 comes back at the widened end and is placed out-of-window.
    assert source.coverage.counts.out_of_window == 1


@pytest.mark.asyncio
async def test_the_submitted_bounds_are_the_window_widened_by_one_boundary_millisecond() -> None:
    manager = paging_event_manager(_rows(3))
    window = {"start": "2026-08-08T12:00:00.000500Z", "end": "2026-08-08T12:59:59.999500Z"}
    evidence = await collect(manager, **window)
    sent = manager.sent_requests[0].data
    # floor(start) - 1 ms and ceil(end): every inclusive/exclusive reading still covers [start, end).
    assert (sent["timestampFrom"], sent["timestampTo"]) == (_ms(window["start"]) - 1, _ms(window["end"]) + 1)
    (source,) = evidence.sources
    assert source.coverage.queried_window.start == "2026-08-08T11:59:59.999000Z"
    assert source.coverage.queried_window.end == "2026-08-08T13:00:00.000000Z"
    assert source.coverage.window_coverage.value == "covered"
    assert source.query["timestamp_from_ms"] == sent["timestampFrom"]
    assert source.query["timestamp_to_ms"] == sent["timestampTo"]
    assert "within_hours" not in source.query


@pytest.mark.asyncio
async def test_events_a_controller_returns_at_the_widened_edges_are_out_of_window() -> None:
    start, end = _ms("2026-08-08T12:00:00.000000Z"), _ms("2026-08-08T13:00:00.000000Z")
    rows = [
        {"id": "before", "key": "K", "timestamp": start - 1},
        {"id": "first", "key": "K", "timestamp": start},
        {"id": "last", "key": "K", "timestamp": end - 1},
        {"id": "at-end", "key": "K", "timestamp": end},
    ]
    evidence = await collect(paging_event_manager(rows))
    contract_json(evidence)
    placement = {r.provenance.source_record_id: r.time.status.value for r in evidence.records}
    assert placement == {
        "before": "out_of_window",
        "first": "in_window",
        "last": "in_window",
        "at-end": "out_of_window",
    }
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE


@pytest.mark.asyncio
async def test_the_legacy_path_keeps_its_lookback() -> None:
    manager = sdk_event_manager({"meta": {"rc": "ok"}, "data": []}, v2=False)
    evidence = await collect(manager)
    sent = manager.sent_requests[0].data
    assert set(sent) == {"within", "_limit", "_start"} and sent["_limit"] == 100
    (source,) = evidence.sources
    assert source.query["within_hours"] == sent["within"] and "timestamp_from_ms" not in source.query
