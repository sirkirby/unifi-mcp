"""Bounded, read-only incident evidence collection shared by every product.

Product collectors (``unifi_core.network.incident_collection`` and
``unifi_core.protect.incident_collection``) plan their sources and read each
one through :func:`read_source_pages`, which checks the evidence set's
budgets before every read. :func:`combine_incident_evidence` merges evidence
sets for one window into one set and keeps every source's own outcome.

Nothing here performs controller I/O: collectors pass page readers bound to
manager read methods. Budgets (see ``docs/incident-evidence.md``):

- ``window``: a requested window longer than ``window_seconds`` is not read.
- ``events``: every row a source returns counts, including rows outside the
  window or later removed by an exact-identifier filter. A read never asks
  for more rows than remain.
- ``calls``: one manager page read is one call.
- ``elapsed``: wall time across reads; a read still running when the budget
  runs out is cancelled.

A budget that stops collection is reported exhausted, the source it stopped
is ``partial`` (or ``not_attempted`` if it returned nothing), and every
source after it is ``not_attempted``.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from unifi_core.incident_evidence import (
    BudgetKind,
    BudgetLimits,
    Budgets,
    BudgetUsage,
    EvidenceRecord,
    FailureKind,
    IncidentEvidence,
    MappingAssertion,
    MappingOutcome,
    MappingStatus,
    SourceEvidence,
    SourceFailure,
    TimeWindow,
    assemble_incident_evidence,
    canonical_json,
    failure_from_exception,
    validate_incident_evidence,
)
from unifi_core.source_page import SourcePage

MAX_WINDOW_SECONDS = 30 * 24 * 3600
MAX_EVENTS = 10_000
MAX_CALLS = 100
MAX_ELAPSED_MS = 120_000
MAX_FILTER_IDS = 50

DEFAULT_WINDOW_SECONDS = 24 * 3600
DEFAULT_EVENTS = 1_000
DEFAULT_CALLS = 20
DEFAULT_ELAPSED_MS = 30_000

#: The failure of a source a budget kept from being read at all.
BUDGET_EXHAUSTED = SourceFailure(kind=FailureKind.BUDGET_EXHAUSTED)
_NOT_EVALUATED = MappingOutcome(status=MappingStatus.NOT_EVALUATED)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


def parse_window_bound(value: Any, name: str) -> datetime:
    """Parse an ISO 8601 window bound that states its UTC offset.

    A bound without an offset is ambiguous, so it is rejected rather than
    assumed to be UTC. The rejected value is never echoed.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be an ISO 8601 timestamp with a UTC offset, for example 2026-08-08T12:00:00Z")
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValueError(
            f"{name} must be an ISO 8601 timestamp with a UTC offset, for example 2026-08-08T12:00:00Z"
        ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} needs an explicit UTC offset (Z or +HH:MM); without one the time is ambiguous")
    return parsed


