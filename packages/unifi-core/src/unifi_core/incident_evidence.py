"""Versioned incident evidence contract shared by every incident surface.

One closed, cross-product model describes what a bounded read-only
investigation observed, where each observation came from, and what could not
be checked. Product normalizers (``unifi_core.network.incident_evidence`` and
``unifi_core.protect.incident_evidence``) turn raw product payloads into these
records; MCP tools, API routes, the relay and the worker consume the result.
This module performs no controller I/O and never imports app packages.

Contract rules encoded here (see ``docs/incident-evidence.md``):

- Windows are half-open: ``start <= t < end``, compared in UTC at the
  timestamp's stated precision.
- Collection time never substitutes for event time. Missing, malformed,
  timezone-less and out-of-window timestamps are explicit states.
- Mappings come only from exact identifier assertions. Names and nearby
  timestamps never establish a mapping.
- A source's retrieved count is a population total only when its coverage is
  complete. Total failure is ``failed``, never ``empty``; incomplete evidence
  is never ``coverage_complete``.
- Records are ordered by UTC time, then product, source, source record ID and
  evidence ID; records without a usable time sort last.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from unifi_core.exceptions import http_status
from unifi_core.mac import canonical_mac
from unifi_core.redaction import is_sensitive_key
from unifi_core.support_bundle import ErrorCategory, classify_error

INCIDENT_EVIDENCE_SCHEMA = "unifi-incident-evidence"
INCIDENT_EVIDENCE_SCHEMA_VERSION = 1

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")
_SOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_ISO_RE = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})[T ](?P<hm>[0-9]{2}:[0-9]{2})"
    r"(?::(?P<sec>[0-9]{2})(?:\.(?P<frac>[0-9]{1,6}))?)?"
    r"(?P<tz>Z|z|[+-][0-9]{2}:?[0-9]{2})?$"
)
_DIGITS_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")
# Plausible epoch magnitudes: seconds cover 1973-5138, milliseconds 1973-5138.
# Anything outside both ranges cannot be told apart from a counter or a sentinel.
_EPOCH_SECONDS_MIN = Decimal(10) ** 8
_EPOCH_MILLIS_MIN = Decimal(10) ** 11
_EPOCH_MILLIS_MAX = Decimal(10) ** 14

# HTTP statuses meaning "this controller has no such endpoint".
_UNSUPPORTED_STATUSES = frozenset({404, 405, 501})


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class Product(str, Enum):
    NETWORK = "network"
    PROTECT = "protect"
    # Reserved so a consumer can report an Access source as unsupported; no
    # Access normalizer exists yet.
    ACCESS = "access"


class ApiFamily(str, Enum):
    """API surfaces with disjoint ID and auth models (see AGENTS.md)."""

    NETWORK_V2_CONTROLLER = "network_v2_controller"
    NETWORK_INTEGRATION = "network_integration"
    ALARM_MANAGER_V2 = "alarm_manager_v2"
    PROTECT_PRIVATE = "protect_private"
    PROTECT_PUBLIC = "protect_public"


class TimeStatus(str, Enum):
    IN_WINDOW = "in_window"
    OUT_OF_WINDOW = "out_of_window"
    MISSING = "missing"
    MALFORMED = "malformed"
    AMBIGUOUS_TIMEZONE = "ambiguous_timezone"


class TimestampFormat(str, Enum):
    EPOCH_SECONDS = "epoch_seconds"
    EPOCH_MILLISECONDS = "epoch_milliseconds"
    ISO8601 = "iso8601"
    UNRECOGNIZED = "unrecognized"


class TimezoneBasis(str, Enum):
    EPOCH_UTC = "epoch_utc"
    EXPLICIT_OFFSET = "explicit_offset"
    NONE = "none"


class TimePrecision(str, Enum):
    SECOND = "second"
    MILLISECOND = "millisecond"
    MICROSECOND = "microsecond"
    MINUTE = "minute"


class OriginalType(str, Enum):
    ABSENT = "absent"
    NULL = "null"
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


class EntityKind(str, Enum):
    NETWORK_CLIENT = "network_client"
    NETWORK_DEVICE = "network_device"
    # A MAC whose client-or-device role the source did not state.
    NETWORK_STATION = "network_station"
    CAMERA = "camera"
    LOCATION = "location"


class IdKind(str, Enum):
    MAC = "mac"
    PROTECT_CAMERA_ID = "protect_camera_id"
    NETWORK_DEVICE_ID = "network_device_id"
    LOCATION_ID = "location_id"


class MappingStatus(str, Enum):
    VERIFIED = "verified"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"
    NOT_EVALUATED = "not_evaluated"


class MappingSource(str, Enum):
    OPERATOR_INPUT = "operator_input"
    PRODUCT_INVENTORY = "product_inventory"


class FailureKind(str, Enum):
    UNAVAILABLE = "unavailable"
    AUTH_FAILED = "auth_failed"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    PARSE_FAILED = "parse_failed"
    PARTIAL_RESPONSE = "partial_response"
    BUDGET_EXHAUSTED = "budget_exhausted"


class SourceOutcome(str, Enum):
    COMPLETE = "complete"
    EMPTY = "empty"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    AUTH_FAILED = "auth_failed"
    PERMISSION_DENIED = "permission_denied"
    TIMEOUT = "timeout"
    UNSUPPORTED = "unsupported"
    PARSE_FAILED = "parse_failed"
    NOT_ATTEMPTED = "not_attempted"


_SUCCESS_OUTCOMES = frozenset({SourceOutcome.COMPLETE, SourceOutcome.EMPTY})
_DATA_OUTCOMES = _SUCCESS_OUTCOMES | {SourceOutcome.PARTIAL}
_FAILURE_OUTCOME_BY_KIND = {
    FailureKind.UNAVAILABLE: SourceOutcome.UNAVAILABLE,
    FailureKind.AUTH_FAILED: SourceOutcome.AUTH_FAILED,
    FailureKind.PERMISSION_DENIED: SourceOutcome.PERMISSION_DENIED,
    FailureKind.TIMEOUT: SourceOutcome.TIMEOUT,
    FailureKind.UNSUPPORTED: SourceOutcome.UNSUPPORTED,
    FailureKind.PARSE_FAILED: SourceOutcome.PARSE_FAILED,
    # A partial response that carried nothing usable is still a failed read.
    FailureKind.PARTIAL_RESPONSE: SourceOutcome.UNAVAILABLE,
    FailureKind.BUDGET_EXHAUSTED: SourceOutcome.NOT_ATTEMPTED,
}


class PartialReason(str, Enum):
    TRUNCATED = "truncated"
    TRUNCATION_UNKNOWN = "truncation_unknown"
    WINDOW_NOT_COVERED = "window_not_covered"
    WINDOW_COVERAGE_UNKNOWN = "window_coverage_unknown"
    MALFORMED_RECORDS = "malformed_records"
    UNTIMED_RECORDS = "untimed_records"
    PARTIAL_RESPONSE = "partial_response"
    BUDGET_EXHAUSTED = "budget_exhausted"


class Truncation(str, Enum):
    NOT_TRUNCATED = "not_truncated"
    TRUNCATED = "truncated"
    UNKNOWN = "unknown"


class WindowCoverage(str, Enum):
    COVERED = "covered"
    NOT_COVERED = "not_covered"
    UNKNOWN = "unknown"


class BudgetKind(str, Enum):
    WINDOW = "window"
    EVENTS = "events"
    CALLS = "calls"
    ELAPSED = "elapsed"


class OverallStatus(str, Enum):
    COMPLETE = "complete"
    EMPTY = "empty"
    PARTIAL = "partial"
    FAILED = "failed"


ScalarValue = StrictStr | StrictInt | StrictFloat | StrictBool | None
AttributeValue = ScalarValue | tuple[StrictStr, ...]
QueryValue = ScalarValue | tuple[StrictStr | StrictInt | StrictFloat | StrictBool, ...]


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def format_utc(value: datetime) -> str:
    """Return the contract's fixed-width UTC form; lexical order is time order."""
    if value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_utc(value: str) -> datetime:
    """Parse a contract UTC string back to an aware datetime."""
    if not isinstance(value, str) or not _UTC_RE.match(value):
        raise ValueError("expected fixed-width UTC timestamp YYYY-MM-DDTHH:MM:SS.ffffffZ")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def _check_utc(value: str | None) -> str | None:
    if value is not None:
        parse_utc(value)
    return value


