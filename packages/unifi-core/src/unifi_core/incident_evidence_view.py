"""Bounded client view of an incident evidence document.

A full ``unifi-incident-evidence`` document carries every record with its raw
attributes and provenance; at realistic budgets it outgrows what MCP clients
accept in one tool result. :func:`client_view` projects a validated document
into a ``unifi-incident-evidence-view`` that a client can read whole:

- ``overall``, ``coverage_complete``, budgets, mapping assertions and every
  source (outcome, failure, reasons and coverage) are copied unchanged, so
  every coverage and failure claim reads the same as in the full document.
  A source's labels (its tool and scope) longer than their limit are cut to
  a prefix and named in the source's ``truncated``.
- Records are compact citations (evidence ID, the conflict group of a
  version, product, source tool, source record ID, time and placement, type,
  summary, entities and mapping). Raw
  attributes and repeated provenance are dropped. Free text longer than its
  limit is cut to a prefix and named in the record's ``truncated``;
  identifiers are never cut, so a record whose citation cannot fit is
  skipped and counted as ``too_large`` instead.
- The view stays within :data:`VIEW_TOKEN_BUDGET` estimated tokens as an MCP
  tool result, whatever the document holds. A string costs one token per
  byte it is sent in, so no text costs fewer than it really uses;
  :data:`VIEW_BYTE_LIMIT` caps the bytes sent as a backstop. Records are
  taken in selection order (in-window records earliest first, then untimed,
  then out-of-window records; ties by evidence ID) until
  ``max_records_returned`` or the budget is reached; a record that cannot
  fit even as the view's first is counted as ``too_large``.
  ``record_selection`` counts what was collected, returned and omitted per
  placement; omission is a presentation limit, never missing coverage.
  ``next_cursor`` names the last record the view examined: passing it back as
  ``resume_after`` returns the records after it, so continuation always makes
  progress, even through records that share a timestamp.

Request validation bounds everything else the view repeats (sources, labels
and mapping assertions), so every valid request's view fits the budget. A
document whose sources and assertions alone would exceed it has no honest
view: :func:`client_view` raises :class:`EvidenceViewTooLarge` instead.

The projection is pure and deterministic and keeps no state between calls.
MCP tools, API routes, the relay and the worker return it by default;
``detail="full"`` returns the full document.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from unifi_core.incident_evidence import (
    CONFLICT_GROUP_PATTERN,
    EVIDENCE_ID_PATTERN,
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

#: Most estimated tokens (:func:`estimated_tokens`) a view takes as an MCP tool
#: result, ``{"success": true, "data": <view>}``: well under the roughly 25,000
#: tokens MCP clients accept in one result.
VIEW_TOKEN_BUDGET = 20_000
#: Most UTF-8 bytes (:func:`serialized_bytes`) a view takes as that MCP tool
#: result: four per budget token. Tokenizers average about four bytes a token
#: over ordinary text, and a view the estimate fits holds far fewer, since
#: every string byte is a token of its own. Only an estimate that undercounts
#: could pass it; such a view is refused rather than sent.
VIEW_BYTE_LIMIT = 4 * VIEW_TOKEN_BUDGET
#: Most estimated tokens one record citation takes. A record over it is never
#: returned: its identifiers cannot be cut without breaking the citation.
RECORD_TOKEN_LIMIT = 2_500
#: Longest evidence ID a returned record, and so a cursor, carries.
MAX_CITED_EVIDENCE_ID_LENGTH = 256
#: Estimated tokens kept of each source label: ``source_tool`` and the scope's
#: ``controller_id``, ``site`` and ``location_id``. An ASCII label request
#: validation accepts (at most 128 characters, none escaped in JSON) is never
#: cut; one with multi-byte characters is cut past 128 bytes.
SOURCE_LABEL_TOKEN_LIMIT = 128
#: Estimated tokens kept of each free-text field of a record citation; longer
#: text is cut to a prefix. A citation repeats its source's ``source_tool``.
TEXT_TOKEN_LIMITS: dict[str, int] = {
    "event_type": 40,
    "original_value": 40,
    "source_tool": SOURCE_LABEL_TOKEN_LIMIT,
    "summary": 200,
}
TruncatedField = Literal["event_type", "original_value", "source_tool", "summary"]
SourceTruncatedField = Literal["controller_id", "location_id", "site", "source_tool"]

_PLACED = (TimeStatus.IN_WINDOW, TimeStatus.OUT_OF_WINDOW)
_UTC = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z"
_EVIDENCE_ID_RE = re.compile(EVIDENCE_ID_PATTERN)
# A version's evidence ID is its conflict group's base identity plus this suffix.
_VERSION_SUFFIX = r"\|version\|[0-9a-f]{24}$"
_VERSION_SUFFIX_RE = re.compile(_VERSION_SUFFIX)
# One JSON document can state that a version names a group and nothing else
# does; that the group is the version's own base is a semantic check. Other
# records omit the key, so ordinary citations cost nothing more.
_VIEW_RECORD_RULES = {
    "if": {"properties": {"evidence_id": {"pattern": _VERSION_SUFFIX}}},
    "then": {"required": ["conflict_group"], "properties": {"conflict_group": {"type": "string"}}},
    "else": {"not": {"required": ["conflict_group"]}},
}
# <rank>|<utc>|<evidence_id>: rank 0 in-window, 1 untimed (no utc), 2 out-of-window.
_CURSOR_RE = re.compile(rf"^(?:[02]\|{_UTC}|1\|)\|(?P<evidence_id>.+)$")
MAX_CURSOR_LENGTH = 2 + 27 + 1 + MAX_CITED_EVIDENCE_ID_LENGTH


# --- estimated tokens ------------------------------------------------------------------------

# Every value is costed as an MCP server sends it: JSON indented by two spaces,
# non-ASCII text unescaped, quotes, backslashes and control characters escaped.
# A string value costs one token per byte it takes there. A byte-level
# tokenizer never needs more, so no text costs fewer estimated tokens than it
# really uses, however degenerate: long whitespace runs, repeated punctuation,
# letters in no word, multi-byte and emoji characters. Field names are the
# view's own schema names and the snake_case filter names a source records;
# they cost one token per four letters and per three digits, as words do, and
# every other character its bytes. The worker ports these functions exactly.

# What JSON escapes: \b \t \n \f \r, quotes and backslashes in two bytes,
# other control characters and lone surrogates in six.
_ESCAPED = re.compile(r'["\\\x00-\x1f\ud800-\udfff]')
_SHORT_ESCAPES = frozenset('"\\\b\t\n\f\r')
_NAME_PARTS = re.compile(r"[A-Za-z]+|[0-9]+|[\s\S]")


def _sent_bytes(text: str) -> int:
    """UTF-8 bytes ``text`` takes inside a JSON string as sent."""
    total = len(text.encode("utf-8", "surrogatepass"))
    for character in _ESCAPED.findall(text):
        if character in _SHORT_ESCAPES:
            total += 1
        else:
            # A control character (one byte) or lone surrogate (three) sent as \uXXXX.
            total += 5 if character < " " else 3
    return total


def _text_tokens(text: str) -> int:
    """Estimated tokens of a string value's text: one per byte as sent, as no token is shorter."""
    return _sent_bytes(text)