class IncidentCollectionRequest(BaseModel):
    """Arguments shared by every product's incident evidence collection.

    Adapters build the product subclass from caller input; the collector
    reads only what it describes.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    start: str = Field(description="Window start, ISO 8601 with a UTC offset (inclusive).")
    end: str = Field(description="Window end, ISO 8601 with a UTC offset (exclusive).")
    location_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Caller's label for the investigated location, recorded in each source's scope.",
    )
    max_window_seconds: int = Field(default=DEFAULT_WINDOW_SECONDS, ge=1, le=MAX_WINDOW_SECONDS)
    max_events: int = Field(default=DEFAULT_EVENTS, ge=1, le=MAX_EVENTS)
    max_calls: int = Field(default=DEFAULT_CALLS, ge=1, le=MAX_CALLS)
    max_elapsed_ms: int = Field(default=DEFAULT_ELAPSED_MS, ge=1, le=MAX_ELAPSED_MS)
    mappings: tuple[MappingAssertion, ...] | None = Field(
        default=None,
        description="Explicit exact-identifier assertions records are mapped against; never inferred.",
    )

    @model_validator(mode="after")
    def _window(self) -> IncidentCollectionRequest:
        start = parse_window_bound(self.start, "start")
        end = parse_window_bound(self.end, "end")
        if start >= end:
            raise ValueError("start must be before end")
        return self

    @property
    def window(self) -> TimeWindow:
        return TimeWindow.from_datetimes(parse_window_bound(self.start, "start"), parse_window_bound(self.end, "end"))

    @property
    def limits(self) -> BudgetLimits:
        return BudgetLimits(
            window_seconds=self.max_window_seconds,
            events=self.max_events,
            calls=self.max_calls,
            elapsed_ms=self.max_elapsed_ms,
        )

    @property
    def window_exhausted(self) -> bool:
        return self.max_window_seconds < self.window.duration_seconds


def describe_validation_error(error: ValidationError) -> str:
    """Field and reason for each problem, without the rejected input values."""
    problems = []
    for item in error.errors(include_input=False, include_url=False):
        location = ".".join(str(part) for part in item.get("loc", ())) or "request"
        message = str(item.get("msg", "invalid value")).removeprefix("Value error, ")
        problems.append(f"{location}: {message}")
    return "; ".join(problems) or "invalid request"


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


class BudgetMeter:
    """Usage of one collection's call, event and elapsed budgets."""

    def __init__(self, limits: BudgetLimits, *, clock: Callable[[], float] | None = None) -> None:
        self.limits = limits
        self._clock = clock or time.monotonic
        self._started = self._clock()
        self._stopped_ms: int | None = None
        self.events = 0
        self.calls = 0
        self._exhausted: set[BudgetKind] = set()

    def elapsed_ms(self) -> int:
        if self._stopped_ms is not None:
            return self._stopped_ms
        return max(0, int((self._clock() - self._started) * 1000))

    def remaining_events(self) -> int:
        return max(0, self.limits.events - self.events)

    def remaining_seconds(self) -> float:
        return max(0.0, self.limits.elapsed_ms / 1000 - (self._clock() - self._started))

    def blocking(self) -> BudgetKind | None:
        """Record and return the budget that forbids another read, if any."""
        used = {
            BudgetKind.CALLS: (self.calls, self.limits.calls),
            BudgetKind.EVENTS: (self.events, self.limits.events),
            BudgetKind.ELAPSED: (self.elapsed_ms(), self.limits.elapsed_ms),
        }
        spent = [kind for kind, (value, limit) in used.items() if value >= limit]
        self._exhausted.update(spent)
        return spent[0] if spent else None

    def exhaust(self, kind: BudgetKind) -> None:
        self._exhausted.add(kind)

    def stop(self) -> None:
        """Freeze elapsed usage at the end of reading."""
        if self._stopped_ms is None:
            self._stopped_ms = self.elapsed_ms()

    def budgets(self, *, window_exhausted: bool) -> Budgets:
        exhausted = set(self._exhausted)
        elapsed = self.elapsed_ms()
        if BudgetKind.ELAPSED in exhausted:
            # A read cancelled at the deadline used the whole budget.
            elapsed = max(elapsed, self.limits.elapsed_ms)
        for kind, used, limit in (
            (BudgetKind.EVENTS, self.events, self.limits.events),
            (BudgetKind.CALLS, self.calls, self.limits.calls),
            (BudgetKind.ELAPSED, elapsed, self.limits.elapsed_ms),
        ):
            if used > limit:
                exhausted.add(kind)
        if window_exhausted:
            exhausted.add(BudgetKind.WINDOW)
        return Budgets(
            limits=self.limits,
            usage=BudgetUsage(events=self.events, calls=self.calls, elapsed_ms=elapsed),
            exhausted=tuple(sorted(exhausted, key=lambda kind: kind.value)),
        )


# ---------------------------------------------------------------------------
# Reading one source
# ---------------------------------------------------------------------------