class TimeWindow(_ClosedModel):
    """Half-open UTC interval ``[start, end)``; the boundary flags are fixed."""

    start: str
    end: str
    start_inclusive: Literal[True] = True
    end_inclusive: Literal[False] = False

    @field_validator("start", "end")
    @classmethod
    def _utc(cls, value: str) -> str:
        return _check_utc(value)

    @model_validator(mode="after")
    def _ordered(self) -> TimeWindow:
        if self.start >= self.end:
            raise ValueError("window start must be before end")
        return self

    @classmethod
    def from_datetimes(cls, start: datetime, end: datetime) -> TimeWindow:
        return cls(start=format_utc(start), end=format_utc(end))

    @property
    def duration_seconds(self) -> float:
        return (parse_utc(self.end) - parse_utc(self.start)).total_seconds()

    def contains(self, utc: str) -> bool:
        return self.start <= utc < self.end

    def covers(self, other: TimeWindow) -> bool:
        return self.start <= other.start and self.end >= other.end


class EventTime(_ClosedModel):
    status: TimeStatus
    original_field: str | None
    original_type: OriginalType
    original_value: ScalarValue
    original_format: TimestampFormat | None
    utc: str | None
    utc_offset: str | None
    timezone_basis: TimezoneBasis | None
    precision: TimePrecision | None
    clock_uncertainty_ms: int | None = Field(default=None, ge=0)
    boundary_uncertain: bool = False

    @field_validator("utc")
    @classmethod
    def _utc(cls, value: str | None) -> str | None:
        return _check_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> EventTime:
        placed = self.status in (TimeStatus.IN_WINDOW, TimeStatus.OUT_OF_WINDOW)
        if placed != (self.utc is not None):
            raise ValueError("only in-window and out-of-window times carry a UTC value")
        if self.status is TimeStatus.MISSING and self.original_type not in (OriginalType.ABSENT, OriginalType.NULL):
            raise ValueError("a missing time has no original value")
        if self.boundary_uncertain and not placed:
            raise ValueError("boundary uncertainty applies only to placed times")
        return self


def _original_type(value: Any, present: bool) -> OriginalType:
    if not present:
        return OriginalType.ABSENT
    if value is None:
        return OriginalType.NULL
    if isinstance(value, bool):
        return OriginalType.BOOLEAN
    if isinstance(value, int):
        return OriginalType.INTEGER
    if isinstance(value, float):
        return OriginalType.FLOAT
    if isinstance(value, str):
        return OriginalType.STRING
    if isinstance(value, Mapping):
        return OriginalType.OBJECT
    return OriginalType.ARRAY


@dataclass(frozen=True)
class _ParsedTime:
    utc: datetime
    fmt: TimestampFormat
    basis: TimezoneBasis
    offset: str | None
    precision: TimePrecision


