"""Protect incident collection through uiprotect's real decoding: statuses, budgets and read-only reads."""

from __future__ import annotations

import json

import jsonschema
import pytest
from uiprotect.exceptions import NotAuthorized, NvrError
from unifi_core.incident_evidence import (
    BudgetKind,
    OverallStatus,
    SourceOutcome,
    TimeStatus,
    WindowCoverage,
    evidence_to_json,
    parse_utc,
    validate_incident_evidence,
)
from unifi_core.protect.incident_collection import READ_METHODS, collect_protect_incident_evidence
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest

from ..incident_evidence_corpus import CORPUS_DIR, SCHEMA_PATH
from .sdk_transport import sdk_protect_event_manager

RESPONSES = json.loads((CORPUS_DIR / "collection" / "controller_responses.json").read_text())
NOW = parse_utc(RESPONSES["now"])
REQUEST = RESPONSES["request"]
PRIVATE = "fixture-private-controller-text"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
URL = "https://controller.invalid/proxy/protect/api/events"


def _status_error(cls, status: int):
    return cls(f"Request failed: {URL} - Status: {status} - Reason: {PRIVATE}")


def _body(response):
    if isinstance(response, dict) and "raise" in response:
        return {
            "auth_failure": lambda: _status_error(NotAuthorized, 401),
            "permission_denied": lambda: _status_error(NotAuthorized, 403),
            "timeout": lambda: TimeoutError(),
            "unavailable": lambda: _status_error(NvrError, 503),
        }[response["raise"]]()
    return response


def manager_for(scenario: str):
    return sdk_protect_event_manager(*[_body(r) for r in RESPONSES["protect"][scenario]["responses"]])


async def collect(manager, **arguments):
    request = ProtectIncidentRequest(**{**REQUEST, **arguments})
    return await collect_protect_incident_evidence(manager, request, now=lambda: NOW)


def contract_json(evidence) -> dict:
    payload = evidence_to_json(evidence)
    jsonschema.validate(payload, SCHEMA)
    assert validate_incident_evidence(payload) == evidence
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", sorted(RESPONSES["protect"]))
async def test_each_nvr_answer_keeps_its_source_status(scenario) -> None:
    evidence = await collect(manager_for(scenario))
    payload = contract_json(evidence)
    (source,) = evidence.sources
    assert source.outcome.value == RESPONSES["protect"][scenario]["outcome"]
    assert source.scope.location_id == "fixture-location-a"
    assert PRIVATE not in json.dumps(payload)
    if source.outcome not in (SourceOutcome.COMPLETE, SourceOutcome.EMPTY):
        assert evidence.overall is OverallStatus.FAILED and source.failure is not None


@pytest.mark.asyncio
async def test_the_exact_window_is_read_and_events_starting_before_it_stay_out_of_it() -> None:
    manager = manager_for("events")
    evidence = await collect(manager)
    params = manager.sent_requests[0]["params"]
    window = evidence.requested_window
    assert params["start"] == int(parse_utc(window.start).timestamp() * 1000)
    assert params["end"] == int(parse_utc(window.end).timestamp() * 1000)
    (source,) = evidence.sources
    assert source.coverage.window_coverage is WindowCoverage.COVERED
    statuses = {record.provenance.source_record_id: record.time.status for record in evidence.records}
    assert statuses["evt-protect-raw-0003"] is TimeStatus.OUT_OF_WINDOW
    assert all("recognized" not in json.dumps(record.attributes) for record in evidence.records)


@pytest.mark.asyncio
async def test_cameras_are_read_as_separate_sources_with_exact_filters() -> None:
    manager = sdk_protect_event_manager([], [])
    evidence = await collect(manager, camera_ids=["cam-fixture-000b", "cam-fixture-000a"])
    contract_json(evidence)
    assert [request["params"]["cameras"] for request in manager.sent_requests] == [
        ["cam-fixture-000a"],
        ["cam-fixture-000b"],
    ]
    assert [(s.source_id, s.coverage.filters) for s in evidence.sources] == [
        ("protect.events.camera.01", {"camera_id": "cam-fixture-000a"}),
        ("protect.events.camera.02", {"camera_id": "cam-fixture-000b"}),
    ]


@pytest.mark.asyncio
async def test_offsets_page_through_a_full_window_until_a_short_page() -> None:
    start = int(parse_utc(REQUEST["start"].replace("Z", ".000000Z")).timestamp() * 1000)
    rows = [{"id": f"evt-{i}", "type": "motion", "camera": "cam-fixture-000a", "start": start + i} for i in range(130)]
    manager = sdk_protect_event_manager(rows[:100], rows[100:])
    evidence = await collect(manager)
    contract_json(evidence)
    assert [request["params"]["offset"] for request in manager.sent_requests] == [0, 100]
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE


@pytest.mark.asyncio
async def test_a_full_last_page_under_a_spent_budget_is_partial() -> None:
    start = int(parse_utc("2026-08-08T12:00:00.000000Z").timestamp() * 1000)
    rows = [{"id": f"evt-{i}", "type": "motion", "camera": "cam-fixture-000a", "start": start + i} for i in range(100)]
    evidence = await collect(sdk_protect_event_manager(rows), max_calls=1)
    contract_json(evidence)
    (source,) = evidence.sources
    assert evidence.budgets.exhausted == (BudgetKind.CALLS,)
    assert [r.value for r in source.partial_reasons] == ["budget_exhausted", "truncation_unknown"]


@pytest.mark.asyncio
async def test_only_gets_reach_the_nvr() -> None:
    manager = sdk_protect_event_manager([], [])
    await collect(manager, camera_ids=["cam-fixture-000a", "cam-fixture-000b"])
    assert {request["method"] for request in manager.sent_requests} == {"get"}
    assert {request["url"] for request in manager.sent_requests} == {"events"}


class ReadOnlyView:
    def __init__(self, target, allowed: frozenset[str]) -> None:
        self._target, self._allowed = target, allowed

    def __getattr__(self, name: str):
        if name not in self._allowed:
            raise AssertionError(f"incident collection called {name}, which is not a read method")
        return getattr(self._target, name)


@pytest.mark.asyncio
async def test_collector_calls_nothing_but_read_methods() -> None:
    assert READ_METHODS == frozenset({"list_events_raw_page"})
    evidence = await collect(ReadOnlyView(manager_for("events"), READ_METHODS))
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE


@pytest.mark.asyncio
async def test_raw_reads_never_enrich_with_known_faces() -> None:
    row = {"id": "e1", "type": "smartDetectZone", "camera": "cam-fixture-000a", "start": 1786191000000}
    manager = sdk_protect_event_manager([dict(row, metadata={"detectedThumbnails": [{"group": {"id": "g1"}}]})])
    await collect(manager)
    assert [request["url"] for request in manager.sent_requests] == ["events"]