def _name_tokens(name: str) -> int:
    total = 0
    for part in _NAME_PARTS.findall(name):
        first = part[0]
        if "A" <= first <= "Z" or "a" <= first <= "z":
            total += -(-len(part) // 4)
        elif "0" <= first <= "9":
            total += -(-len(part) // 3)
        else:
            total += _sent_bytes(part)
    return total


def _integer_tokens(value: int) -> int:
    # One per digit; a sign and a float's ".0" are allowed for.
    return len(str(abs(value))) + 3


def estimated_tokens(value: Any) -> int:
    """Upper bound on the tokens a JSON-ready value takes as indented JSON."""
    if value is None:
        return 1
    if isinstance(value, bool):
        return 2
    if isinstance(value, int):
        return _integer_tokens(value)
    if isinstance(value, float):
        return _integer_tokens(int(value)) if value.is_integer() else 24
    if isinstance(value, str):
        return _text_tokens(value) + 2
    if isinstance(value, dict):
        return 3 + sum(6 + _name_tokens(key) + estimated_tokens(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return 3 + sum(2 + estimated_tokens(item) for item in value)
    raise TypeError(f"not a JSON value: {type(value).__name__}")


def serialized_bytes(value: Any, depth: int = 0) -> int:
    """UTF-8 bytes of a JSON-ready value as an MCP server sends it, at ``depth`` levels of indentation.

    Exact, except that a number is counted at its longest form: an integral
    one's digits, a sign and a float's ".0", any other 24 bytes. The worker,
    whose numbers do not say whether they are floats, counts them alike.
    """
    if value is None:
        return 4
    if isinstance(value, bool):
        return 4 if value else 5
    if isinstance(value, int):
        return _integer_tokens(value)
    if isinstance(value, float):
        return _integer_tokens(int(value)) if value.is_integer() else 24
    if isinstance(value, str):
        return _sent_bytes(value) + 2
    # Each member or item on its own line, indented one level deeper, then
    # the closing bracket on a line of its own.
    inner, outer = 1 + 2 * (depth + 1), 1 + 2 * depth
    if isinstance(value, dict):
        members = [inner + _sent_bytes(key) + 4 + serialized_bytes(item, depth + 1) for key, item in value.items()]
    elif isinstance(value, (list, tuple)):
        members = [inner + serialized_bytes(item, depth + 1) for item in value]
    else:
        raise TypeError(f"not a JSON value: {type(value).__name__}")
    return 2 + sum(members) + len(members) - 1 + outer if members else 2


# {"success": true, "data": <view>}, less the view itself.
_ENVELOPE_TOKENS = estimated_tokens({"success": True, "data": None}) - estimated_tokens(None)


def _cut(text: str, limit: int) -> str:
    """The longest prefix of ``text`` whose estimated tokens are at most ``limit``."""
    if _text_tokens(text) <= limit:
        return text
    # Every character costs at least a token, so no longer prefix fits.
    low, high = 0, min(len(text), limit)
    while low < high:
        middle = (low + high + 1) // 2
        if _text_tokens(text[:middle]) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low]


# --- model -----------------------------------------------------------------------------------


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


class EvidenceDetail(str, Enum):
    VIEW = "view"
    FULL = "full"


def _cursor_key(cursor: str) -> tuple[int, str, str]:
    """The selection key a cursor names; raises ``ValueError`` for anything else."""
    match = _CURSOR_RE.match(cursor) if len(cursor) <= MAX_CURSOR_LENGTH else None
    if match is None or not _EVIDENCE_ID_RE.match(match["evidence_id"]):
        raise ValueError("a cursor must be a next_cursor value returned by an evidence view")
    rank, utc, evidence_id = cursor.split("|", 2)
    return int(rank), utc, evidence_id


def _cursor(key: tuple[int, str, str]) -> str:
    return "|".join((str(key[0]), key[1], key[2]))


def _rank(status: TimeStatus) -> int:
    if status is TimeStatus.IN_WINDOW:
        return 0
    return 2 if status is TimeStatus.OUT_OF_WINDOW else 1


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
    """One record in citation form; ``evidence_id`` begins with its source ID.

    ``conflict_group`` is present on every version of one identity, as in the
    full document, and absent otherwise: records sharing it are differing
    versions, never distinct events. It is the evidence ID without its
    ``|version|<digest>`` suffix, so it is always shorter than the cited ID.
    ``truncated`` names each free-text field cut to a prefix, with its full
    length in characters; identifiers are never cut.
    """

    model_config = ConfigDict(json_schema_extra=_VIEW_RECORD_RULES)

    evidence_id: str
    conflict_group: str | None = Field(
        default=None, pattern=CONFLICT_GROUP_PATTERN, exclude_if=lambda group: group is None
    )
    product: Product
    source_tool: str | None
    source_record_id: StrictStr | StrictInt | None
    time: ViewTime
    event_type: str | None
    summary: str | None
    entity_ids: tuple[str, ...]
    mapping: ViewMapping
    truncated: dict[TruncatedField, int]

    @field_validator("truncated")
    @classmethod
    def _lengths(cls, value: dict[str, int]) -> dict[str, int]:
        if any(length < 1 for length in value.values()):
            raise ValueError("a truncated field states its full length")
        return value

    @model_validator(mode="after")
    def _conflict_group(self) -> ViewRecord:
        base = _VERSION_SUFFIX_RE.sub("", self.evidence_id)
        if (self.conflict_group is None) != (base == self.evidence_id) or (
            self.conflict_group is not None and self.conflict_group != base
        ):
            raise ValueError("a cited version names its own conflict group, and only versions name one")
        if self.conflict_group is None and "conflict_group" in self.model_fields_set:
            raise ValueError("a record outside any conflict group omits conflict_group rather than stating null")
        return self

    @property
    def selection_key(self) -> tuple[int, str, str]:
        return _rank(self.time.status), self.time.utc or "", self.evidence_id


class ViewSource(_ClosedModel):
    """A source's outcome, failure and coverage, exactly as in the full document.

    Request provenance (API family, endpoint, query, collection time) is left
    to the full document; nothing it states changes coverage. ``truncated``
    names each label (``source_tool`` or a scope field) cut to a prefix, with
    its full length in characters.
    """

    source_id: str
    product: Product
    source_tool: str | None
    scope: Scope
    outcome: SourceOutcome
    failure: SourceFailure | None
    partial_reasons: tuple[PartialReason, ...]
    coverage: Coverage
    truncated: dict[SourceTruncatedField, int]

    @field_validator("truncated")
    @classmethod
    def _lengths(cls, value: dict[str, int]) -> dict[str, int]:
        if any(length < 1 for length in value.values()):
            raise ValueError("a truncated label states its full length")
        return value


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
    """Which collected records the view returns; omission never reduces coverage.

    ``before_resume`` counts records at or before ``resume_after`` (shown by
    earlier views), ``omitted`` every other record not returned, including the
    ``too_large`` records this view skipped. ``next_cursor`` is set exactly
    when ``limited_by`` says which limit stopped the view.
    """

    max_records_returned: int = Field(ge=1, le=MAX_RECORDS_RETURNED)
    omission: Literal["presentation_limit"] = "presentation_limit"
    resume_after: str | None
    collected: RecordTally
    before_resume: RecordTally
    returned: RecordTally
    omitted: RecordTally
    too_large: int = Field(ge=0)
    limited_by: Literal["max_records_returned", "output_budget"] | None
    next_cursor: str | None

    @field_validator("resume_after", "next_cursor")
    @classmethod
    def _cursor_shape(cls, value: str | None) -> str | None:
        if value is not None:
            _cursor_key(value)
        return value

    @model_validator(mode="after")
    def _consistent(self) -> RecordSelection:
        for field in ("total", "in_window", "out_of_window", "untimed"):
            parts = (self.before_resume, self.returned, self.omitted)
            if sum(getattr(part, field) for part in parts) != getattr(self.collected, field):
                raise ValueError("records before the cursor, returned and omitted must add up to the collected records")
        if self.returned.total > self.max_records_returned:
            raise ValueError("a view returns at most max_records_returned records")
        if self.resume_after is None and self.before_resume.total:
            raise ValueError("records come before the cursor only when the view resumes after one")
        if self.too_large > self.omitted.total:
            raise ValueError("too_large records are omitted records")
        if (self.next_cursor is None) != (self.limited_by is None):
            raise ValueError("next_cursor is set exactly when a limit stopped the view")
        if self.next_cursor is not None and not self.omitted.total:
            raise ValueError("a view stopped by a limit has omitted records")
        if self.limited_by == "max_records_returned" and self.returned.total != self.max_records_returned:
            raise ValueError("a view stopped by max_records_returned returns that many records")
        if self.resume_after is not None and self.next_cursor is not None:
            if _cursor_key(self.next_cursor) <= _cursor_key(self.resume_after):
                raise ValueError("next_cursor must come after resume_after")
        return self


class EvidenceViewTooLarge(ValueError):
    """A document's sources and mapping assertions alone exceed the view's output budget.

    Also raised for a view over :data:`VIEW_BYTE_LIMIT`, which only an
    estimate that undercounts could produce.

    The message states only counts and how to narrow the request, never
    document content.
    """


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
        selection = self.record_selection
        collected = selection.collected
        counts = [source.coverage.counts for source in self.sources]
        if (collected.in_window, collected.out_of_window, collected.untimed) != (
            sum(c.in_window for c in counts),
            sum(c.out_of_window for c in counts),
            sum(c.untimed for c in counts),
        ):
            raise ValueError("collected records must equal the sources' accepted record counts")
        if _tally([record.time.status for record in self.records]) != selection.returned:
            raise ValueError("returned counts must describe the records in the view")
        prefixes = set(source_ids)
        if any(record.evidence_id.split("|", 1)[0] not in prefixes for record in self.records):
            raise ValueError("every record must cite a listed source")
        keys = [record.selection_key for record in self.records]
        if selection.resume_after is not None and any(key <= _cursor_key(selection.resume_after) for key in keys):
            raise ValueError("returned records must come after resume_after")
        if selection.next_cursor is not None and any(key > _cursor_key(selection.next_cursor) for key in keys):
            raise ValueError("returned records must not come after next_cursor")
        return self


# --- projection ------------------------------------------------------------------------------


def _view_source(source: SourceResult) -> dict[str, Any]:
    """A source's JSON form in the view, its labels cut to :data:`SOURCE_LABEL_TOKEN_LIMIT`."""
    shown = source.model_dump(mode="json", include=set(ViewSource.model_fields))
    truncated: dict[str, int] = {}

    def label(field: str, value: str | None) -> str | None:
        if value is None:
            return None
        cut = _cut(value, SOURCE_LABEL_TOKEN_LIMIT)
        if cut != value:
            truncated[field] = len(value)
        return cut

    shown["source_tool"] = label("source_tool", source.source_tool)
    shown["scope"] = {field: label(field, getattr(source.scope, field)) for field in Scope.model_fields}
    shown["truncated"] = truncated
    return shown


def _view_record(record: EvidenceRecord) -> dict[str, Any] | None:
    """A record's JSON citation, or None when its identifiers cannot be cited within the limit."""
    if len(record.evidence_id) > MAX_CITED_EVIDENCE_ID_LENGTH:
        return None
    identifiers = [entity.id for entity in record.entities] + [target.id for target in record.mapping.targets]
    # Every character costs at least a token.
    if sum(len(identifier) for identifier in identifiers) > RECORD_TOKEN_LIMIT:
        return None
    time = record.time
    truncated: dict[str, int] = {}

    def text(field: str, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        cut = _cut(value, TEXT_TOKEN_LIMITS[field])
        if cut != value:
            truncated[field] = len(value)
        return cut

    source_tool = text("source_tool", record.provenance.source_tool)
    event_type = text("event_type", record.event_type)
    original_value = text("original_value", time.original_value)
    summary = text("summary", record.summary)
    citation: dict[str, Any] = {"evidence_id": record.evidence_id}
    if record.conflict_group is not None:
        citation["conflict_group"] = record.conflict_group
    citation |= {
        "product": record.provenance.product.value,
        "source_tool": source_tool,
        "source_record_id": record.provenance.source_record_id,
        "time": {
            "status": time.status.value,
            "utc": time.utc,
            "boundary_uncertain": time.boundary_uncertain,
            "original_field": time.original_field,
            "original_type": time.original_type.value,
            "original_value": original_value,
        },
        "event_type": event_type,
        "summary": summary,
        "entity_ids": [entity.id for entity in record.entities],
        "mapping": {
            "status": record.mapping.status.value,
            "target_ids": [target.id for target in record.mapping.targets],
            "sources": [source.value for source in record.mapping.sources],
        },
        "truncated": truncated,
    }
    return citation if estimated_tokens(citation) <= RECORD_TOKEN_LIMIT else None


def _key(record: EvidenceRecord) -> tuple[int, str, str]:
    return _rank(record.time.status), record.time.utc or "", record.evidence_id


def client_view(
    evidence: IncidentEvidence,
    *,
    max_records_returned: int = DEFAULT_MAX_RECORDS_RETURNED,
    resume_after: str | None = None,
) -> IncidentEvidenceView:
    """Project a validated evidence set into its bounded client view.

    Records after ``resume_after`` are examined in selection order: in-window
    records earliest first, then untimed, then out-of-window records, ties by
    evidence ID. A record too large to cite, or to fit as the view's first,
    is skipped and counted; the rest are returned until
    ``max_records_returned`` or :data:`VIEW_TOKEN_BUDGET` is reached.
    Returned records keep the document's order.

    Raises :class:`EvidenceViewTooLarge` when the document's sources and
    mapping assertions alone, labels cut, exceed the budget, or when the view
    would exceed :data:`VIEW_BYTE_LIMIT` as sent.
    """
    evidence = validate_incident_evidence(evidence)
    records = evidence.records
    after = _cursor_key(resume_after) if resume_after is not None else None
    order = sorted(range(len(records)), key=lambda i: _key(records[i]))
    pending = [i for i in order if after is None or _key(records[i]) > after]

    sources = [_view_source(source) for source in evidence.sources]
    # The selection's numbers and cursor are not known until the end, so its
    # largest possible form is reserved up front.
    count = max(len(records), MAX_RECORDS_RETURNED)
    tally = {"total": count, "in_window": count, "out_of_window": count, "untimed": count}
    reserved_selection = {
        "max_records_returned": count,
        "omission": "presentation_limit",
        "resume_after": resume_after,
        "collected": tally,
        "before_resume": tally,
        "returned": tally,
        "omitted": tally,
        "too_large": count,
        "limited_by": "max_records_returned",
        "next_cursor": "-" * MAX_CURSOR_LENGTH,
    }
    skeleton = {
        "schema": INCIDENT_EVIDENCE_VIEW_SCHEMA,
        "schema_version": INCIDENT_EVIDENCE_VIEW_SCHEMA_VERSION,
        "evidence_schema_version": INCIDENT_EVIDENCE_SCHEMA_VERSION,
        "requested_window": evidence.requested_window.model_dump(mode="json"),
        "overall": evidence.overall.value,
        "coverage_complete": evidence.coverage_complete,
        "budgets": evidence.budgets.model_dump(mode="json"),
        "mappings": None if evidence.mappings is None else [m.model_dump(mode="json") for m in evidence.mappings],
        "sources": sources,
        "records": [],
        "record_selection": reserved_selection,
    }
    used = _ENVELOPE_TOKENS + estimated_tokens(skeleton)
    if used > VIEW_TOKEN_BUDGET:
        raise EvidenceViewTooLarge(
            f"the evidence view would exceed its {VIEW_TOKEN_BUDGET}-token output budget without any record "
            f"(sources: {len(sources)}, mapping assertions: {len(evidence.mappings or ())}); narrow the request "
            "to fewer sources (one location_id, fewer products or camera_ids) or fewer mapping assertions, "
            "or use detail=full for the whole document"
        )

    kept: dict[int, dict[str, Any]] = {}
    # Records too large to cite are counted once they lie before a returned
    # record, or when nothing after them is left; otherwise the next view,
    # resuming after the last returned record, examines and counts them.
    too_large = skipped = 0
    limited_by: Literal["max_records_returned", "output_budget"] | None = None
    for index in pending:
        citation = _view_record(records[index])
        if citation is None:
            skipped += 1
            continue
        if len(kept) == max_records_returned:
            limited_by = "max_records_returned"
            break
        cost = 2 + estimated_tokens(citation)
        if used + cost > VIEW_TOKEN_BUDGET:
            if kept:
                limited_by = "output_budget"
                break
            # Nothing is returned yet: the citation cannot fit beside the
            # view's sources, so it is too large, like one over the record limit.
            skipped += 1
            continue
        kept[index] = citation
        used += cost
        too_large, skipped = too_large + skipped, 0
    if limited_by is None:
        too_large += skipped

    returned = [records[i] for i in sorted(kept)]
    view_records = tuple(ViewRecord.model_validate(kept[i]) for i in sorted(kept))
    omitted = [records[i] for i in pending if i not in kept]
    before = [records[i] for i in order if after is not None and _key(records[i]) <= after]
    view = IncidentEvidenceView(
        requested_window=evidence.requested_window,
        overall=evidence.overall,
        coverage_complete=evidence.coverage_complete,
        budgets=evidence.budgets,
        mappings=evidence.mappings,
        sources=tuple(ViewSource.model_validate(source) for source in sources),
        records=view_records,
        record_selection=RecordSelection(
            max_records_returned=max_records_returned,
            resume_after=resume_after,
            collected=_tally([record.time.status for record in records]),
            before_resume=_tally([record.time.status for record in before]),
            returned=_tally([record.time.status for record in returned]),
            omitted=_tally([record.time.status for record in omitted]),
            too_large=too_large,
            limited_by=limited_by,
            # A limit stops the view only after it returned a record.
            next_cursor=_cursor(max(record.selection_key for record in view_records)) if limited_by else None,
        ),
    )
    if serialized_bytes({"success": True, "data": view_to_json(view)}) > VIEW_BYTE_LIMIT:
        raise EvidenceViewTooLarge(
            f"the evidence view would exceed its {VIEW_BYTE_LIMIT}-byte output limit (sources: {len(sources)}, "
            f"records: {len(view_records)}); request fewer records with max_records_returned, or use detail=full "
            "for the whole document"
        )
    return view


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
    resume_after: str | None = Field(
        default=None,
        max_length=MAX_CURSOR_LENGTH,
        description=(
            "record_selection.next_cursor from an earlier view of the same request; returns the records "
            "after it. View only"
        ),
    )

    @field_validator("resume_after")
    @classmethod
    def _cursor_shape(cls, value: str | None) -> str | None:
        if value is not None:
            _cursor_key(value)
        return value

    @model_validator(mode="after")
    def _view_only(self) -> EvidencePresentation:
        if self.detail is EvidenceDetail.FULL and (self.max_records_returned is not None or self.resume_after):
            raise ValueError("max_records_returned and resume_after apply only to detail=view")
        return self

    def render(self, evidence: IncidentEvidence) -> dict[str, Any]:
        """The JSON payload an adapter returns for ``evidence``."""
        if self.detail is EvidenceDetail.FULL:
            return evidence_to_json(evidence)
        limit = self.max_records_returned or DEFAULT_MAX_RECORDS_RETURNED
        return view_to_json(client_view(evidence, max_records_returned=limit, resume_after=self.resume_after))