def _parse_epoch(text: str) -> _ParsedTime | None:
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite() or number < _EPOCH_SECONDS_MIN or number >= _EPOCH_MILLIS_MAX:
        return None
    fractional = number != number.to_integral_value()
    if number < _EPOCH_MILLIS_MIN:
        fmt, micros = TimestampFormat.EPOCH_SECONDS, number * 1_000_000
        precision = TimePrecision.MICROSECOND if fractional else TimePrecision.SECOND
    else:
        fmt, micros = TimestampFormat.EPOCH_MILLISECONDS, number * 1_000
        precision = TimePrecision.MICROSECOND if fractional else TimePrecision.MILLISECOND
    whole = int(micros.to_integral_value(rounding="ROUND_HALF_EVEN"))
    return _ParsedTime(_EPOCH + timedelta(microseconds=whole), fmt, TimezoneBasis.EPOCH_UTC, None, precision)


def _parse_iso(text: str) -> _ParsedTime | TimeStatus:
    match = _ISO_RE.match(text)
    if not match:
        return TimeStatus.MALFORMED
    tz = match.group("tz")
    if tz is None:
        return TimeStatus.AMBIGUOUS_TIMEZONE
    frac = match.group("frac")
    if match.group("sec") is None:
        precision = TimePrecision.MINUTE
    elif frac is None:
        precision = TimePrecision.SECOND
    elif len(frac) <= 3:
        precision = TimePrecision.MILLISECOND
    else:
        precision = TimePrecision.MICROSECOND
    if tz in ("Z", "z"):
        offset = "+00:00"
    else:
        digits = tz[1:].replace(":", "")
        offset = f"{tz[0]}{digits[:2]}:{digits[2:]}"
    normalized = (
        f"{match.group('date')}T{match.group('hm')}:{match.group('sec') or '00'}.{(frac or '').ljust(6, '0')}{offset}"
    )
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return TimeStatus.MALFORMED
    return _ParsedTime(
        parsed.astimezone(timezone.utc), TimestampFormat.ISO8601, TimezoneBasis.EXPLICIT_OFFSET, offset, precision
    )


_ABSENT: Any = object()


def parse_event_time(
    field_name: str | None,
    value: Any,
    *,
    window: TimeWindow,
    clock_uncertainty_ms: int | None = None,
) -> EventTime:
    """Normalize one event timestamp exactly as the source returned it.

    ``value`` may be the module sentinel for an absent field. Epoch units are
    inferred from magnitude (seconds below 1e11, milliseconds below 1e14);
    values outside both ranges, booleans, non-finite numbers, containers and
    unparseable strings are malformed. ISO strings without an offset are
    ``ambiguous_timezone`` rather than silently assumed to be UTC.
    """
    present = value is not _ABSENT
    original_type = _original_type(value, present)
    scalar = value if present and original_type not in (OriginalType.OBJECT, OriginalType.ARRAY) else None
    if isinstance(scalar, float) and not math.isfinite(scalar):
        scalar = None

    def _state(status: TimeStatus, fmt: TimestampFormat | None = None) -> EventTime:
        return EventTime(
            status=status,
            original_field=field_name,
            original_type=original_type,
            original_value=scalar,
            original_format=fmt,
            utc=None,
            utc_offset=None,
            timezone_basis=None,
            precision=None,
            clock_uncertainty_ms=clock_uncertainty_ms,
        )

    if original_type in (OriginalType.ABSENT, OriginalType.NULL):
        return _state(TimeStatus.MISSING)

    parsed: _ParsedTime | TimeStatus | None
    if original_type in (OriginalType.INTEGER, OriginalType.FLOAT):
        parsed = _parse_epoch(repr(value)) if scalar is not None else None
    elif original_type is OriginalType.STRING and _DIGITS_RE.match(value):
        parsed = _parse_epoch(value)
    elif original_type is OriginalType.STRING:
        parsed = _parse_iso(value)
    else:
        parsed = None

    if parsed is None:
        return _state(TimeStatus.MALFORMED, TimestampFormat.UNRECOGNIZED)
    if isinstance(parsed, TimeStatus):
        ambiguous = parsed is TimeStatus.AMBIGUOUS_TIMEZONE
        return _state(parsed, TimestampFormat.ISO8601 if ambiguous else TimestampFormat.UNRECOGNIZED)

    utc = format_utc(parsed.utc)
    boundary_uncertain = False
    if clock_uncertainty_ms:
        slack = timedelta(milliseconds=clock_uncertainty_ms)
        for edge in (parse_utc(window.start), parse_utc(window.end)):
            if abs(parsed.utc - edge) <= slack:
                boundary_uncertain = True
    return EventTime(
        status=TimeStatus.IN_WINDOW if window.contains(utc) else TimeStatus.OUT_OF_WINDOW,
        original_field=field_name,
        original_type=original_type,
        original_value=scalar,
        original_format=parsed.fmt,
        utc=utc,
        utc_offset=parsed.offset,
        timezone_basis=parsed.basis,
        precision=parsed.precision,
        clock_uncertainty_ms=clock_uncertainty_ms,
        boundary_uncertain=boundary_uncertain,
    )


# ---------------------------------------------------------------------------
# Provenance, entities and mapping
# ---------------------------------------------------------------------------


class Scope(_ClosedModel):
    controller_id: str | None = None
    site: str | None = None
    location_id: str | None = None


class EntityRef(_ClosedModel):
    kind: EntityKind
    id_kind: IdKind
    id: str = Field(min_length=1)
    role: str | None = None

    @property
    def identity(self) -> tuple[str, str]:
        """Exact-match identity; MACs compare case- and separator-insensitively."""
        if self.id_kind is IdKind.MAC:
            return (self.id_kind.value, canonical_mac(self.id) or self.id)
        return (self.id_kind.value, self.id)


class MappingAssertion(_ClosedModel):
    """An explicit, exact-identifier association supplied to the investigation."""

    entity: EntityRef
    target: EntityRef
    source: MappingSource


