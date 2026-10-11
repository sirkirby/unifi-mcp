"""Bounded client view of an incident evidence document.

A full ``unifi-incident-evidence`` document carries every record with its raw
attributes and provenance; at realistic budgets it outgrows what MCP clients
accept in one tool result. :func:`client_view` projects a validated document
into a ``unifi-incident-evidence-view`` that a client can read whole:

- ``overall``, ``coverage_complete``, budgets, mapping assertions and every
  source (outcome, failure, reasons and coverage) are copied unchanged, so
  every coverage and failure claim reads the same as in the full document.
- Records are compact citations (evidence ID, product, source tool, source
  record ID, time and placement, type, summary, entities and mapping). Raw
  attributes and repeated provenance are dropped.
- At most ``max_records_returned`` records are returned: in-window records
  first, earliest first, then untimed records, then out-of-window records.
  ``record_selection`` counts what was collected, returned and omitted per
  placement. Omission is a presentation limit, never missing coverage; a
  narrower window starting at ``omitted_in_window_from_utc`` returns the
  in-window records left out.

The projection is pure and deterministic and keeps no state between calls.
MCP tools, API routes, the relay and the worker return it by default;
``detail="full"`` returns the full document.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from unifi_core.incident_evidence import (
    INCIDENT_EVIDENCE_SCHEMA_VERSION,
    Budgets,
    Coverage,
    EvidenceRecord,
    IncidentEvidence,
    MappingAssertion,
    MappingSource,
    MappingStatus,
    OriginalType,
    OverallStatus,
    PartialReason,
    Product,
    ScalarValue,
    Scope,
    SourceFailure,
    SourceOutcome,
    SourceResult,
    TimeStatus,
    TimeWindow,
    _overall,
    evidence_to_json,
    validate_incident_evidence,
)

INCIDENT_EVIDENCE_VIEW_SCHEMA = "unifi-incident-evidence-view"
INCIDENT_EVIDENCE_VIEW_SCHEMA_VERSION = 1

DEFAULT_MAX_RECORDS_RETURNED = 25
MAX_RECORDS_RETURNED = 50

_PLACED = (TimeStatus.IN_WINDOW, TimeStatus.OUT_OF_WINDOW)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class EvidenceDetail(str, Enum):
    VIEW = "view"
    FULL = "full"


class ViewTime(_ClosedModel):
    """A record's placement and the timestamp exactly as the source returned it."""

    status: TimeStatus
    utc: str | None
    boundary_uncertain: bool
    original_field: str | None
    original_type: OriginalType
    original_value: ScalarValue


class ViewMapping(_ClosedModel):
    """A record's mapping outcome: its target IDs and the assertion sources behind them."""

    status: MappingStatus
    target_ids: tuple[str, ...]
    sources: tuple[MappingSource, ...]


class ViewRecord(_ClosedModel):
    """One record in citation form; ``evidence_id`` begins with its source ID."""

    evidence_id: str
    product: Product
    source_tool: str | None
    source_record_id: StrictStr | StrictInt | None
    time: ViewTime
    event_type: str | None
    summary: str | None
    entity_ids: tuple[str, ...]
    mapping: ViewMapping


class ViewSource(_ClosedModel):
    """A source's outcome, failure and coverage, exactly as in the full document.

    Request provenance (API family, endpoint, query, collection time) is left
    to the full document; nothing it states changes coverage.
    """

    source_id: str
    product: Product
    source_tool: str | None
    scope: Scope
    outcome: SourceOutcome
    failure: SourceFailure | None
    partial_reasons: tuple[PartialReason, ...]
    coverage: Coverage

    @classmethod
    def from_source(cls, source: SourceResult) -> ViewSource:
        return cls(**{name: getattr(source, name) for name in cls.model_fields})


class RecordTally(_ClosedModel):
    total: int = Field(ge=0)
    in_window: int = Field(ge=0)
    out_of_window: int = Field(ge=0)
    untimed: int = Field(ge=0)

    @model_validator(mode="after")
    def _balanced(self) -> RecordTally:
        if self.total != self.in_window + self.out_of_window + self.untimed:
            raise ValueError("a tally's total must equal in-window + out-of-window + untimed records")
        return self


