"""Bounded, read-only Network incident evidence collection.

Reads the Network event log for one requested window through
``EventManager.read_events_page`` only, one request per page within the
request's budgets, and returns a validated evidence set with one
``network.events`` source.

The v2 log is asked for the window itself, as absolute millisecond bounds
(see :func:`submitted_bounds_ms`), so a quiet window on a busy controller can
be read in one page. The legacy log only takes a lookback relative to "now",
chosen to reach the window start even if every read takes the whole elapsed
budget; its rows newer than the window are read, counted against the events
budget and reported as out-of-window. Device filters are exact MACs applied
to the rows after reading; rows that cannot be read stay in so they are
counted as malformed.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from unifi_core.incident_collection import (
    BUDGET_EXHAUSTED,
    BudgetMeter,
    SourceRead,
    acquire_once,
    read_source_pages,
    utc_now,
)
from unifi_core.incident_evidence import (
    IdKind,
    IncidentEvidence,
    SourceEvidence,
    TimeWindow,
    assemble_incident_evidence,
    parse_utc,
    source_failed,
)
from unifi_core.network.incident_evidence import (
    extract_network_record,
    network_events_context,
    normalize_network_records,
)
from unifi_core.network.managers.event_manager import DEFAULT_EVENT_CATEGORIES, DEFAULT_EVENT_SEVERITIES
from unifi_core.network.models.incident_evidence import NetworkIncidentRequest
from unifi_core.source_page import SourcePage

NETWORK_EVENTS_SOURCE = "network.events"
# One v2 system-log page per read.
EVENTS_PAGE_SIZE = 100
# Slack for clock reads around a read cancelled at the elapsed deadline.
_LOOKBACK_MARGIN = timedelta(minutes=1)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

#: The only manager methods the collector calls.
READ_METHODS = frozenset({"read_events_page"})


class NetworkEventPages(Protocol):
    async def read_events_page(
        self, *, within: int, limit: int, offset: int = 0, window_ms: tuple[int, int] | None = None
    ) -> SourcePage: ...


def lookback_hours(window_start: datetime, planned_at: datetime, elapsed_ms: int) -> int:
    """Whole hours that reach ``window_start`` from any read inside the elapsed budget."""
    span = planned_at - window_start + timedelta(milliseconds=elapsed_ms) + _LOOKBACK_MARGIN
    return max(1, math.ceil(span.total_seconds() / 3600))


def submitted_bounds_ms(window: TimeWindow) -> tuple[int, int]:
    """The epoch-millisecond ``timestampFrom``/``timestampTo`` sent for a v2 read of ``window``.

    Whether the controller treats either bound as inclusive or exclusive is
    unverified, so the bounds are widened rather than narrowed: one
    millisecond before the window start (floored to milliseconds) and the
    window end rounded up. Under every interpretation the controller then
    returns all of ``[start, end)``; an event it returns at a widened edge
    is placed by its own timestamp, so it is reported out-of-window, never
    in it. Narrowing (``end - 1``) would instead lose the last millisecond
    while still claiming the window was covered.
    """
    start_us = (parse_utc(window.start) - _EPOCH) // timedelta(microseconds=1)
    end_us = (parse_utc(window.end) - _EPOCH) // timedelta(microseconds=1)
    return start_us // 1000 - 1, -(-end_us // 1000)


def _names_device(raw: Any, wanted: frozenset[str]) -> bool:
    if not isinstance(raw, Mapping):
        return True
    try:
        extracted = extract_network_record(raw)
    except (TypeError, ValueError):
        return True
    if extracted is None:
        return True
    return any(entity.id_kind is IdKind.MAC and entity.identity[1] in wanted for entity in extracted.entities)


def _filter_devices(page: SourcePage, device_macs: tuple[str, ...]) -> SourcePage:
    wanted = frozenset(device_macs)
    return SourcePage(
        rows=[row for row in page.rows if _names_device(row, wanted)],
        has_more=page.has_more,
        total_reported=page.total_reported,
        offset=page.offset,
        cap=page.cap,
        api_path=page.api_path,
        submitted_window_ms=page.submitted_window_ms,
        post_filtered=True,
    )


def _events_source(
    read: SourceRead | None,
    request: NetworkIncidentRequest,
    *,
    within: int,
    window_ms: tuple[int, int],
    site: str | None,
    now: datetime,
) -> SourceEvidence:
    page = read.page if read is not None else None
    if page is not None and request.device_macs:
        page = _filter_devices(page, request.device_macs)
    v2 = page is not None and page.api_path == "v2"
    context = network_events_context(
        requested_window=request.window,
        request_started_at=read.started_at if read is not None else now,
        collected_at=read.finished_at if read is not None else now,
        within_hours=within,
        limit=read.requested if read is not None else 0,
        start=0,
        # The v2 path applies these when none are named, so they qualify what was read.
        categories=DEFAULT_EVENT_CATEGORIES if v2 else None,
        severities=DEFAULT_EVENT_SEVERITIES if v2 else None,
        device_macs=request.device_macs or None,
        # v2 was sent the absolute bounds; legacy (and an unread source) the lookback.
        window_ms=window_ms if v2 else None,
        page=page,
        source_id=NETWORK_EVENTS_SOURCE,
        site=site,
        location_id=request.location_id,
    )
    if read is None or page is None:
        return source_failed(context, read.evidence_failure() if read is not None else BUDGET_EXHAUSTED)
    return normalize_network_records(page.rows, context, failure=read.failure, budget_exhausted=read.budget_stopped)


async def collect_network_incident_evidence(
    events: NetworkEventPages | Callable[[], Awaitable[NetworkEventPages]],
    request: NetworkIncidentRequest,
    *,
    site: str | None = None,
    clock: Callable[[], float] | None = None,
    now: Callable[[], datetime] = utc_now,
) -> IncidentEvidence:
    """Collect bounded Network event evidence for ``request``'s window.

    ``events`` is the Network ``EventManager`` (or anything with its
    ``read_events_page``), or an awaitable factory for one, acquired inside
    the first read; no other method is called. Source failures, budget
    exhaustion and truncation are reported in the evidence, never raised.
    """
    get_events = acquire_once(events, "read_events_page")
    meter = BudgetMeter(request.limits, clock=clock)
    planned_at = now()
    within = lookback_hours(parse_utc(request.window.start), planned_at, request.max_elapsed_ms)
    window_ms = submitted_bounds_ms(request.window)
    read = None
    if not request.window_exhausted:

        async def read_page(offset: int, limit: int) -> SourcePage:
            return await (await get_events()).read_events_page(
                within=within, limit=limit, offset=offset, window_ms=window_ms
            )

        # v2 pages by number, so every offset stays a whole number of pages.
        read = await read_source_pages(read_page, meter, page_size=EVENTS_PAGE_SIZE, aligned=True, now=now)
    meter.stop()
    source = _events_source(read, request, within=within, window_ms=window_ms, site=site, now=planned_at)
    return assemble_incident_evidence(
        requested_window=request.window,
        budgets=meter.budgets(window_exhausted=request.window_exhausted),
        sources=[source],
        mappings=request.mappings,
    )
