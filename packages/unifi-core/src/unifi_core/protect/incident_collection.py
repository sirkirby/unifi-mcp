"""Bounded, read-only Protect incident evidence collection.

Reads NVR events for one requested window through
``EventManager.list_events_raw_page`` only: the exact window bounds, a page
at a time by offset, within the request's budgets. Without camera IDs one
``protect.events`` source covers every camera; with them, each camera (in
ID order) is its own ``protect.events.camera.NN`` source filtered by the
NVR, and a camera the budget never reached is ``not_attempted``.
"""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from unifi_core.incident_collection import (
    BUDGET_EXHAUSTED,
    BudgetMeter,
    SourceRead,
    acquire_once,
    read_source_pages,
    utc_now,
)
from unifi_core.incident_evidence import (
    IncidentEvidence,
    SourceEvidence,
    assemble_incident_evidence,
    parse_utc,
    source_failed,
)
from unifi_core.protect.incident_evidence import normalize_protect_records, protect_events_context
from unifi_core.protect.models.incident_evidence import ProtectIncidentRequest
from unifi_core.source_page import SourcePage

PROTECT_EVENTS_SOURCE = "protect.events"
EVENTS_PAGE_SIZE = 100

#: The only manager methods the collector calls.
READ_METHODS = frozenset({"list_events_raw_page"})

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class ProtectEventPages(Protocol):
    async def list_events_raw_page(
        self,
        *,
        start: datetime,
        end: datetime,
        limit: int,
        offset: int = 0,
        camera_id: str | None = None,
    ) -> SourcePage: ...


def camera_source_id(index: int) -> str:
    return f"{PROTECT_EVENTS_SOURCE}.camera.{index:02d}"


def _millisecond_bounds(request: ProtectIncidentRequest) -> tuple[datetime, datetime]:
    """Whole-millisecond bounds that cover the requested window (the NVR takes epoch ms)."""
    window = request.window
    start_us = (parse_utc(window.start) - _EPOCH) // timedelta(microseconds=1)
    end_us = (parse_utc(window.end) - _EPOCH) // timedelta(microseconds=1)
    start = _EPOCH + timedelta(milliseconds=start_us // 1000)
    end = _EPOCH + timedelta(milliseconds=math.ceil(end_us / 1000))
    return start, end


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _source(
    read: SourceRead | None,
    request: ProtectIncidentRequest,
    *,
    source_id: str,
    camera_id: str | None,
    bounds: tuple[datetime, datetime],
    now: datetime,
) -> SourceEvidence:
    page = read.page if read is not None else None
    context = protect_events_context(
        requested_window=request.window,
        collected_at=read.finished_at if read is not None else now,
        start=_iso(bounds[0]),
        end=_iso(bounds[1]),
        limit=read.requested if read is not None else 0,
        camera_id=camera_id,
        page=page,
        source_id=source_id,
        location_id=request.location_id,
    )
    if read is None or page is None:
        return source_failed(context, read.evidence_failure() if read is not None else BUDGET_EXHAUSTED)
    return normalize_protect_records(page.rows, context, failure=read.failure, budget_exhausted=read.budget_stopped)


async def collect_protect_incident_evidence(
    events: ProtectEventPages | Callable[[], Awaitable[ProtectEventPages]],
    request: ProtectIncidentRequest,
    *,
    clock: Callable[[], float] | None = None,
    now: Callable[[], datetime] = utc_now,
) -> IncidentEvidence:
    """Collect bounded Protect event evidence for ``request``'s window.

    ``events`` is the Protect ``EventManager`` (or anything with its
    ``list_events_raw_page``), or an awaitable factory for one, acquired
    inside the first read; no other method is called. Source failures,
    budget exhaustion and truncation are reported in the evidence, never
    raised.
    """
    get_events = acquire_once(events, "list_events_raw_page")
    meter = BudgetMeter(request.limits, clock=clock)
    planned_at = now()
    bounds = _millisecond_bounds(request)
    plan: list[tuple[str, str | None]] = (
        [(camera_source_id(index), camera) for index, camera in enumerate(request.camera_ids, start=1)]
        if request.camera_ids
        else [(PROTECT_EVENTS_SOURCE, None)]
    )
    reads: list[SourceRead | None] = []
    for _, camera_id in plan:
        if request.window_exhausted:
            reads.append(None)
            continue

        async def read_page(offset: int, limit: int, camera_id: str | None = camera_id) -> SourcePage:
            return await (await get_events()).list_events_raw_page(
                start=bounds[0], end=bounds[1], limit=limit, offset=offset, camera_id=camera_id
            )

        reads.append(await read_source_pages(read_page, meter, page_size=EVENTS_PAGE_SIZE, now=now))
    meter.stop()
    sources = [
        _source(read, request, source_id=source_id, camera_id=camera_id, bounds=bounds, now=planned_at)
        for read, (source_id, camera_id) in zip(reads, plan, strict=True)
    ]
    return assemble_incident_evidence(
        requested_window=request.window,
        budgets=meter.budgets(window_exhausted=request.window_exhausted),
        sources=sources,
        mappings=request.mappings,
    )
