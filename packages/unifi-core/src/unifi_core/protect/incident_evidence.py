"""Protect event normalizers for the incident evidence contract.

Pure functions: no controller I/O. They accept the record shapes Protect
actually returns today:

- ``EventManager.list_events`` records (``id``, ``type``, ``camera_id``,
  ``start``/``end`` as ISO strings with an offset), and raw NVR rows from the
  private ``events`` endpoint (``camera``, ``start``/``end`` epoch ms,
  ``smartDetectTypes``).
- The ``protect_list_events`` / ``protect_list_smart_detections`` tool
  projections (``Event`` / ``SmartDetection``: ``camera`` UUID, ISO ``start``),
  whose records live under ``data.events`` / ``data.detections``.

Event time is the event ``start``. Recognized-face and license-plate fields
are deliberately not carried: incident evidence never asserts identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

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
)
from unifi_core.source_page import SourcePage

LIST_EVENTS_TOOL = "protect_list_events"
LIST_SMART_DETECTIONS_TOOL = "protect_list_smart_detections"
EVENTS_ENDPOINT = "/proxy/protect/api/events"

#: Where each tool's response envelope keeps its records.
TOOL_RECORD_PATHS: dict[str, tuple[str, ...]] = {
    LIST_EVENTS_TOOL: ("data", "events"),
    LIST_SMART_DETECTIONS_TOOL: ("data", "detections"),
}
# EventManager's smart_detection_min_confidence when the server is not configured otherwise.
DEFAULT_SMART_DETECTION_MIN_CONFIDENCE = 50


def _camera_id(raw: Mapping[str, Any]) -> str | None:
    for key in ("camera", "camera_id", "cameraId"):
        value = raw.get(key)
        if isinstance(value, Mapping):
            value = value.get("id")
        if isinstance(value, str) and value:
            return value
    return None


def extract_protect_event(raw: Mapping[str, Any]) -> ExtractedRecord | None:
    """Extract contract fields from one Protect event or smart detection."""
    record_id = raw.get("id")
    event_type = raw.get("type") if isinstance(raw.get("type"), str) else None
    time_value = raw["start"] if "start" in raw else ABSENT
    if record_id is None and event_type is None and time_value is ABSENT:
        return None
    smart = raw.get("smart_detect_types", raw.get("smartDetectTypes"))
    smart_types = [value for value in smart if isinstance(value, str)] if isinstance(smart, list) else []
    camera = _camera_id(raw)
    summary = event_type
    if event_type and smart_types:
        summary = f"{event_type}: {', '.join(smart_types)}"
    attributes: dict[str, Any] = {"smart_detect_types": smart_types}
    for key in ("score", "end"):
        if raw.get(key) is not None:
            attributes[key] = raw[key]
    return ExtractedRecord(
        record_id=record_id,
        record_id_field="id" if record_id is not None else None,
        time_field="start",
        time_value=time_value,
        event_type=event_type,
        summary=summary,
        entities=(
            (EntityRef(kind=EntityKind.CAMERA, id_kind=IdKind.PROTECT_CAMERA_ID, id=camera, role="camera"),)
            if camera
            else ()
        ),
        attributes=attributes,
    )


def _tool_datetime(value: str | None) -> datetime | None:
    """Parse a tool time argument as the Protect tools do: naive is UTC, invalid is dropped."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def protect_events_context(
    *,
    requested_window: TimeWindow,
    collected_at: datetime,
    start: str | None = None,
    end: str | None = None,
    limit: int = 30,
    event_type: str | None = None,
    camera_id: str | None = None,
    compact: bool | None = None,
    metadata_fields: Sequence[str] | None = None,
    source_tool: str = LIST_EVENTS_TOOL,
    detection_type: str | None = None,
    min_confidence: int | None = None,
    server_min_confidence: int = DEFAULT_SMART_DETECTION_MIN_CONFIDENCE,
    page: SourcePage | None = None,
    source_id: str = "protect.events",
    controller_id: str | None = None,
    location_id: str | None = None,
    clock_uncertainty_ms: int | None = None,
) -> SourceContext:
    """Describe one ``protect_list_events`` or ``protect_list_smart_detections`` call.

    ``start``/``end`` are the ISO strings passed to the tool. A bound that is
    omitted or unparseable reaches the controller as no bound at all, so the
    queried window is unknown rather than an assumed 24 hours.

    Pass the ``page`` from ``EventManager.list_events_page`` or
    ``list_smart_detections_page``: it records whether the unfiltered read
    ran short of ``limit`` (the NVR reports no totals) and the millisecond
    bounds actually submitted. Without a page coverage is never complete.

    Smart detections are filtered by confidence after the controller applies
    ``limit``, so only the page's unfiltered continuation state can prove
    completeness. The effective
    threshold is ``min_confidence`` or, when omitted, the server's configured
    ``smart_detection_min_confidence`` passed as ``server_min_confidence``.
    """
    if source_tool not in TOOL_RECORD_PATHS:
        raise ValueError(f"no Protect record path is known for tool {source_tool!r}")
    query: dict[str, Any] = {"start": start, "end": end, "limit": limit, "camera_id": camera_id}
    if compact is not None:
        query["compact"] = compact
    if metadata_fields is not None:
        # Selects the raw endpoint instead of the SDK path, so it is part of the query.
        query["metadata_fields"] = list(metadata_fields)
    filters: dict[str, Any] = {"camera_id": camera_id}
    post_filtered = False
    if source_tool == LIST_EVENTS_TOOL:
        query["event_type"] = event_type
        filters["event_type"] = event_type
    else:
        effective = min_confidence if min_confidence is not None else server_min_confidence
        query["detection_type"] = detection_type
        query["min_confidence"] = min_confidence
        filters["detection_type"] = detection_type
        filters["min_confidence_effective"] = effective
        post_filtered = effective > 0
    queried_start, queried_end = _tool_datetime(start), _tool_datetime(end)
    queried = (
        TimeWindow.from_datetimes(queried_start, queried_end)
        if queried_start is not None and queried_end is not None and queried_start < queried_end
        else None
    )
    context = SourceContext(
        source_id=source_id,
        product=Product.PROTECT,
        api_family=ApiFamily.PROTECT_PRIVATE,
        source_tool=source_tool,
        endpoint=EVENTS_ENDPOINT,
        scope=Scope(controller_id=controller_id, location_id=location_id),
        query=query,
        filters={key: value for key, value in filters.items() if value is not None},
        collected_at=format_utc(collected_at),
        requested_window=requested_window,
        queried_window=queried,
        requested_cap=max(limit, 0),
        cap=max(limit, 0),
        post_filtered=post_filtered,
        clock_uncertainty_ms=clock_uncertainty_ms,
    )
    return apply_source_page(context, page) if page is not None else context


