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
    collect_source,
    format_utc,
    records_from_tool_response,
    source_failed,
)
from unifi_core.mac import looks_like_mac
from unifi_core.network.models.events import threat_event_log_from_controller

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


def _guaranteed_window(span: timedelta, request_started_at: datetime, collected_at: datetime) -> TimeWindow | None:
    """The interval a relative lookback covered whenever the manager read its clock.

    The manager takes "now" somewhere between ``request_started_at`` and
    ``collected_at``; only the overlap of every possible window is certain.
    """
    if request_started_at > collected_at:
        raise ValueError("request_started_at must not be after collected_at")
    start, end = collected_at - span, request_started_at
    return TimeWindow.from_datetimes(start, end) if start < end else None


def effective_events_cap(limit: int, api_path: ApiPath | None) -> int:
    """The most records ``get_events`` can return; unknown paths assume the smaller cap."""
    limit = max(limit, 0)
    return limit if api_path == "v2" else min(limit, LEGACY_EVENTS_CAP)


def effective_alarms_cap(limit: int, api_path: ApiPath | None) -> int:
    """The most records ``get_alarms`` can return; unknown paths assume the smaller cap."""
    limit = max(limit, 0)
    return limit if api_path == "legacy" else min(limit, V2_ALARMS_PAGE_CAP)


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
    api_path: ApiPath | None = None,
    source_id: str = "network.events",
    site: str | None = None,
    controller_id: str | None = None,
    location_id: str | None = None,
    endpoint: str | None = None,
    clock_uncertainty_ms: int | None = None,
) -> SourceContext:
    """Describe one ``unifi_list_events`` call; arguments mirror the tool's.

    ``request_started_at`` is captured immediately before the call and
    ``collected_at`` when it returned; the lookback is relative to the
    manager's own clock reading between them. ``start`` is an offset, so any
    value but 0 leaves the skipped prefix uncollected. ``api_path`` names the
    path that answered when known; otherwise the smaller legacy cap applies.
    """
    return SourceContext(
        source_id=source_id,
        product=Product.NETWORK,
        api_family=ApiFamily.NETWORK_V2_CONTROLLER,
        source_tool=LIST_EVENTS_TOOL,
        endpoint=endpoint or (_EVENT_ENDPOINTS[api_path] if api_path else None),
        scope=_scope(site, controller_id, location_id),
        query={
            "within_hours": within_hours,
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
            )
            if value is not None
        },
        collected_at=format_utc(collected_at),
        requested_window=requested_window,
        queried_window=_guaranteed_window(timedelta(hours=within_hours), request_started_at, collected_at),
        offset=start,
        requested_cap=max(limit, 0),
        cap=effective_events_cap(limit, api_path),
        clock_uncertainty_ms=clock_uncertainty_ms,
    )


def network_alarms_context(
    *,
    requested_window: TimeWindow,
    collected_at: datetime,
    include_archived: bool = False,
    limit: int = 100,
    api_path: ApiPath | None = None,
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

    The tool takes no time range and does not say which path answered. With
    ``api_path="v2"`` and ``request_started_at`` the fixed 30-day lookback is
    used; otherwise the queried window is ``queried_window`` or unknown. The
    v2 path reads one page of at most 100 alarms.
    """
    if queried_window is None and api_path == "v2" and request_started_at is not None:
        queried_window = _guaranteed_window(ALARM_V2_LOOKBACK, request_started_at, collected_at)
    return SourceContext(
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


def normalize_network_records(
    records: Any,
    context: SourceContext,
    *,
    failure: SourceFailure | None = None,
    budget_exhausted: bool = False,
) -> SourceEvidence:
    """Normalize manager records or tool-projected records for one source."""
    return collect_source(context, records, extract_network_record, failure=failure, budget_exhausted=budget_exhausted)


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