PageReader = Callable[[int, int], Awaitable[SourcePage]]
"""``(offset, limit) -> SourcePage``: one manager page read."""


@dataclass(frozen=True)
class SourceRead:
    """What bounded page reads of one source returned and how they ended."""

    # Every page merged into one; None when no read returned.
    page: SourcePage | None
    # The read that failed, when one did.
    failure: SourceFailure | None
    # A budget stopped reading before the source showed its end.
    budget_stopped: bool
    # Sum of the limits sent across reads.
    requested: int
    started_at: datetime
    finished_at: datetime

    def evidence_failure(self) -> SourceFailure | None:
        """The failure to report for a source that produced no page."""
        if self.page is not None:
            return self.failure
        return self.failure or BUDGET_EXHAUSTED


def _source_ended(page: SourcePage, seen: int) -> bool:
    if page.has_more is False:
        return True
    if page.has_more is True:
        return False
    return page.total_reported is not None and not page.post_filtered and seen >= page.total_reported


def _intersect(windows: list[tuple[int, int] | None]) -> tuple[int, int] | None:
    if not windows or any(window is None for window in windows):
        return None
    return max(w[0] for w in windows), min(w[1] for w in windows)  # type: ignore[index]


def _merge_pages(pages: list[SourcePage], *, ended: bool) -> SourcePage:
    """One page describing consecutive reads of one source.

    The queried window is the part every read covered. The end is claimed
    only when the last read proved it and the source's population did not
    visibly move between reads (a changed total or API path), because
    offsets then no longer line up.
    """
    totals = {page.total_reported for page in pages}
    paths = {page.api_path for page in pages}
    stable = len(totals) == 1 and len(paths) == 1
    last = pages[-1]
    if not stable:
        has_more, total = None, None
    elif ended:
        has_more, total = False, last.total_reported
    else:
        has_more, total = last.has_more, last.total_reported
    caps = [page.cap for page in pages]
    return SourcePage(
        rows=[row for page in pages for row in page.rows],
        has_more=has_more,
        total_reported=total,
        offset=pages[0].offset,
        cap=None if any(cap is None for cap in caps) else sum(caps),  # type: ignore[misc]
        api_path=pages[0].api_path if len(paths) == 1 else None,
        submitted_window_ms=_intersect([page.submitted_window_ms for page in pages]),
        post_filtered=any(page.post_filtered for page in pages),
    )


async def read_source_pages(
    read: PageReader,
    meter: BudgetMeter,
    *,
    page_size: int,
    paged: bool = True,
    now: Callable[[], datetime] = utc_now,
) -> SourceRead:
    """Read one source page by page while every budget allows another read.

    Reading stops when the source proves its end (``has_more`` false, or its
    remote total reached), when a read fails, or when a budget is spent.
    ``paged=False`` reads a source that has no offset exactly once.
    """
    started_at = now()
    pages: list[SourcePage] = []
    failure: SourceFailure | None = None
    stopped = ended = False
    requested = offset = 0
    while True:
        if meter.blocking() is not None:
            stopped = True
            break
        limit = min(page_size, meter.remaining_events())
        meter.calls += 1
        requested += limit
        deadline = asyncio.timeout(meter.remaining_seconds())
        try:
            async with deadline:
                page = await read(offset, limit)
        except TimeoutError as exc:
            if deadline.expired():
                meter.exhaust(BudgetKind.ELAPSED)
                stopped = True
            else:
                failure = failure_from_exception(exc)
            break
        except Exception as exc:  # noqa: BLE001 - classified into evidence, never re-raised
            failure = failure_from_exception(exc)
            break
        meter.events += len(page.rows)
        pages.append(page)
        seen = offset + len(page.rows)
        if _source_ended(page, seen):
            ended = True
            break
        if not paged or not page.rows:
            break
        offset = seen
    return SourceRead(
        page=_merge_pages(pages, ended=ended) if pages else None,
        failure=failure,
        budget_stopped=stopped and not ended,
        requested=requested,
        started_at=started_at,
        finished_at=now(),
    )