def normalize_protect_records(
    records: Any,
    context: SourceContext,
    *,
    failure: SourceFailure | None = None,
    budget_exhausted: bool = False,
) -> SourceEvidence:
    """Normalize manager, raw NVR or tool-projected Protect events for one source."""
    return collect_source(context, records, extract_protect_event, failure=failure, budget_exhausted=budget_exhausted)


def normalize_protect_page(
    page: SourcePage, context: SourceContext, *, budget_exhausted: bool = False
) -> SourceEvidence:
    """Normalize a manager page from ``list_events_page`` or ``list_smart_detections_page``."""
    return normalize_protect_records(page.rows, context, budget_exhausted=budget_exhausted)


def normalize_protect_tool_response(
    response: Any,
    context: SourceContext,
    *,
    budget_exhausted: bool = False,
) -> SourceEvidence:
    """Normalize a ``protect_list_events`` or ``protect_list_smart_detections`` envelope."""
    path = TOOL_RECORD_PATHS.get(context.source_tool or "")
    if path is None:
        raise ValueError(f"no Protect record path is known for tool {context.source_tool!r}")
    records = records_from_tool_response(response, path)
    if isinstance(records, SourceFailure):
        return source_failed(context, records)
    return normalize_protect_records(records, context, budget_exhausted=budget_exhausted)