def _tally(statuses: list[TimeStatus]) -> RecordTally:
    in_window = statuses.count(TimeStatus.IN_WINDOW)
    out_of_window = statuses.count(TimeStatus.OUT_OF_WINDOW)
    return RecordTally(
        total=len(statuses),
        in_window=in_window,
        out_of_window=out_of_window,
        untimed=len(statuses) - in_window - out_of_window,
    )


class RecordSelection(_ClosedModel):
    """Which collected records the view returns; omission never reduces coverage."""

    max_records_returned: int = Field(ge=1, le=MAX_RECORDS_RETURNED)
    omission: Literal["presentation_limit"] = "presentation_limit"
    collected: RecordTally
    returned: RecordTally
    omitted: RecordTally
    omitted_in_window_from_utc: str | None

    @model_validator(mode="after")
    def _consistent(self) -> RecordSelection:
        for field in ("total", "in_window", "out_of_window", "untimed"):
            if getattr(self.returned, field) + getattr(self.omitted, field) != getattr(self.collected, field):
                raise ValueError("returned and omitted records must add up to the collected records")
        if self.returned.total > self.max_records_returned:
            raise ValueError("a view returns at most max_records_returned records")
        if self.omitted.total and self.returned.total < self.max_records_returned:
            raise ValueError("records are omitted only when the view is full")
        if (self.omitted_in_window_from_utc is None) != (self.omitted.in_window == 0):
            raise ValueError("omitted_in_window_from_utc is set exactly when in-window records were omitted")
        return self


class IncidentEvidenceView(_ClosedModel):
    """A bounded projection of one evidence set, readable in one tool result."""

    schema_name: Literal["unifi-incident-evidence-view"] = Field(default=INCIDENT_EVIDENCE_VIEW_SCHEMA, alias="schema")
    schema_version: Literal[1] = INCIDENT_EVIDENCE_VIEW_SCHEMA_VERSION
    evidence_schema_version: Literal[1] = INCIDENT_EVIDENCE_SCHEMA_VERSION
    requested_window: TimeWindow
    overall: OverallStatus
    coverage_complete: bool
    budgets: Budgets
    mappings: tuple[MappingAssertion, ...] | None
    sources: tuple[ViewSource, ...] = Field(min_length=1)
    records: tuple[ViewRecord, ...]
    record_selection: RecordSelection

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always", populate_by_name=True)

    @model_validator(mode="after")
    def _consistent(self) -> IncidentEvidenceView:
        # The contract's rule reads only each source's outcome.
        expected = _overall(self.sources, self.budgets)  # type: ignore[arg-type]
        if self.overall is not expected:
            raise ValueError(f"overall status must be {expected.value} for these sources and budgets")
        if self.coverage_complete != (expected in (OverallStatus.COMPLETE, OverallStatus.EMPTY)):
            raise ValueError("coverage_complete is true only for complete or empty evidence")
        source_ids = [source.source_id for source in self.sources]
        if source_ids != sorted(set(source_ids)):
            raise ValueError("sources must be sorted by unique source_id")
        collected = self.record_selection.collected
        counts = [source.coverage.counts for source in self.sources]
        if (collected.in_window, collected.out_of_window, collected.untimed) != (
            sum(c.in_window for c in counts),
            sum(c.out_of_window for c in counts),
            sum(c.untimed for c in counts),
        ):
            raise ValueError("collected records must equal the sources' accepted record counts")
        if _tally([record.time.status for record in self.records]) != self.record_selection.returned:
            raise ValueError("returned counts must describe the records in the view")
        prefixes = set(source_ids)
        if any(record.evidence_id.split("|", 1)[0] not in prefixes for record in self.records):
            raise ValueError("every record must cite a listed source")
        return self


def _view_record(record: EvidenceRecord) -> ViewRecord:
    time = record.time
    return ViewRecord(
        evidence_id=record.evidence_id,
        product=record.provenance.product,
        source_tool=record.provenance.source_tool,
        source_record_id=record.provenance.source_record_id,
        time=ViewTime(
            status=time.status,
            utc=time.utc,
            boundary_uncertain=time.boundary_uncertain,
            original_field=time.original_field,
            original_type=time.original_type,
            original_value=time.original_value,
        ),
        event_type=record.event_type,
        summary=record.summary,
        entity_ids=tuple(entity.id for entity in record.entities),
        mapping=ViewMapping(
            status=record.mapping.status,
            target_ids=tuple(target.id for target in record.mapping.targets),
            sources=record.mapping.sources,
        ),
    )