# ---------------------------------------------------------------------------
# Combining evidence sets
# ---------------------------------------------------------------------------


def _canonical(value: BaseModel) -> str:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _combined_budgets(documents: list[IncidentEvidence], window: TimeWindow) -> Budgets:
    limits = BudgetLimits(
        window_seconds=min(doc.budgets.limits.window_seconds for doc in documents),
        events=sum(doc.budgets.limits.events for doc in documents),
        calls=sum(doc.budgets.limits.calls for doc in documents),
        elapsed_ms=sum(doc.budgets.limits.elapsed_ms for doc in documents),
    )
    usage = BudgetUsage(
        events=sum(doc.budgets.usage.events for doc in documents),
        calls=sum(doc.budgets.usage.calls for doc in documents),
        elapsed_ms=sum(doc.budgets.usage.elapsed_ms for doc in documents),
    )
    reported = {kind for doc in documents for kind in doc.budgets.exhausted}
    exhausted: set[BudgetKind] = set()
    if limits.window_seconds < window.duration_seconds:
        exhausted.add(BudgetKind.WINDOW)
    for kind, used, limit in (
        (BudgetKind.EVENTS, usage.events, limits.events),
        (BudgetKind.CALLS, usage.calls, limits.calls),
        (BudgetKind.ELAPSED, usage.elapsed_ms, limits.elapsed_ms),
    ):
        if used > limit or (kind in reported and used >= limit):
            exhausted.add(kind)
    return Budgets(limits=limits, usage=usage, exhausted=tuple(sorted(exhausted, key=lambda kind: kind.value)))


def combine_incident_evidence(documents: Iterable[IncidentEvidence | Mapping[str, Any]]) -> IncidentEvidence:
    """Merge evidence sets for one requested window into one validated set.

    Pure and order-independent; identical sets count once. Every source keeps its own outcome, failure,
    partial reasons and coverage. A source ID that appears in more than one
    set must describe the same source and records, or the sets conflict.
    Mapping assertions are the union of every set's assertions, and each
    record's mapping is resolved again against them (``None`` only when no
    set carried assertions).

    Budgets add up: limits and usage are summed, except ``window_seconds``,
    which is the smallest limit. A budget kind stays exhausted when the
    combined usage reached the combined limit; whatever a budget stopped
    stays visible on the source it stopped.
    """
    # The same set passed twice is one collection, not two budgets' worth.
    unique = {canonical_json(document): document for document in documents}
    docs = [validate_incident_evidence(unique[key]) for key in sorted(unique)]
    if not docs:
        raise ValueError("combining evidence needs at least one evidence set")
    window = docs[0].requested_window
    if any(doc.requested_window != window for doc in docs):
        raise ValueError("evidence sets can be combined only for the same requested window")

    sources: dict[str, SourceEvidence] = {}
    for doc in docs:
        records: dict[str, list[EvidenceRecord]] = {source.source_id: [] for source in doc.sources}
        for record in doc.records:
            records[record.source_id].append(record.model_copy(update={"mapping": _NOT_EVALUATED}))
        for source in doc.sources:
            item = SourceEvidence(source=source, records=tuple(records[source.source_id]))
            existing = sources.setdefault(source.source_id, item)
            if existing != item:
                raise ValueError(f"evidence sets disagree about source {source.source_id}")

    assertion_sets = [doc.mappings for doc in docs if doc.mappings is not None]
    mappings = None
    if assertion_sets:
        unique = {_canonical(assertion): assertion for assertions in assertion_sets for assertion in assertions}
        mappings = [unique[key] for key in sorted(unique)]

    return assemble_incident_evidence(
        requested_window=window,
        budgets=_combined_budgets(docs, window),
        sources=sources.values(),
        mappings=mappings,
    )
