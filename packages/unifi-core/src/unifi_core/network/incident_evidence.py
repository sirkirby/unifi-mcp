"""Network event and alarm normalizers for the incident evidence contract.

Pure functions: no controller I/O. They accept the record shapes Network
actually returns today:

- ``EventManager.get_events`` / ``get_alarms`` records: v2 system-log
  (``id``, ``key``, ``timestamp`` epoch ms, role-keyed ``parameters``) or the
  legacy ``/stat/event`` / ``/stat/alarm`` shape (``_id``, ``key``, ``time``
  epoch ms, flat ``user``/``ap``/``sw``/``gw`` MACs).
- The ``unifi_list_events`` / ``unifi_list_alarms`` tool projections
  (``ThreatEventLog`` / ``Alarm``: ``id``, ``key``, ``msg``, ``time``, ``mac``),
  whose records live under the top-level ``events`` / ``alarms`` keys, not
  under ``data``.

``unifi_list_events`` takes a relative ``within_hours`` lookback read from
the manager's clock during the call, so the certain queried window ends when
the request started; ``start`` is a pagination offset, not a time.
``unifi_list_alarms`` takes no time range.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Literal

from unifi_core.incident_evidence import (
    ABSENT,
    ApiFamily,
    EntityKind,
    EntityRef,
    ExtractedRecord,
    IdKind,
    Product,
    Scope,
    SourceContext,
    SourceEvidence,
    SourceFailure,
    TimeWindow,
    apply_source_page,
    collect_source,
    format_utc,
    records_from_tool_response,
    source_failed,
    window_from_epoch_ms,
)
from unifi_core.mac import looks_like_mac
from unifi_core.network.models.events import threat_event_log_from_controller
from unifi_core.source_page import SourcePage

LIST_EVENTS_TOOL = "unifi_list_events"
LIST_ALARMS_TOOL = "unifi_list_alarms"

#: Where each tool's response envelope keeps its records.
TOOL_RECORD_PATHS: dict[str, tuple[str, ...]] = {
    LIST_EVENTS_TOOL: ("events",),
    LIST_ALARMS_TOOL: ("alarms",),
}

# v2 ``parameters`` roles that name a station by MAC, and what kind it is.
_ROLE_KINDS: tuple[tuple[str, EntityKind], ...] = (
    ("SRC_CLIENT", EntityKind.NETWORK_CLIENT),
    ("CLIENT", EntityKind.NETWORK_CLIENT),
    ("DST_CLIENT", EntityKind.NETWORK_CLIENT),
    ("SRC_DEVICE", EntityKind.NETWORK_DEVICE),
    ("DEVICE", EntityKind.NETWORK_DEVICE),
    ("AP", EntityKind.NETWORK_DEVICE),
    ("GATEWAY", EntityKind.NETWORK_DEVICE),
)
# Legacy flat MAC keys.
_LEGACY_KINDS: tuple[tuple[str, EntityKind], ...] = (
    ("user", EntityKind.NETWORK_CLIENT),
    ("guest", EntityKind.NETWORK_CLIENT),
    ("ap", EntityKind.NETWORK_DEVICE),
    ("sw", EntityKind.NETWORK_DEVICE),
    ("gw", EntityKind.NETWORK_DEVICE),
)
_TIME_FIELDS = ("time", "timestamp", "ts", "datetime")
_PROJECTION_SKIP = frozenset({*_TIME_FIELDS, "_id", "id"})
# The alarm v2 path looks back this far (EventManager._get_alarms_v2).
ALARM_V2_LOOKBACK = timedelta(days=30)


def _entities(raw: Mapping[str, Any]) -> tuple[EntityRef, ...]:
    found: list[EntityRef] = []
    seen: set[tuple[str, tuple[str, str]]] = set()

    def _add(kind: EntityKind, value: Any, role: str) -> None:
        if not looks_like_mac(value):
            return
        ref = EntityRef(kind=kind, id_kind=IdKind.MAC, id=value, role=role)
        marker = (kind.value, ref.identity)
        if marker not in seen:
            seen.add(marker)
            found.append(ref)

    parameters = raw.get("parameters")
    if isinstance(parameters, Mapping):
        for role, kind in _ROLE_KINDS:
            actor = parameters.get(role)
            if isinstance(actor, Mapping):
                _add(kind, actor.get("id"), role)
    for key, kind in _LEGACY_KINDS:
        _add(kind, raw.get(key), key)
    if not found:
        # Tool projections keep one MAC without saying whether it is a client or device.
        _add(EntityKind.NETWORK_STATION, raw.get("mac"), "mac")
    return tuple(found)


def extract_network_record(raw: Mapping[str, Any]) -> ExtractedRecord | None:
    """Extract contract fields from one Network event or alarm record."""
    # IDs and times are read by the contract as returned; the projection model
    # would reject integer IDs and the malformed times that must stay visible.
    projected = threat_event_log_from_controller({k: v for k, v in raw.items() if k not in _PROJECTION_SKIP})
    record_id_field = next((key for key in ("_id", "id") if raw.get(key) is not None), None)
    time_field = next((key for key in _TIME_FIELDS if key in raw and raw[key] is not None), None)
    if time_field is None:
        time_field = next((key for key in _TIME_FIELDS if key in raw), None)
    time_value = raw[time_field] if time_field is not None else ABSENT
    event_type = projected.key or projected.event
    if record_id_field is None and time_field is None and event_type is None and projected.msg is None:
        return None
    attributes: dict[str, Any] = {
        "severity": projected.severity,
        "category": projected.category,
        "subcategory": projected.subcategory,
        "event": projected.event,
    }
    if isinstance(raw.get("archived"), bool):
        attributes["archived"] = raw["archived"]
    return ExtractedRecord(
        record_id=raw[record_id_field] if record_id_field else None,
        record_id_field=record_id_field,
        time_field=time_field,
        time_value=time_value,
        event_type=event_type,
        summary=projected.msg,
        entities=_entities(raw),
        attributes={key: value for key, value in attributes.items() if value is not None},
    )


def _scope(site: str | None, controller_id: str | None, location_id: str | None) -> Scope:
    return Scope(site=site, controller_id=controller_id, location_id=location_id)


ApiPath = Literal["v2", "legacy"]

# Hard caps the manager applies regardless of the requested limit.
LEGACY_EVENTS_CAP = 3000  # EventManager._get_events_legacy: ``_limit`` is clamped
V2_ALARMS_PAGE_CAP = 100  # EventManager._get_alarms_v2: one page of at most 100
_EVENT_ENDPOINTS = {"v2": "/system-log/all", "legacy": "/stat/event"}
_ALARM_ENDPOINTS = {"v2": "/system-log/critical", "legacy": "/stat/alarm"}


def _floor_ms(value: datetime) -> datetime:
    return value.replace(microsecond=value.microsecond - value.microsecond % 1000)


def _guaranteed_window(span: timedelta, request_started_at: datetime, collected_at: datetime) -> TimeWindow | None:
    """The interval a relative lookback covered whenever the manager read its clock.

    The manager reads "now" somewhere between ``request_started_at`` and
    ``collected_at`` and floors it to milliseconds before sending it; only
    the overlap of every possible window is certain.
    """
    if request_started_at > collected_at:
        raise ValueError("request_started_at must not be after collected_at")
    start, end = collected_at - span, _floor_ms(request_started_at)
    return TimeWindow.from_datetimes(start, end) if start < end else None


def effective_events_cap(limit: int, api_path: ApiPath | None) -> int:
    """The most records ``get_events`` can return; unknown paths assume the smaller cap."""
    limit = max(limit, 0)
    return limit if api_path == "v2" else min(limit, LEGACY_EVENTS_CAP)


def effective_alarms_cap(limit: int, api_path: ApiPath | None) -> int:
    """The most records ``get_alarms`` can return; unknown paths assume the smaller cap."""
    limit = max(limit, 0)
    return limit if api_path == "legacy" else min(limit, V2_ALARMS_PAGE_CAP)


def _page_api_path(page: SourcePage | None, api_path: ApiPath | None) -> ApiPath | None:
    if page is None or page.api_path is None:
        return api_path
    if api_path is not None and api_path != page.api_path:
        raise ValueError("api_path disagrees with the page the manager returned")
    if page.api_path not in ("v2", "legacy"):
        raise ValueError("unknown Network api_path on the page")
    return page.api_path  # type: ignore[return-value]


def network_events_context(
    *,
    requested_window: TimeWindow,
    request_started_at: datetime,
    collected_at: datetime,
    within_hours: int = 24,
    limit: int = 100,
    start: int = 0,
    event_type: str | None = None,
    categories: Sequence[str] | None = None,
    severities: Sequence[str] | None = None,
    device_macs: Sequence[str] | None = None,
    window_ms: tuple[int, int] | None = None,
    api_path: ApiPath | None = None,
    page: SourcePage | None = None,
    source_id: str = "network.events",
    site: str | None = None,
    controller_id: str | None = None,
    location_id: str | None = None,
    endpoint: str | None = None,
    clock_uncertainty_ms: int | None = None,
) -> SourceContext:
    """Describe one ``unifi_list_events`` call; arguments mirror the tool's.

    Pass the ``page`` from ``EventManager.get_events_page``: it carries the
    path that answered, the remote total, whether more rows exist, and on the
    v2 path the exact millisecond bounds submitted. Without a page nothing
    establishes that the read reached the end, so coverage is never complete.

    ``request_started_at`` is captured immediately before the call and
    ``collected_at`` when it returned. They bound the window only when the
    page does not record submitted bounds (the legacy path asks the
    controller for a relative lookback). ``start`` is an offset, so any value
    but 0 leaves the skipped prefix uncollected.

    ``device_macs`` records an exact-MAC filter applied to the page's rows
    after they were read; such a page must say ``post_filtered``.

    ``window_ms`` describes a v2 read sent with absolute epoch-millisecond
    ``timestampFrom``/``timestampTo`` bounds instead of a lookback: the query
    records those bounds in place of ``within_hours``, and they are the
    queried window.
    """
    api_path = _page_api_path(page, api_path)
    if window_ms is not None:
        lookback: dict[str, Any] = {"timestamp_from_ms": window_ms[0], "timestamp_to_ms": window_ms[1]}
        queried = window_from_epoch_ms(*window_ms)
    else:
        lookback = {"within_hours": within_hours}
        queried = _guaranteed_window(timedelta(hours=within_hours), request_started_at, collected_at)
    context = SourceContext(
        source_id=source_id,
        product=Product.NETWORK,
        api_family=ApiFamily.NETWORK_V2_CONTROLLER,
        source_tool=LIST_EVENTS_TOOL,
        endpoint=endpoint or (_EVENT_ENDPOINTS[api_path] if api_path else None),
        scope=_scope(site, controller_id, location_id),
        query={
            **lookback,
            "limit": limit,
            "start": start,
            "event_type": event_type,
            "categories": list(categories) if categories is not None else None,
            "severities": list(severities) if severities is not None else None,
        },
        filters={
            key: value
            for key, value in (
                ("event_type", event_type),
                ("categories", list(categories) if categories else None),
                ("severities", list(severities) if severities else None),
                ("device_macs", list(device_macs) if device_macs else None),
            )
            if value is not None
        },
        collected_at=format_utc(collected_at),
        requested_window=requested_window,
        queried_window=queried,
        offset=start,
        requested_cap=max(limit, 0),
        cap=effective_events_cap(limit, api_path),
        clock_uncertainty_ms=clock_uncertainty_ms,
    )
    return apply_source_page(context, page) if page is not None else context


def network_alarms_context(
    *,
    requested_window: TimeWindow,
    collected_at: datetime,
    include_archived: bool = False,
    limit: int = 100,
    api_path: ApiPath | None = None,
    page: SourcePage | None = None,
    request_started_at: datetime | None = None,
    queried_window: TimeWindow | None = None,
    source_id: str = "network.alarms",
    site: str | None = None,
    controller_id: str | None = None,
    location_id: str | None = None,
    endpoint: str | None = None,
    clock_uncertainty_ms: int | None = None,
) -> SourceContext:
    """Describe one ``unifi_list_alarms`` call.

    Pass the ``page`` from ``EventManager.get_alarms_page``: it carries the
    remote total, continuation state and, on the v2 path, the exact 30-day
    bounds submitted. The legacy path reads every alarm, so its window is
    whatever the caller supplies as ``queried_window``. Without a page
    coverage is never complete.
    """
    api_path = _page_api_path(page, api_path)
    if queried_window is None and api_path == "v2" and request_started_at is not None:
        queried_window = _guaranteed_window(ALARM_V2_LOOKBACK, request_started_at, collected_at)
    context = SourceContext(
        source_id=source_id,
        product=Product.NETWORK,
        api_family=ApiFamily.NETWORK_V2_CONTROLLER,
        source_tool=LIST_ALARMS_TOOL,
        endpoint=endpoint or (_ALARM_ENDPOINTS[api_path] if api_path else None),
        scope=_scope(site, controller_id, location_id),
        query={"include_archived": include_archived, "limit": limit},
        filters={"include_archived": include_archived},
        collected_at=format_utc(collected_at),
        requested_window=requested_window,
        queried_window=queried_window,
        requested_cap=max(limit, 0),
        cap=effective_alarms_cap(limit, api_path),
        clock_uncertainty_ms=clock_uncertainty_ms,
    )
    return apply_source_page(context, page) if page is not None else context


def normalize_network_records(
    records: Any,
    context: SourceContext,
    *,
    failure: SourceFailure | None = None,
    budget_exhausted: bool = False,
) -> SourceEvidence:
    """Normalize manager records or tool-projected records for one source."""
    return collect_source(context, records, extract_network_record, failure=failure, budget_exhausted=budget_exhausted)


def normalize_network_page(
    page: SourcePage, context: SourceContext, *, budget_exhausted: bool = False
) -> SourceEvidence:
    """Normalize a manager page; rows the manager could not read count as malformed."""
    return normalize_network_records(page.rows, context, budget_exhausted=budget_exhausted)


def normalize_network_tool_response(
    response: Any,
    context: SourceContext,
    *,
    budget_exhausted: bool = False,
) -> SourceEvidence:
    """Normalize a ``unifi_list_events`` or ``unifi_list_alarms`` response envelope."""
    path = TOOL_RECORD_PATHS.get(context.source_tool or "")
    if path is None:
        raise ValueError(f"no Network record path is known for tool {context.source_tool!r}")
    records = records_from_tool_response(response, path)
    if isinstance(records, SourceFailure):
        return source_failed(context, records)
    return normalize_network_records(records, context, budget_exhausted=budget_exhausted)