def _priority(record: EvidenceRecord) -> int:
    if record.time.status is TimeStatus.IN_WINDOW:
        return 0
    return 2 if record.time.status is TimeStatus.OUT_OF_WINDOW else 1


def client_view(
    evidence: IncidentEvidence, *, max_records_returned: int = DEFAULT_MAX_RECORDS_RETURNED
) -> IncidentEvidenceView:
    """Project a validated evidence set into its bounded client view.

    In-window records are kept first, earliest first, then untimed and then
    out-of-window records; returned records keep the document's order.
    """
    evidence = validate_incident_evidence(evidence)
    ranked = sorted(range(len(evidence.records)), key=lambda i: (_priority(evidence.records[i]), i))
    kept = set(ranked[:max_records_returned])
    returned = [record for i, record in enumerate(evidence.records) if i in kept]
    omitted = [record for i, record in enumerate(evidence.records) if i not in kept]
    omitted_in_window = [record.time.utc for record in omitted if record.time.status is TimeStatus.IN_WINDOW]
    return IncidentEvidenceView(
        requested_window=evidence.requested_window,
        overall=evidence.overall,
        coverage_complete=evidence.coverage_complete,
        budgets=evidence.budgets,
        mappings=evidence.mappings,
        sources=tuple(ViewSource.from_source(source) for source in evidence.sources),
        records=tuple(_view_record(record) for record in returned),
        record_selection=RecordSelection(
            max_records_returned=max_records_returned,
            collected=_tally([record.time.status for record in evidence.records]),
            returned=_tally([record.time.status for record in returned]),
            omitted=_tally([record.time.status for record in omitted]),
            omitted_in_window_from_utc=min(omitted_in_window) if omitted_in_window else None,
        ),
    )


def view_to_json(view: IncidentEvidenceView) -> dict[str, Any]:
    """Return the JSON-ready form used by golden fixtures and clients."""
    return view.model_dump(mode="json", by_alias=True)


def canonical_view_json(view: IncidentEvidenceView, *, indent: int | None = None) -> str:
    """Deterministic ASCII JSON of a validated view."""
    payload = view_to_json(IncidentEvidenceView.model_validate(view_to_json(view)))
    separators = (",", ":") if indent is None else (",", ": ")
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=separators, indent=indent)


def incident_evidence_view_json_schema() -> dict[str, Any]:
    """JSON Schema for the serialized view (committed as a drift-tested artifact)."""
    schema = IncidentEvidenceView.model_json_schema(mode="serialization", by_alias=True)
    schema["$id"] = f"urn:unifi-mcp:{INCIDENT_EVIDENCE_VIEW_SCHEMA}:v{INCIDENT_EVIDENCE_VIEW_SCHEMA_VERSION}"
    return schema


class EvidencePresentation(BaseModel):
    """How an adapter returns collected evidence: the bounded view, or the full document.

    Validated with the collection request, before any controller I/O.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: EvidenceDetail = Field(
        default=EvidenceDetail.VIEW,
        description=(
            "view (default): every source's coverage and failures plus a bounded list of compact record "
            "citations; full: the complete unifi-incident-evidence document"
        ),
    )
    max_records_returned: int | None = Field(
        default=None,
        ge=1,
        le=MAX_RECORDS_RETURNED,
        description=(
            f"Most records the view returns (default {DEFAULT_MAX_RECORDS_RETURNED}, at most "
            f"{MAX_RECORDS_RETURNED}); omitted records are counted, never dropped from coverage. View only"
        ),
    )

    @model_validator(mode="after")
    def _view_only(self) -> EvidencePresentation:
        if self.detail is EvidenceDetail.FULL and self.max_records_returned is not None:
            raise ValueError("max_records_returned applies only to detail=view")
        return self

    def render(self, evidence: IncidentEvidence) -> dict[str, Any]:
        """The JSON payload an adapter returns for ``evidence``."""
        if self.detail is EvidenceDetail.FULL:
            return evidence_to_json(evidence)
        limit = self.max_records_returned or DEFAULT_MAX_RECORDS_RETURNED
        return view_to_json(client_view(evidence, max_records_returned=limit))
