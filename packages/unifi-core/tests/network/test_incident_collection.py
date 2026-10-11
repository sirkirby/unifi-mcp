"""Network incident collection through aiounifi's real decoding: statuses, budgets and read-only reads."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from unittest.mock import patch

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
from .sdk_transport import sdk_event_manager

RESPONSES = json.loads((CORPUS_DIR / "collection" / "controller_responses.json").read_text())
NOW = parse_utc(RESPONSES["now"])
REQUEST = RESPONSES["request"]
PRIVATE = "fixture-private-controller-text"
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


@pytest.mark.asyncio
async def test_pages_follow_the_controller_until_its_total_is_reached() -> None:
    rows = [{"id": f"evt-{i}", "key": "K", "timestamp": int(NOW.timestamp() * 1000) - 600_000 - i} for i in range(230)]
    pages = [{"data": rows[i : i + 100], "total_element_count": 230} for i in range(0, 230, 100)]
    manager = sdk_event_manager(*pages)
    evidence = await collect(manager)
    contract_json(evidence)
    assert [request.data["pageNumber"] for request in manager.sent_requests] == [0, 1, 2]
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE
    assert evidence.budgets.usage.calls == 3 and evidence.budgets.usage.events == 230


@pytest.mark.asyncio
async def test_a_spent_budget_leaves_the_truncation_visible() -> None:
    rows = [{"id": f"evt-{i}", "key": "K", "timestamp": int(NOW.timestamp() * 1000) - 600_000 - i} for i in range(230)]
    manager = sdk_event_manager(*[{"data": rows[i : i + 100], "total_element_count": 230} for i in range(0, 230, 100)])
    evidence = await collect(manager, max_events=150)
    contract_json(evidence)
    (source,) = evidence.sources
    assert evidence.budgets.exhausted == (BudgetKind.EVENTS,)
    assert source.coverage.truncation is Truncation.TRUNCATED
    assert source.coverage.pagination.total_reported == 230 and source.coverage.pagination.returned == 150
    assert [r.value for r in source.partial_reasons] == ["budget_exhausted", "truncated"]


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
    assert READ_METHODS == frozenset({"get_events_page"})
    evidence = await collect(ReadOnlyView(manager_for("events"), READ_METHODS))
    assert evidence.sources[0].outcome is SourceOutcome.COMPLETE


def test_window_bounds_are_parsed_as_given() -> None:
    request = NetworkIncidentRequest(start="2026-08-08T08:00:00-04:00", end="2026-08-08T13:00:00Z")
    assert parse_utc(request.window.start) == datetime.fromisoformat("2026-08-08T12:00:00+00:00")