class MappingOutcome(_ClosedModel):
    status: MappingStatus
    targets: tuple[EntityRef, ...] = ()
    matched_on: tuple[EntityRef, ...] = ()
    sources: tuple[MappingSource, ...] = ()
    confidence: Literal["exact_identifier"] | None = None

    @model_validator(mode="after")
    def _consistent(self) -> MappingOutcome:
        if self.status is MappingStatus.VERIFIED:
            if len(self.targets) != 1 or self.confidence != "exact_identifier" or not self.matched_on:
                raise ValueError("a verified mapping names exactly one target matched on an exact identifier")
        elif self.status is MappingStatus.AMBIGUOUS:
            if len(self.targets) < 2 or self.confidence is not None:
                raise ValueError("an ambiguous mapping lists every candidate target and carries no confidence")
        elif self.targets or self.matched_on or self.sources or self.confidence is not None:
            raise ValueError("missing and unevaluated mappings carry no targets")
        return self


_NOT_EVALUATED = MappingOutcome(status=MappingStatus.NOT_EVALUATED)


def resolve_mapping(entities: Sequence[EntityRef], assertions: Sequence[MappingAssertion] | None) -> MappingOutcome:
    """Map a record's stated identifiers to incident targets by exact identity only."""
    if assertions is None:
        return _NOT_EVALUATED
    wanted = {entity.identity: entity for entity in entities}
    targets: dict[tuple[str, str], EntityRef] = {}
    matched: dict[tuple[str, str], EntityRef] = {}
    sources: set[MappingSource] = set()
    for assertion in assertions:
        hit = wanted.get(assertion.entity.identity)
        if hit is None:
            continue
        targets.setdefault(assertion.target.identity, assertion.target)
        matched.setdefault(hit.identity, hit)
        sources.add(assertion.source)
    if not targets:
        return MappingOutcome(status=MappingStatus.MISSING)
    ordered_targets = tuple(targets[key] for key in sorted(targets))
    ordered_matched = tuple(matched[key] for key in sorted(matched))
    ordered_sources = tuple(sorted(sources, key=lambda s: s.value))
    if len(ordered_targets) > 1:
        return MappingOutcome(
            status=MappingStatus.AMBIGUOUS,
            targets=ordered_targets,
            matched_on=ordered_matched,
            sources=ordered_sources,
        )
    return MappingOutcome(
        status=MappingStatus.VERIFIED,
        targets=ordered_targets,
        matched_on=ordered_matched,
        sources=ordered_sources,
        confidence="exact_identifier",
    )


