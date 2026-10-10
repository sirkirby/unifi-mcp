"""EventManager pages through the SDK's real decoding: envelopes, malformed rows, totals, safe errors."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from unifi_core.exceptions import UniFiMalformedResponseError, UniFiPermissionError
from unifi_core.incident_evidence import (
    BudgetLimits,
    Budgets,
    FailureKind,
    OverallStatus,
    PartialReason,
    SourceOutcome,
    TimeWindow,
    Truncation,
    assemble_incident_evidence,
    failure_from_exception,
)
from unifi_core.network.incident_evidence import (
    network_alarms_context,
    network_events_context,
    normalize_network_page,
)

from ..sdk_transport import sdk_event_manager

UTC = timezone.utc
NOW = datetime(2026, 8, 8, 13, 4, tzinfo=UTC)
WINDOW = TimeWindow.from_datetimes(NOW - timedelta(hours=1), NOW - timedelta(minutes=4))
BUDGETS = Budgets(limits=BudgetLimits(window_seconds=7200, events=5000, calls=10, elapsed_ms=60_000))
PRIVATE = "fixture-private-controller-text"
VALID = {"id": "fixture-valid", "key": "K", "timestamp": int((NOW - timedelta(minutes=30)).timestamp() * 1000)}


async def _events_page(*bodies, v2=True, **kwargs):
    manager = sdk_event_manager(*bodies, v2=v2)
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()):
        page = await manager.get_events_page(within=2, **kwargs)
    return manager, page


def _events_evidence(page, *, limit=100):
    context = network_events_context(
        requested_window=WINDOW,
        request_started_at=NOW,
        collected_at=NOW + timedelta(seconds=1),
        within_hours=2,
        limit=limit,
        page=page,
    )
    source = normalize_network_page(page, context)
    return source, assemble_incident_evidence(requested_window=WINDOW, budgets=BUDGETS, sources=[source])


# --- item 1: SDK-wrapped envelopes and malformed rows -------------------------


@pytest.mark.asyncio
async def test_sdk_wrapped_logs_envelope_is_a_valid_empty_collection() -> None:
    _, page = await _events_page({"logs": [], "total_page_count": 0})
    assert page.rows == [] and page.has_more is False
    source, evidence = _events_evidence(page)
    assert source.source.outcome is SourceOutcome.EMPTY
    assert evidence.overall is OverallStatus.EMPTY


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{"unexpected": PRIVATE}, {"data": PRIVATE}, {"logs": {"x": PRIVATE}}, [VALID]])
async def test_sdk_wrapped_unreadable_envelopes_raise_fixed_text(body) -> None:
    manager = sdk_event_manager(body)
    with pytest.raises(UniFiMalformedResponseError) as error:
        await manager.get_events_page(limit=10)
    assert PRIVATE not in str(error.value)
    with pytest.raises(UniFiMalformedResponseError):
        await sdk_event_manager(body).get_alarms_page(limit=10)
    assert failure_from_exception(error.value).kind is FailureKind.PARSE_FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[PRIVATE], [None, VALID], [VALID, 7]])
async def test_malformed_rows_survive_the_manager_boundary(rows) -> None:
    _, page = await _events_page({"data": rows})
    assert page.rows == rows and page.malformed == 1
    source, evidence = _events_evidence(page)
    assert source.source.coverage.counts.malformed_dropped == page.malformed > 0
    assert PartialReason.MALFORMED_RECORDS in source.source.partial_reasons
    assert evidence.overall is OverallStatus.PARTIAL


@pytest.mark.asyncio
async def test_list_callers_get_an_error_instead_of_a_silently_dropped_row() -> None:
    manager = sdk_event_manager({"data": [None, VALID]})
    with pytest.raises(UniFiMalformedResponseError, match="Unreadable rows"):
        await manager.get_events(limit=10)
    with pytest.raises(UniFiMalformedResponseError, match="Unreadable rows"):
        await sdk_event_manager({"data": [PRIVATE]}).get_alarms(limit=10)


@pytest.mark.asyncio
async def test_valid_rows_still_list_normally() -> None:
    assert await sdk_event_manager({"data": [VALID]}).get_events(limit=10) == [VALID]
    assert await sdk_event_manager({"meta": {"rc": "ok"}, "data": [VALID]}, v2=False).get_events(limit=10) == [VALID]


# --- item 2: remote totals and continuation state ------------------------------


@pytest.mark.asyncio
async def test_alarm_remote_total_beyond_the_page_is_truncation() -> None:
    manager = sdk_event_manager({"data": [VALID], "total_element_count": 25, "total_page_count": 2})
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=NOW.timestamp()):
        page = await manager.get_alarms_page(limit=99)
    assert page.total_reported == 25 and page.has_more is None
    context = network_alarms_context(requested_window=WINDOW, collected_at=NOW, limit=99, page=page)
    source = normalize_network_page(page, context).source
    assert source.coverage.truncation is Truncation.TRUNCATED
    assert source.outcome is SourceOutcome.PARTIAL and source.coverage.population_total is None


@pytest.mark.asyncio
async def test_empty_event_page_reporting_a_remote_total_is_not_empty() -> None:
    _, page = await _events_page({"data": [], "total_element_count": 25, "total_page_count": 1}, limit=99)
    source, evidence = _events_evidence(page, limit=99)
    assert source.source.coverage.truncation is Truncation.TRUNCATED
    assert evidence.overall is OverallStatus.PARTIAL


@pytest.mark.asyncio
async def test_rows_beyond_the_limit_mean_more_exist() -> None:
    rows = [dict(VALID, id=f"fixture-{i}") for i in range(5)]
    _, page = await _events_page({"data": rows}, limit=3)
    assert len(page.rows) == 3 and page.has_more is True


@pytest.mark.asyncio
async def test_full_page_without_total_is_unknown() -> None:
    rows = [dict(VALID, id=f"fixture-{i}") for i in range(3)]
    _, page = await _events_page({"data": rows}, limit=3)
    assert page.has_more is None
    source, _ = _events_evidence(page, limit=3)
    assert source.source.coverage.truncation is Truncation.UNKNOWN


@pytest.mark.asyncio
async def test_legacy_short_page_against_the_sent_limit_proves_the_end() -> None:
    _, page = await _events_page({"meta": {"rc": "ok"}, "data": [VALID]}, v2=False, limit=5000)
    assert page.cap == 3000 and page.has_more is False and page.api_path == "legacy"
    _, full = await _events_page({"meta": {"rc": "ok"}, "data": [VALID] * 3000}, v2=False, limit=5000)
    assert full.has_more is None


@pytest.mark.asyncio
async def test_legacy_alarms_report_their_whole_population() -> None:
    manager = sdk_event_manager({"meta": {"rc": "ok"}, "data": [dict(VALID, id=f"a{i}") for i in range(7)]}, v2=False)
    page = await manager.get_alarms_page(limit=5)
    assert len(page.rows) == 5 and page.total_reported == 7 and page.has_more is True


# --- item 6: submitted bounds, millisecond precision -----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("micros", [0, 500, 999])
async def test_v2_queried_window_is_the_submitted_millisecond_window(micros) -> None:
    request = NOW.replace(microsecond=micros)
    manager = sdk_event_manager({"data": []})
    with patch("unifi_core.network.managers.event_manager.time.time", return_value=request.timestamp()):
        page = await manager.get_events_page(within=2, limit=100)
    sent = manager.sent_requests[0].data
    window = TimeWindow.from_datetimes(NOW - timedelta(hours=1), request)
    context = network_events_context(
        requested_window=window, request_started_at=request, collected_at=request, within_hours=2, page=page
    )
    assert page.submitted_window_ms == (sent["timestampFrom"], sent["timestampTo"])
    assert context.queried_window.end == "2026-08-08T13:04:00.000000Z"
    source = normalize_network_page(page, context).source
    expected = SourceOutcome.EMPTY if micros == 0 else SourceOutcome.PARTIAL
    assert source.outcome is expected


def test_bracket_window_floors_the_request_start_to_milliseconds() -> None:
    request = NOW.replace(microsecond=500)
    context = network_events_context(
        requested_window=WINDOW, request_started_at=request, collected_at=request, within_hours=2
    )
    assert context.queried_window.end == "2026-08-08T13:04:00.000000Z"


# --- item 4: controller text never leaves the manager -----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get_events", "get_alarms", "get_events_page", "get_alarms_page"])
async def test_legacy_rejection_text_stays_inside_the_manager(method, caplog) -> None:
    body = {"meta": {"rc": "error", "msg": "api.err.FixtureFailure", "detail": PRIVATE}, "data": []}
    manager = sdk_event_manager(body, v2=False)
    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as error:
        await getattr(manager, method)()
    assert PRIVATE not in str(error.value)
    assert "FixtureFailure" not in str(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert PRIVATE not in caplog.text and "FixtureFailure" not in caplog.text
    assert str(error.value).endswith("failed (AiounifiException).")


@pytest.mark.asyncio
async def test_translated_errors_keep_their_category() -> None:
    body = {"meta": {"rc": "error", "msg": "api.err.NoPermission", "detail": PRIVATE}, "data": []}
    manager = sdk_event_manager(body, v2=False)
    with pytest.raises(UniFiPermissionError) as error:
        await manager.get_events()
    assert PRIVATE not in str(error.value)
    assert failure_from_exception(error.value).kind is FailureKind.PERMISSION_DENIED


@pytest.mark.asyncio
async def test_v2_error_code_body_is_translated_with_its_status() -> None:
    manager = sdk_event_manager({"errorCode": 404, "message": PRIVATE})
    with pytest.raises(Exception) as error:
        await manager.get_events()
    assert PRIVATE not in str(error.value)
    assert failure_from_exception(error.value).kind is FailureKind.UNSUPPORTED