def _drop_secret_keys(values: Mapping[str, Any], allowed: Callable[[Any], Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in sorted(values):
        if not isinstance(key, str) or is_sensitive_key(key):
            continue
        value = allowed(values[key])
        if value is not _ABSENT:
            cleaned[key] = value
    return cleaned


def _scalar_or_absent(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _ABSENT
    return _ABSENT


def _query_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        items = [_scalar_or_absent(item) for item in value]
        if any(item is _ABSENT or item is None for item in items):
            return _ABSENT
        return tuple(items)
    return _scalar_or_absent(value)


def _attribute_value(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return tuple(value) if all(isinstance(item, str) for item in value) else _ABSENT
    return _scalar_or_absent(value)


def clean_query(query: Mapping[str, Any]) -> dict[str, Any]:
    """Keep JSON-scalar query parameters; secret-named keys are excluded entirely."""
    return _drop_secret_keys(query, _query_value)


def clean_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Keep scalar or string-list attributes; secret-named keys are excluded entirely."""
    return _drop_secret_keys(attributes, _attribute_value)


def _no_secret_keys(values: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in values:
        if is_sensitive_key(key):
            raise ValueError("secret-named keys are not allowed in evidence")
    return values


class Provenance(_ClosedModel):
    product: Product
    api_family: ApiFamily | None
    source_tool: str | None
    endpoint: str | None
    scope: Scope
    source_record_id: StrictStr | StrictInt | None
    source_record_id_field: str | None
    query: dict[str, QueryValue]
    collected_at: str

    @field_validator("collected_at")
    @classmethod
    def _utc(cls, value: str) -> str:
        return _check_utc(value)

    @field_validator("query")
    @classmethod
    def _query(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(_no_secret_keys(value))


class EvidenceRecord(_ClosedModel):
    evidence_id: str
    evidence_id_basis: Literal["source_record_id", "content_hash"]
    source_id: str
    provenance: Provenance
    time: EventTime
    event_type: str | None
    summary: str | None
    entities: tuple[EntityRef, ...] = ()
    mapping: MappingOutcome = _NOT_EVALUATED
    attributes: dict[str, AttributeValue] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(_no_secret_keys(value))

    @model_validator(mode="after")
    def _identity(self) -> EvidenceRecord:
        has_id = self.provenance.source_record_id is not None
        if has_id != (self.evidence_id_basis == "source_record_id"):
            raise ValueError("evidence IDs derive from the source record ID exactly when one was returned")
        return self


def record_sort_key(record: EvidenceRecord) -> tuple[Any, ...]:
    """UTC order, untimed records last, then product, source and record ID."""
    rid = record.provenance.source_record_id
    return (
        record.time.utc is None,
        record.time.utc or "",
        record.provenance.product.value,
        record.source_id,
        "" if rid is None else str(rid),
        record.evidence_id,
    )


# ---------------------------------------------------------------------------
# Source coverage and failure
# ---------------------------------------------------------------------------


class SourceFailure(_ClosedModel):
    """Why a source failed; exception text is never carried."""

    kind: FailureKind
    http_status: int | None = Field(default=None, ge=100, le=599)


def failure_from_exception(exc: BaseException) -> SourceFailure:
    """Classify a collection exception without reading its message into evidence."""
    category, status, _ = classify_error(exc)
    status = status or http_status(exc)
    if status in _UNSUPPORTED_STATUSES:
        return SourceFailure(kind=FailureKind.UNSUPPORTED, http_status=status)
    kind = {
        ErrorCategory.AUTHENTICATION: FailureKind.AUTH_FAILED,
        ErrorCategory.PERMISSION: FailureKind.PERMISSION_DENIED,
        ErrorCategory.TIMEOUT: FailureKind.TIMEOUT,
        ErrorCategory.INVALID_RESPONSE: FailureKind.PARSE_FAILED,
    }.get(category, FailureKind.UNAVAILABLE)
    if kind is FailureKind.UNAVAILABLE and status == 401:
        kind = FailureKind.AUTH_FAILED
    elif kind is FailureKind.UNAVAILABLE and status == 403:
        kind = FailureKind.PERMISSION_DENIED
    return SourceFailure(kind=kind, http_status=status)


class Pagination(_ClosedModel):
    offset: int | None = Field(default=None, ge=0)
    cap: int | None = Field(default=None, ge=0)
    returned: int = Field(ge=0)
    has_more: bool | None = None
    total_reported: int | None = Field(default=None, ge=0)
    # The read broke off or never ran, so a short page proves nothing.
    interrupted: bool = False


class RecordCounts(_ClosedModel):
    received: int = Field(ge=0)
    accepted: int = Field(ge=0)
    in_window: int = Field(ge=0)
    out_of_window: int = Field(ge=0)
    untimed: int = Field(ge=0)
    malformed_dropped: int = Field(ge=0)
    duplicates_dropped: int = Field(ge=0)

    @model_validator(mode="after")
    def _balanced(self) -> RecordCounts:
        if self.received != self.accepted + self.malformed_dropped + self.duplicates_dropped:
            raise ValueError("received records must equal accepted + malformed + duplicate records")
        if self.accepted != self.in_window + self.out_of_window + self.untimed:
            raise ValueError("accepted records must equal in-window + out-of-window + untimed records")
        return self


def truncation_state(pagination: Pagination) -> Truncation:
    """Decide truncation from what the source reported, never from hope."""
    if pagination.has_more is True:
        return Truncation.TRUNCATED
    if pagination.total_reported is not None:
        seen = (pagination.offset or 0) + pagination.returned
        return Truncation.TRUNCATED if pagination.total_reported > seen else Truncation.NOT_TRUNCATED
    if pagination.interrupted:
        return Truncation.UNKNOWN
    if pagination.has_more is False:
        return Truncation.NOT_TRUNCATED
    if pagination.cap is not None and pagination.returned < pagination.cap:
        return Truncation.NOT_TRUNCATED
    return Truncation.UNKNOWN


class Coverage(_ClosedModel):
    requested_window: TimeWindow
    queried_window: TimeWindow | None
    window_coverage: WindowCoverage
    observed_first_utc: str | None
    observed_last_utc: str | None
    filters: dict[str, QueryValue]
    pagination: Pagination
    truncation: Truncation
    counts: RecordCounts
    complete: bool
    population_total: int | None = Field(ge=0)

    @field_validator("observed_first_utc", "observed_last_utc")
    @classmethod
    def _utc(cls, value: str | None) -> str | None:
        return _check_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> Coverage:
        expected_window = (
            WindowCoverage.UNKNOWN
            if self.queried_window is None
            else WindowCoverage.COVERED
            if self.queried_window.covers(self.requested_window)
            else WindowCoverage.NOT_COVERED
        )
        if self.window_coverage is not expected_window:
            raise ValueError("window coverage must follow from the requested and queried windows")
        if self.truncation is not truncation_state(self.pagination):
            raise ValueError("truncation must follow from the reported pagination")
        if self.pagination.returned != self.counts.received:
            raise ValueError("pagination.returned must equal the received record count")
        if self.complete and not (
            self.window_coverage is WindowCoverage.COVERED
            and self.truncation is Truncation.NOT_TRUNCATED
            and self.counts.malformed_dropped == 0
            and self.counts.untimed == 0
        ):
            raise ValueError("coverage is complete only when untruncated, window-covering and fully parsed")
        if (self.population_total is not None) != self.complete:
            raise ValueError("a retrieved count is a population total only when coverage is complete")
        if self.complete and self.population_total != self.counts.in_window:
            raise ValueError("population_total must equal the in-window record count")
        if (self.observed_first_utc is None) != (self.counts.in_window == 0):
            raise ValueError("observed bounds are present exactly when in-window records exist")
        return self


class SourceResult(_ClosedModel):
    source_id: str
    product: Product
    api_family: ApiFamily | None
    source_tool: str | None
    endpoint: str | None
    scope: Scope
    query: dict[str, QueryValue]
    collected_at: str
    outcome: SourceOutcome
    failure: SourceFailure | None
    partial_reasons: tuple[PartialReason, ...] = ()
    coverage: Coverage

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        if not _SOURCE_ID_RE.match(value):
            raise ValueError("source_id must be a short lowercase identifier")
        return value

    @field_validator("collected_at")
    @classmethod
    def _utc(cls, value: str) -> str:
        return _check_utc(value)

    @field_validator("query")
    @classmethod
    def _query(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(_no_secret_keys(value))

    @model_validator(mode="after")
    def _consistent(self) -> SourceResult:
        counts = self.coverage.counts
        if list(self.partial_reasons) != sorted(set(self.partial_reasons), key=lambda r: r.value):
            raise ValueError("partial_reasons must be sorted and unique")
        if self.outcome in _SUCCESS_OUTCOMES:
            if self.failure is not None or self.partial_reasons or not self.coverage.complete:
                raise ValueError("complete and empty sources need complete coverage and no failure")
            if (self.outcome is SourceOutcome.EMPTY) != (counts.in_window == 0):
                raise ValueError("a source is empty exactly when it has no in-window records")
        elif self.outcome is SourceOutcome.PARTIAL:
            if not self.partial_reasons or self.coverage.complete:
                raise ValueError("a partial source states why and has incomplete coverage")
            if (self.failure is not None) != (PartialReason.PARTIAL_RESPONSE in self.partial_reasons):
                raise ValueError("a partial source carries a failure exactly when its response broke off")
        else:
            if self.failure is None or _FAILURE_OUTCOME_BY_KIND[self.failure.kind] is not self.outcome:
                raise ValueError("a failed source carries the failure that matches its outcome")
            if counts.received or self.partial_reasons or self.coverage.complete:
                raise ValueError("a failed source carries no records and no coverage claim")
            if (
                self.coverage.window_coverage is not WindowCoverage.UNKNOWN
                or self.coverage.truncation is not Truncation.UNKNOWN
            ):
                raise ValueError("a failed source observed no window and cannot rule out truncation")
        return self


# ---------------------------------------------------------------------------
# Budgets and the evidence set
# ---------------------------------------------------------------------------


class BudgetLimits(_ClosedModel):
    window_seconds: int = Field(gt=0)
    events: int = Field(ge=0)
    calls: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)


class BudgetUsage(_ClosedModel):
    events: int = Field(default=0, ge=0)
    calls: int = Field(default=0, ge=0)
    elapsed_ms: int = Field(default=0, ge=0)


class Budgets(_ClosedModel):
    limits: BudgetLimits
    usage: BudgetUsage = BudgetUsage()
    exhausted: tuple[BudgetKind, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> Budgets:
        if list(self.exhausted) != sorted(set(self.exhausted), key=lambda k: k.value):
            raise ValueError("exhausted budgets must be sorted and unique")
        pairs = {
            BudgetKind.EVENTS: (self.usage.events, self.limits.events),
            BudgetKind.CALLS: (self.usage.calls, self.limits.calls),
            BudgetKind.ELAPSED: (self.usage.elapsed_ms, self.limits.elapsed_ms),
        }
        for kind, (used, limit) in pairs.items():
            if used > limit and kind not in self.exhausted:
                raise ValueError(f"{kind.value} budget overran its limit and must be reported exhausted")
            if kind in self.exhausted and used < limit:
                raise ValueError(f"{kind.value} budget is reported exhausted below its limit")
        return self


def _overall(sources: Sequence[SourceResult], budgets: Budgets) -> OverallStatus:
    outcomes = [source.outcome for source in sources]
    if not any(outcome in _DATA_OUTCOMES for outcome in outcomes):
        return OverallStatus.FAILED
    if budgets.exhausted or not all(outcome in _SUCCESS_OUTCOMES for outcome in outcomes):
        return OverallStatus.PARTIAL
    if all(outcome is SourceOutcome.EMPTY for outcome in outcomes):
        return OverallStatus.EMPTY
    return OverallStatus.COMPLETE


class IncidentEvidence(_ClosedModel):
    """A bounded, cited evidence set. ``coverage_complete`` gates any all-clear."""

    schema_name: Literal["unifi-incident-evidence"] = Field(default=INCIDENT_EVIDENCE_SCHEMA, alias="schema")
    schema_version: Literal[1] = INCIDENT_EVIDENCE_SCHEMA_VERSION
    requested_window: TimeWindow
    budgets: Budgets
    mappings: tuple[MappingAssertion, ...] | None = None
    sources: tuple[SourceResult, ...] = Field(min_length=1)
    records: tuple[EvidenceRecord, ...] = ()
    overall: OverallStatus
    coverage_complete: bool

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always", populate_by_name=True)

    @model_validator(mode="after")
    def _consistent(self) -> IncidentEvidence:
        source_ids = [source.source_id for source in self.sources]
        if source_ids != sorted(set(source_ids)):
            raise ValueError("sources must be sorted by unique source_id")
        by_id = {source.source_id: source for source in self.sources}
        per_source: dict[str, list[EvidenceRecord]] = {sid: [] for sid in source_ids}
        for record in self.records:
            if record.source_id not in by_id:
                raise ValueError("every record must cite a listed source")
            per_source[record.source_id].append(record)
        for sid, records in per_source.items():
            counts = by_id[sid].coverage.counts
            in_window = sum(1 for r in records if r.time.status is TimeStatus.IN_WINDOW)
            if len(records) != counts.accepted or in_window != counts.in_window:
                raise ValueError("record counts must match each source's coverage counts")
        ids = [record.evidence_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("evidence IDs must be unique")
        if list(self.records) != sorted(self.records, key=record_sort_key):
            raise ValueError("records must be in deterministic UTC order")
        if (self.budgets.limits.window_seconds < self.requested_window.duration_seconds) != (
            BudgetKind.WINDOW in self.budgets.exhausted
        ):
            raise ValueError("a requested window longer than the window budget must report window exhaustion")
        expected = _overall(self.sources, self.budgets)
        if self.overall is not expected:
            raise ValueError(f"overall status must be {expected.value} for these sources and budgets")
        if self.coverage_complete != (expected in (OverallStatus.COMPLETE, OverallStatus.EMPTY)):
            raise ValueError("coverage_complete is true only for complete or empty evidence")
        if self.mappings is None and any(r.mapping.status is not MappingStatus.NOT_EVALUATED for r in self.records):
            raise ValueError("mapping outcomes require the mapping assertions they were resolved against")
        return self


# ---------------------------------------------------------------------------
# Collection pipeline
# ---------------------------------------------------------------------------


class SourceContext(_ClosedModel):
    """What the collector knows about one source call, supplied to normalizers."""

    source_id: str
    product: Product
    api_family: ApiFamily | None
    source_tool: str | None = None
    endpoint: str | None = None
    scope: Scope = Scope()
    query: dict[str, QueryValue] = Field(default_factory=dict)
    filters: dict[str, QueryValue] = Field(default_factory=dict)
    collected_at: str
    requested_window: TimeWindow
    queried_window: TimeWindow | None = None
    offset: int | None = Field(default=None, ge=0)
    cap: int | None = Field(default=None, ge=0)
    has_more: bool | None = None
    total_reported: int | None = Field(default=None, ge=0)
    clock_uncertainty_ms: int | None = Field(default=None, ge=0)

    @field_validator("query", "filters", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return clean_query(value) if isinstance(value, Mapping) else value

    @field_validator("collected_at")
    @classmethod
    def _utc(cls, value: str) -> str:
        return _check_utc(value)


@dataclass(frozen=True)
class ExtractedRecord:
    """Product-neutral fields a normalizer extracts from one raw record."""

    record_id: str | int | None
    record_id_field: str | None
    time_field: str | None
    time_value: Any
    event_type: str | None
    summary: str | None
    entities: tuple[EntityRef, ...] = ()
    attributes: Mapping[str, Any] = field(default_factory=dict)


ABSENT = _ABSENT
"""Sentinel for a timestamp field the record did not contain."""


@dataclass(frozen=True)
class SourceEvidence:
    """One source's result plus the records it contributed."""

    source: SourceResult
    records: tuple[EvidenceRecord, ...]


def _content_hash(raw: Mapping[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _record_id(value: Any) -> str | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) or (isinstance(value, str) and value):
        return value
    return None


def collect_source(
    context: SourceContext,
    raw_records: Any,
    extractor: Callable[[Mapping[str, Any]], ExtractedRecord | None],
    *,
    failure: SourceFailure | None = None,
    budget_exhausted: bool = False,
) -> SourceEvidence:
    """Normalize one source's raw records into evidence with explicit coverage.

    ``failure`` marks a call that broke off after returning ``raw_records``
    (for example a timeout on a later page); ``budget_exhausted`` marks a call
    the collector stopped early. Either makes the source partial.
    """
    if not isinstance(raw_records, (list, tuple)):
        return source_failed(context, SourceFailure(kind=FailureKind.PARSE_FAILED))

    records: list[EvidenceRecord] = []
    seen: set[str] = set()
    malformed = duplicates = in_window = out_of_window = untimed = 0
    for raw in raw_records:
        if not isinstance(raw, Mapping):
            malformed += 1
            continue
        try:
            extracted = extractor(raw)
        except (TypeError, ValueError):
            extracted = None
        if extracted is None:
            malformed += 1
            continue
        record_id = _record_id(extracted.record_id)
        if record_id is not None:
            evidence_id = f"{context.source_id}:{record_id}"
        else:
            evidence_id = f"{context.source_id}:sha256:{_content_hash(raw)}"
        if evidence_id in seen:
            duplicates += 1
            continue
        seen.add(evidence_id)
        event_time = parse_event_time(
            extracted.time_field,
            extracted.time_value,
            window=context.requested_window,
            clock_uncertainty_ms=context.clock_uncertainty_ms,
        )
        if event_time.status is TimeStatus.IN_WINDOW:
            in_window += 1
        elif event_time.status is TimeStatus.OUT_OF_WINDOW:
            out_of_window += 1
        else:
            untimed += 1
        records.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                evidence_id_basis="source_record_id" if record_id is not None else "content_hash",
                source_id=context.source_id,
                provenance=Provenance(
                    product=context.product,
                    api_family=context.api_family,
                    source_tool=context.source_tool,
                    endpoint=context.endpoint,
                    scope=context.scope,
                    source_record_id=record_id,
                    source_record_id_field=extracted.record_id_field if record_id is not None else None,
                    query=context.query,
                    collected_at=context.collected_at,
                ),
                time=event_time,
                event_type=extracted.event_type,
                summary=extracted.summary,
                entities=extracted.entities,
                attributes=clean_attributes(extracted.attributes),
            )
        )

    counts = RecordCounts(
        received=len(raw_records),
        accepted=len(records),
        in_window=in_window,
        out_of_window=out_of_window,
        untimed=untimed,
        malformed_dropped=malformed,
        duplicates_dropped=duplicates,
    )
    if failure is not None and not records and not malformed:
        return source_failed(context, failure)
    records.sort(key=record_sort_key)
    return SourceEvidence(
        source=_source_result(context, counts, records, failure=failure, budget_exhausted=budget_exhausted),
        records=tuple(records),
    )


def _coverage(
    context: SourceContext,
    counts: RecordCounts,
    records: Sequence[EvidenceRecord],
    *,
    interrupted: bool,
    responded: bool = True,
) -> Coverage:
    pagination = Pagination(
        offset=context.offset,
        cap=context.cap,
        returned=counts.received,
        has_more=context.has_more,
        total_reported=context.total_reported,
        interrupted=interrupted,
    )
    truncation = truncation_state(pagination)
    # A source that never answered observed no window at all.
    queried = context.queried_window if responded else None
    window = (
        WindowCoverage.UNKNOWN
        if queried is None
        else WindowCoverage.COVERED
        if queried.covers(context.requested_window)
        else WindowCoverage.NOT_COVERED
    )
    complete = (
        not interrupted
        and window is WindowCoverage.COVERED
        and truncation is Truncation.NOT_TRUNCATED
        and counts.malformed_dropped == 0
        and counts.untimed == 0
    )
    placed = [r.time.utc for r in records if r.time.status is TimeStatus.IN_WINDOW]
    return Coverage(
        requested_window=context.requested_window,
        queried_window=queried,
        window_coverage=window,
        observed_first_utc=min(placed) if placed else None,
        observed_last_utc=max(placed) if placed else None,
        filters=context.filters,
        pagination=pagination,
        truncation=truncation,
        counts=counts,
        complete=complete,
        population_total=counts.in_window if complete else None,
    )


def _source_result(
    context: SourceContext,
    counts: RecordCounts,
    records: Sequence[EvidenceRecord],
    *,
    failure: SourceFailure | None,
    budget_exhausted: bool,
) -> SourceResult:
    coverage = _coverage(context, counts, records, interrupted=failure is not None or budget_exhausted)
    reasons: set[PartialReason] = set()
    if failure is not None:
        reasons.add(PartialReason.PARTIAL_RESPONSE)
    if budget_exhausted:
        reasons.add(PartialReason.BUDGET_EXHAUSTED)
    if coverage.truncation is Truncation.TRUNCATED:
        reasons.add(PartialReason.TRUNCATED)
    elif coverage.truncation is Truncation.UNKNOWN:
        reasons.add(PartialReason.TRUNCATION_UNKNOWN)
    if coverage.window_coverage is WindowCoverage.NOT_COVERED:
        reasons.add(PartialReason.WINDOW_NOT_COVERED)
    elif coverage.window_coverage is WindowCoverage.UNKNOWN:
        reasons.add(PartialReason.WINDOW_COVERAGE_UNKNOWN)
    if counts.malformed_dropped:
        reasons.add(PartialReason.MALFORMED_RECORDS)
    if counts.untimed:
        reasons.add(PartialReason.UNTIMED_RECORDS)
    if coverage.complete:
        outcome = SourceOutcome.EMPTY if counts.in_window == 0 else SourceOutcome.COMPLETE
        reasons.clear()
    else:
        outcome = SourceOutcome.PARTIAL
    return SourceResult(
        source_id=context.source_id,
        product=context.product,
        api_family=context.api_family,
        source_tool=context.source_tool,
        endpoint=context.endpoint,
        scope=context.scope,
        query=context.query,
        collected_at=context.collected_at,
        outcome=outcome,
        failure=failure,
        partial_reasons=tuple(sorted(reasons, key=lambda r: r.value)),
        coverage=coverage,
    )


def source_failed(context: SourceContext, failure: SourceFailure) -> SourceEvidence:
    """Record a source that produced no records; never an empty success."""
    counts = RecordCounts(
        received=0, accepted=0, in_window=0, out_of_window=0, untimed=0, malformed_dropped=0, duplicates_dropped=0
    )
    coverage = _coverage(context, counts, (), interrupted=True, responded=False)
    return SourceEvidence(
        source=SourceResult(
            source_id=context.source_id,
            product=context.product,
            api_family=context.api_family,
            source_tool=context.source_tool,
            endpoint=context.endpoint,
            scope=context.scope,
            query=context.query,
            collected_at=context.collected_at,
            outcome=_FAILURE_OUTCOME_BY_KIND[failure.kind],
            failure=failure,
            coverage=coverage,
        ),
        records=(),
    )


def records_from_tool_response(response: Any, path: Sequence[str]) -> list[Any] | SourceFailure:
    """Unwrap a standard MCP tool response envelope to its record list.

    Error envelopes carry only free text, so they map to ``unavailable``; the
    message is never inspected or copied into evidence.
    """
    if not isinstance(response, Mapping) or not isinstance(response.get("success"), bool):
        return SourceFailure(kind=FailureKind.PARSE_FAILED)
    if response["success"] is not True:
        return SourceFailure(kind=FailureKind.UNAVAILABLE)
    node: Any = response
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return SourceFailure(kind=FailureKind.PARSE_FAILED)
        node = node[key]
    if not isinstance(node, list):
        return SourceFailure(kind=FailureKind.PARSE_FAILED)
    return node


def assemble_incident_evidence(
    *,
    requested_window: TimeWindow,
    budgets: Budgets,
    sources: Iterable[SourceEvidence],
    mappings: Sequence[MappingAssertion] | None = None,
) -> IncidentEvidence:
    """Merge per-source evidence into one ordered, validated evidence set."""
    collected = sorted(sources, key=lambda s: s.source.source_id)
    for item in collected:
        if item.source.coverage.requested_window != requested_window:
            raise ValueError("every source must be collected against the evidence set's requested window")
    records = [
        record.model_copy(update={"mapping": resolve_mapping(record.entities, mappings)})
        for item in collected
        for record in item.records
    ]
    records.sort(key=record_sort_key)
    source_results = tuple(item.source for item in collected)
    overall = _overall(source_results, budgets)
    return IncidentEvidence(
        requested_window=requested_window,
        budgets=budgets,
        mappings=tuple(mappings) if mappings is not None else None,
        sources=source_results,
        records=tuple(records),
        overall=overall,
        coverage_complete=overall in (OverallStatus.COMPLETE, OverallStatus.EMPTY),
    )


def validate_incident_evidence(value: IncidentEvidence | Mapping[str, Any]) -> IncidentEvidence:
    """Validate a serialized evidence set against the closed contract."""
    if isinstance(value, IncidentEvidence):
        value = value.model_dump(mode="python", by_alias=True, round_trip=True)
    return IncidentEvidence.model_validate(value)


def evidence_to_json(value: IncidentEvidence) -> dict[str, Any]:
    """Return the JSON-ready form used by golden fixtures and consumers."""
    return value.model_dump(mode="json", by_alias=True)


def canonical_json(value: IncidentEvidence | Mapping[str, Any], *, indent: int | None = None) -> str:
    """Deterministic ASCII JSON after closed-schema validation."""
    payload = evidence_to_json(validate_incident_evidence(value))
    separators = (",", ":") if indent is None else (",", ": ")
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=separators, indent=indent)


def incident_evidence_json_schema() -> dict[str, Any]:
    """JSON Schema for the serialized contract (committed as a drift-tested artifact)."""
    schema = IncidentEvidence.model_json_schema(mode="serialization", by_alias=True)
    schema["$id"] = f"urn:unifi-mcp:{INCIDENT_EVIDENCE_SCHEMA}:v{INCIDENT_EVIDENCE_SCHEMA_VERSION}"
    return schema
