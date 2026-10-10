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
from urllib.parse import quote

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

from unifi_core.exceptions import UniFiMalformedResponseError, http_status
from unifi_core.mac import canonical_mac
from unifi_core.redaction import is_sensitive_key
from unifi_core.source_page import SourcePage
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
    BOUNDARY_UNCERTAIN = "boundary_uncertain"
    CONFLICTING_RECORDS = "conflicting_records"
    POST_FILTERED = "post_filtered"
    PREFIX_NOT_COLLECTED = "prefix_not_collected"
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
    return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


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


# JSON Schema rules mirroring the validators below, so schema-only consumers
# reject the same outcome and completeness contradictions. Checks that compare
# values across objects (time placement, counts, ordering, mapping
# recomputation) cannot be expressed here; see docs/incident-evidence.md.
def _when(condition: dict[str, Any], then: dict[str, Any], otherwise: dict[str, Any] | None = None) -> dict[str, Any]:
    rule: dict[str, Any] = {"if": condition, "then": then}
    if otherwise is not None:
        rule["else"] = otherwise
    return rule


def _props(**properties: Any) -> dict[str, Any]:
    return {"properties": properties}


_PLACED = ["in_window", "out_of_window"]
_SUCCESS = ["complete", "empty"]
_DATA = ["complete", "empty", "partial"]
_FAILED = ["unavailable", "auth_failed", "permission_denied", "timeout", "unsupported", "parse_failed", "not_attempted"]

_EVENT_TIME_RULES = {
    "allOf": [
        _when(
            _props(status={"enum": _PLACED}),
            _props(utc={"type": "string"}, precision={"type": "string"}),
            _props(utc={"type": "null"}, precision={"type": "null"}, boundary_uncertain={"const": False}),
        ),
        _when(_props(status={"const": "missing"}), _props(original_type={"enum": ["absent", "null"]})),
        _when(
            _props(status={"enum": ["malformed", "ambiguous_timezone", "missing"]}),
            _props(utc_offset={"type": "null"}, timezone_basis={"type": "null"}),
        ),
    ]
}
_MAPPING_RULES = {
    "allOf": [
        _when(
            _props(status={"const": "verified"}),
            _props(
                targets={"minItems": 1, "maxItems": 1},
                matched_on={"minItems": 1},
                confidence={"const": "exact_identifier"},
            ),
        ),
        _when(_props(status={"const": "ambiguous"}), _props(targets={"minItems": 2}, confidence={"type": "null"})),
        _when(
            _props(status={"enum": ["missing", "not_evaluated"]}),
            _props(
                targets={"maxItems": 0},
                matched_on={"maxItems": 0},
                sources={"maxItems": 0},
                confidence={"type": "null"},
            ),
        ),
    ]
}
_ZERO = {"const": 0}
_COVERAGE_RULES = {
    "allOf": [
        _when(
            _props(complete={"const": True}),
            _props(
                truncation={"const": "not_truncated"},
                window_coverage={"const": "covered"},
                population_total={"type": "integer"},
                pagination=_props(offset={"enum": [None, 0]}, interrupted={"const": False}),
                counts=_props(malformed_dropped=_ZERO, untimed=_ZERO, conflicting=_ZERO, boundary_uncertain=_ZERO),
            ),
            _props(population_total={"type": "null"}),
        ),
        _when(_props(queried_window={"type": "null"}), _props(window_coverage={"const": "unknown"})),
        # Only the source's own continuation flag or total proves the tail was read.
        _when(
            _props(truncation={"const": "not_truncated"}),
            _props(
                pagination={
                    **_props(interrupted={"const": False}),
                    "anyOf": [
                        _props(has_more={"const": False}),
                        _props(post_filtered={"const": False}, total_reported={"type": "integer"}),
                    ],
                }
            ),
        ),
        _when(
            _props(truncation={"const": "truncated"}),
            _props(
                pagination={
                    "anyOf": [
                        _props(has_more={"const": True}),
                        _props(post_filtered={"const": False}, total_reported={"type": "integer"}),
                    ]
                }
            ),
        ),
        _when(
            _props(counts=_props(in_window=_ZERO)),
            _props(observed_first_utc={"type": "null"}, observed_last_utc={"type": "null"}),
            _props(observed_first_utc={"type": "string"}, observed_last_utc={"type": "string"}),
        ),
        _when(_props(pagination=_props(has_more={"const": True})), _props(truncation={"const": "truncated"})),
        _when(
            _props(pagination=_props(interrupted={"const": True})),
            _props(truncation={"enum": ["truncated", "unknown"]}),
        ),
    ]
}
_FAILURE_KINDS_BY_OUTCOME = {
    "unavailable": ["unavailable", "partial_response"],
    "auth_failed": ["auth_failed"],
    "permission_denied": ["permission_denied"],
    "timeout": ["timeout"],
    "unsupported": ["unsupported"],
    "parse_failed": ["parse_failed"],
    "not_attempted": ["budget_exhausted"],
}
_SOURCE_RULES = {
    "allOf": [
        _when(
            _props(outcome={"enum": _SUCCESS}),
            _props(
                failure={"type": "null"}, partial_reasons={"maxItems": 0}, coverage=_props(complete={"const": True})
            ),
        ),
        _when(_props(outcome={"const": "empty"}), _props(coverage=_props(counts=_props(in_window=_ZERO)))),
        _when(
            _props(outcome={"const": "complete"}),
            _props(coverage=_props(counts=_props(in_window={"type": "integer", "minimum": 1}))),
        ),
        _when(
            _props(outcome={"const": "partial"}),
            _props(partial_reasons={"minItems": 1}, coverage=_props(complete={"const": False})),
        ),
        _when(
            {"required": ["failure"], **_props(outcome={"const": "partial"}, failure={"type": "object"})},
            _props(partial_reasons={"contains": {"const": "partial_response"}}),
        ),
        _when(
            _props(outcome={"enum": _FAILED}),
            _props(
                failure={"type": "object"},
                partial_reasons={"maxItems": 0},
                coverage=_props(
                    complete={"const": False},
                    window_coverage={"const": "unknown"},
                    truncation={"const": "unknown"},
                    queried_window={"type": "null"},
                    counts=_props(received=_ZERO),
                    pagination=_props(
                        interrupted={"const": True}, has_more={"type": "null"}, total_reported={"type": "null"}
                    ),
                ),
            ),
        ),
        *(
            _when(_props(outcome={"const": outcome}), _props(failure=_props(kind={"enum": kinds})))
            for outcome, kinds in _FAILURE_KINDS_BY_OUTCOME.items()
        ),
    ]
}
_NOT_IN_WINDOW = {"not": _props(time=_props(status={"const": "in_window"}))}
_EVIDENCE_RULES = {
    "allOf": [
        _when(_props(coverage_complete={"const": True}), _props(overall={"enum": _SUCCESS})),
        _when(_props(overall={"enum": _SUCCESS}), _props(coverage_complete={"const": True})),
        _when(
            _props(overall={"const": "empty"}),
            _props(
                sources={"items": _props(outcome={"const": "empty"})},
                budgets=_props(exhausted={"maxItems": 0}),
                records={"items": _NOT_IN_WINDOW},
            ),
        ),
        _when(
            _props(overall={"const": "complete"}),
            _props(
                sources={
                    "items": _props(outcome={"enum": _SUCCESS}),
                    "contains": _props(outcome={"const": "complete"}),
                },
                budgets=_props(exhausted={"maxItems": 0}),
            ),
        ),
        _when(
            _props(overall={"const": "failed"}),
            _props(sources={"items": _props(outcome={"enum": _FAILED})}, records={"maxItems": 0}),
        ),
        _when(
            _props(overall={"const": "partial"}),
            {
                **_props(sources={"contains": _props(outcome={"enum": _DATA})}),
                "anyOf": [
                    _props(sources={"contains": _props(outcome={"not": {"enum": _SUCCESS}})}),
                    _props(budgets=_props(exhausted={"minItems": 1})),
                ],
            },
        ),
        _when(
            {"required": ["mappings"], **_props(mappings={"type": "null"})},
            _props(records={"items": _props(mapping=_props(status={"const": "not_evaluated"}))}),
        ),
    ]
}


class EventTime(_ClosedModel):
    model_config = ConfigDict(json_schema_extra=_EVENT_TIME_RULES)

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
    frac = match.group("frac")
    # The calendar date and clock time must be valid before the timezone is judged.
    try:
        naive = datetime.fromisoformat(
            f"{match.group('date')}T{match.group('hm')}:{match.group('sec') or '00'}.{(frac or '').ljust(6, '0')}"
        )
    except ValueError:
        return TimeStatus.MALFORMED
    tz = match.group("tz")
    if tz is None:
        return TimeStatus.AMBIGUOUS_TIMEZONE
    if match.group("sec") is None:
        precision = TimePrecision.MINUTE
    elif frac is None:
        precision = TimePrecision.SECOND
    elif len(frac) <= 3:
        precision = TimePrecision.MILLISECOND
    else:
        precision = TimePrecision.MICROSECOND
    if tz in ("Z", "z"):
        sign, hours, minutes = 1, 0, 0
    else:
        digits = tz[1:].replace(":", "")
        sign, hours, minutes = (1 if tz[0] == "+" else -1), int(digits[:2]), int(digits[2:])
        if hours > 23 or minutes > 59:
            return TimeStatus.MALFORMED
    offset = f"{'+' if sign > 0 else '-'}{hours:02d}:{minutes:02d}"
    try:
        utc = naive.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes))).astimezone(timezone.utc)
    except OverflowError:
        return TimeStatus.MALFORMED
    return _ParsedTime(utc, TimestampFormat.ISO8601, TimezoneBasis.EXPLICIT_OFFSET, offset, precision)


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
    model_config = ConfigDict(json_schema_extra=_MAPPING_RULES)

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


# Keys in queries, filters and attributes: lowercase snake case, and never a
# name that could carry secret material. The deny pattern is a strict superset
# of ``unifi_core.redaction.is_sensitive_key`` for this grammar, so the JSON
# Schema (``propertyNames``) and Python enforce exactly the same rule.
EVIDENCE_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
EVIDENCE_KEY_DENY_PATTERN = r"pass|psk|secret|token|auth|cookie|key|community|pin|rtsp|crypt|configuration"
_EVIDENCE_KEY_RE = re.compile(EVIDENCE_KEY_PATTERN)
_EVIDENCE_KEY_DENY_RE = re.compile(EVIDENCE_KEY_DENY_PATTERN)
_KEY_NAMES_SCHEMA = {"propertyNames": {"pattern": EVIDENCE_KEY_PATTERN, "not": {"pattern": EVIDENCE_KEY_DENY_PATTERN}}}


def evidence_key_allowed(key: Any) -> bool:
    """Whether ``key`` may name a query parameter, filter or attribute in evidence."""
    return (
        isinstance(key, str)
        and _EVIDENCE_KEY_RE.fullmatch(key) is not None
        and _EVIDENCE_KEY_DENY_RE.search(key) is None
        and not is_sensitive_key(key)
    )


def _drop_secret_keys(values: Mapping[str, Any], allowed: Callable[[Any], Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key in sorted(values, key=str):
        if not evidence_key_allowed(key):
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
    """Keep JSON-scalar query parameters under allowed key names; others are excluded entirely."""
    return _drop_secret_keys(query, _query_value)


def clean_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    """Keep scalar or string-list attributes under allowed key names; others are excluded entirely."""
    return _drop_secret_keys(attributes, _attribute_value)


def _no_secret_keys(values: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in values:
        if not evidence_key_allowed(key):
            raise ValueError("secret-named or non-snake-case keys are not allowed in evidence")
    return values


# Evidence IDs are ``|``-separated, a character source IDs cannot contain, and
# record IDs are percent-encoded, so no two identities can collide:
#   <source_id>|int|<id>  or  <source_id>|str|<id>     a source record
#   <base>|version|<digest>                             one of several differing versions
#   <source_id>|sha256|<digest>                         a record without an ID
_DIGEST_RE = r"[0-9a-f]{24}"
_ENCODED_ID_RE = r"[A-Za-z0-9%._~-]+"
EVIDENCE_ID_PATTERN = (
    rf"^[a-z0-9][a-z0-9_.:-]{{0,127}}\|(?:(?:int|str)\|{_ENCODED_ID_RE}(?:\|version\|{_DIGEST_RE})?"
    rf"|sha256\|{_DIGEST_RE})$"
)
CONFLICT_GROUP_PATTERN = rf"^[a-z0-9][a-z0-9_.:-]{{0,127}}\|(?:int|str)\|{_ENCODED_ID_RE}$"


class Provenance(_ClosedModel):
    product: Product
    api_family: ApiFamily | None
    source_tool: str | None
    endpoint: str | None
    scope: Scope
    source_record_id: StrictStr | StrictInt | None
    source_record_id_field: str | None
    query: dict[str, QueryValue] = Field(json_schema_extra=_KEY_NAMES_SCHEMA)
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
    evidence_id: str = Field(pattern=EVIDENCE_ID_PATTERN)
    evidence_id_basis: Literal["source_record_id", "content_hash"]
    source_id: str
    provenance: Provenance
    time: EventTime
    event_type: str | None
    summary: str | None
    entities: tuple[EntityRef, ...] = ()
    mapping: MappingOutcome = _NOT_EVALUATED
    attributes: dict[str, AttributeValue] = Field(default_factory=dict, json_schema_extra=_KEY_NAMES_SCHEMA)
    # Set when the source returned differing records under one source record
    # ID; every version is kept and the group blocks complete coverage.
    conflict_group: str | None = Field(default=None, pattern=CONFLICT_GROUP_PATTERN)

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(_no_secret_keys(value))

    @model_validator(mode="after")
    def _identity(self) -> EvidenceRecord:
        record_id = self.provenance.source_record_id
        if (record_id is not None) != (self.evidence_id_basis == "source_record_id"):
            raise ValueError("evidence IDs derive from the source record ID exactly when one was returned")
        digest = self.digest()
        if record_id is None:
            if self.conflict_group is not None:
                raise ValueError("content-hash records cannot conflict")
            expected = content_identity(self.source_id, digest)
        else:
            base = record_identity(self.source_id, record_id)
            if self.conflict_group is None:
                expected = base
            elif self.conflict_group != base:
                raise ValueError("a conflict group is the base identity of its source record ID")
            else:
                expected = version_identity(base, digest)
        if self.evidence_id != expected:
            raise ValueError("evidence_id must follow from the typed source record ID or the evidence digest")
        return self

    def digest(self) -> str:
        """Hash of the record's own evidence content (see :func:`evidence_digest`)."""
        return evidence_digest(
            source_record_id=self.provenance.source_record_id,
            source_record_id_field=self.provenance.source_record_id_field,
            time=self.time,
            event_type=self.event_type,
            summary=self.summary,
            entities=self.entities,
            attributes=self.attributes,
        )


def record_identity(source_id: str, record_id: str | int) -> str:
    """Typed, escaped identity: integer 7 and string "7" are different source records."""
    kind = "int" if isinstance(record_id, int) else "str"
    return f"{source_id}|{kind}|{quote(str(record_id), safe='')}"


def version_identity(base: str, digest: str) -> str:
    return f"{base}|version|{digest}"


def content_identity(source_id: str, digest: str) -> str:
    return f"{source_id}|sha256|{digest}"


def evidence_digest(
    *,
    source_record_id: str | int | None,
    source_record_id_field: str | None,
    time: EventTime,
    event_type: str | None,
    summary: str | None,
    entities: Sequence[EntityRef],
    attributes: Mapping[str, Any],
) -> str:
    """Hash the sanitized evidence a record carries, never the raw payload.

    Fields the normalizers exclude (secrets, buffer stamps, recognized identity,
    display names) therefore cannot change identity or create conflicts. The
    time contributes only what the source returned, not window-derived state.
    """
    payload = {
        "source_record_id": None
        if source_record_id is None
        else ["int" if isinstance(source_record_id, int) else "str", source_record_id],
        "source_record_id_field": source_record_id_field,
        "time": [time.original_field, time.original_type.value, time.original_value],
        "event_type": event_type,
        "summary": summary,
        "entities": [entity.model_dump(mode="json") for entity in entities],
        "attributes": {key: list(value) if isinstance(value, tuple) else value for key, value in attributes.items()},
    }
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


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


def _valid_status(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599 else None


def failure_from_exception(exc: BaseException) -> SourceFailure:
    """Classify a collection exception without reading its message into evidence.

    Never raises: an exception whose rendering or attributes fail to classify
    is reported as ``unavailable``.
    """
    try:
        category, status, _ = classify_error(exc)
    except Exception:
        category, status = ErrorCategory.UNKNOWN, None
    status = _valid_status(status)
    if status is None:
        try:
            status = _valid_status(http_status(exc))
        except Exception:
            status = None
    if status in _UNSUPPORTED_STATUSES:
        return SourceFailure(kind=FailureKind.UNSUPPORTED, http_status=status)
    if isinstance(exc, UniFiMalformedResponseError):
        return SourceFailure(kind=FailureKind.PARSE_FAILED, http_status=status)
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
    # Records skipped before this read; anything but 0 means the prefix was not collected.
    offset: int | None = Field(default=None, ge=0)
    # The limit the caller asked for, and the cap the source actually applied.
    requested_cap: int | None = Field(default=None, ge=0)
    cap: int | None = Field(default=None, ge=0)
    returned: int = Field(ge=0)
    has_more: bool | None = None
    total_reported: int | None = Field(default=None, ge=0)
    # Records were filtered after the source applied its cap, so a short list proves nothing.
    post_filtered: bool = False
    # The read broke off or never ran, so a short page proves nothing.
    interrupted: bool = False

    @model_validator(mode="after")
    def _caps(self) -> Pagination:
        if self.cap is not None and self.requested_cap is not None and self.cap > self.requested_cap:
            raise ValueError("the effective cap cannot exceed the requested cap")
        return self

    @property
    def prefix_collected(self) -> bool:
        return not self.offset


class RecordCounts(_ClosedModel):
    received: int = Field(ge=0)
    accepted: int = Field(ge=0)
    in_window: int = Field(ge=0)
    out_of_window: int = Field(ge=0)
    untimed: int = Field(ge=0)
    malformed_dropped: int = Field(ge=0)
    duplicates_dropped: int = Field(ge=0)
    # Accepted records that are differing versions of one source record ID.
    conflicting: int = Field(default=0, ge=0)
    # Out-of-window records within known clock uncertainty of a window boundary.
    boundary_uncertain: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _balanced(self) -> RecordCounts:
        if self.received != self.accepted + self.malformed_dropped + self.duplicates_dropped:
            raise ValueError("received records must equal accepted + malformed + duplicate records")
        if self.accepted != self.in_window + self.out_of_window + self.untimed:
            raise ValueError("accepted records must equal in-window + out-of-window + untimed records")
        if self.conflicting > self.accepted or self.conflicting == 1:
            raise ValueError("conflicting records come in groups of accepted records")
        if self.boundary_uncertain > self.out_of_window:
            raise ValueError("only out-of-window records count as boundary-uncertain")
        return self


def truncation_state(pagination: Pagination) -> Truncation:
    """Decide whether the tail was cut off, from what the source reported, never from caps or hope."""
    if pagination.has_more is True:
        return Truncation.TRUNCATED
    if pagination.total_reported is not None and not pagination.post_filtered:
        seen = (pagination.offset or 0) + pagination.returned
        if pagination.total_reported > seen:
            return Truncation.TRUNCATED
        if not pagination.interrupted:
            return Truncation.NOT_TRUNCATED
    if pagination.interrupted:
        return Truncation.UNKNOWN
    if pagination.has_more is False:
        return Truncation.NOT_TRUNCATED
    # A cap alone never proves the source ran out: only the source's own
    # continuation flag or total does.
    return Truncation.UNKNOWN


def coverage_is_complete(
    *,
    window_coverage: WindowCoverage,
    truncation: Truncation,
    pagination: Pagination,
    counts: RecordCounts,
) -> bool:
    """The single rule for when a source's retrieved records are the whole population."""
    return (
        window_coverage is WindowCoverage.COVERED
        and truncation is Truncation.NOT_TRUNCATED
        and pagination.prefix_collected
        and not pagination.interrupted
        and counts.malformed_dropped == 0
        and counts.untimed == 0
        and counts.conflicting == 0
        and counts.boundary_uncertain == 0
    )


def _window_coverage(queried: TimeWindow | None, requested: TimeWindow) -> WindowCoverage:
    if queried is None:
        return WindowCoverage.UNKNOWN
    return WindowCoverage.COVERED if queried.covers(requested) else WindowCoverage.NOT_COVERED


class Coverage(_ClosedModel):
    model_config = ConfigDict(json_schema_extra=_COVERAGE_RULES)

    requested_window: TimeWindow
    queried_window: TimeWindow | None
    window_coverage: WindowCoverage
    observed_first_utc: str | None
    observed_last_utc: str | None
    filters: dict[str, QueryValue] = Field(json_schema_extra=_KEY_NAMES_SCHEMA)
    pagination: Pagination
    truncation: Truncation
    counts: RecordCounts
    complete: bool
    population_total: int | None = Field(ge=0)

    @field_validator("observed_first_utc", "observed_last_utc")
    @classmethod
    def _utc(cls, value: str | None) -> str | None:
        return _check_utc(value)

    @field_validator("filters")
    @classmethod
    def _filters(cls, value: dict[str, Any]) -> dict[str, Any]:
        return dict(_no_secret_keys(value))

    @model_validator(mode="after")
    def _consistent(self) -> Coverage:
        if self.window_coverage is not _window_coverage(self.queried_window, self.requested_window):
            raise ValueError("window coverage must follow from the requested and queried windows")
        if self.truncation is not truncation_state(self.pagination):
            raise ValueError("truncation must follow from the reported pagination")
        if self.pagination.returned != self.counts.received:
            raise ValueError("pagination.returned must equal the received record count")
        expected = coverage_is_complete(
            window_coverage=self.window_coverage,
            truncation=self.truncation,
            pagination=self.pagination,
            counts=self.counts,
        )
        if self.complete != expected:
            raise ValueError("coverage.complete must follow from the window, pagination and counts")
        if (self.population_total is not None) != self.complete:
            raise ValueError("a retrieved count is a population total only when coverage is complete")
        if self.complete and self.population_total != self.counts.in_window:
            raise ValueError("population_total must equal the in-window record count")
        no_records = self.counts.in_window == 0
        if (self.observed_first_utc is None) != no_records or (self.observed_last_utc is None) != no_records:
            raise ValueError("observed bounds are present exactly when in-window records exist")
        if self.observed_first_utc is not None and self.observed_first_utc > self.observed_last_utc:
            raise ValueError("observed bounds must be ordered")
        return self


def coverage_reasons(coverage: Coverage, *, broke_off: bool, budget_exhausted: bool) -> set[PartialReason]:
    """Every reason a source's coverage falls short of the whole population."""
    reasons: set[PartialReason] = set()
    if broke_off:
        reasons.add(PartialReason.PARTIAL_RESPONSE)
    if budget_exhausted:
        reasons.add(PartialReason.BUDGET_EXHAUSTED)
    if coverage.truncation is Truncation.TRUNCATED:
        reasons.add(PartialReason.TRUNCATED)
    elif coverage.truncation is Truncation.UNKNOWN:
        reasons.add(PartialReason.TRUNCATION_UNKNOWN)
        if coverage.pagination.post_filtered:
            reasons.add(PartialReason.POST_FILTERED)
    if not coverage.pagination.prefix_collected:
        reasons.add(PartialReason.PREFIX_NOT_COLLECTED)
    if coverage.window_coverage is WindowCoverage.NOT_COVERED:
        reasons.add(PartialReason.WINDOW_NOT_COVERED)
    elif coverage.window_coverage is WindowCoverage.UNKNOWN:
        reasons.add(PartialReason.WINDOW_COVERAGE_UNKNOWN)
    counts = coverage.counts
    if counts.malformed_dropped:
        reasons.add(PartialReason.MALFORMED_RECORDS)
    if counts.untimed:
        reasons.add(PartialReason.UNTIMED_RECORDS)
    if counts.conflicting:
        reasons.add(PartialReason.CONFLICTING_RECORDS)
    if counts.boundary_uncertain:
        reasons.add(PartialReason.BOUNDARY_UNCERTAIN)
    return reasons


class SourceResult(_ClosedModel):
    model_config = ConfigDict(json_schema_extra=_SOURCE_RULES)

    source_id: str
    product: Product
    api_family: ApiFamily | None
    source_tool: str | None
    endpoint: str | None
    scope: Scope
    query: dict[str, QueryValue] = Field(json_schema_extra=_KEY_NAMES_SCHEMA)
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
            budget = PartialReason.BUDGET_EXHAUSTED in self.partial_reasons
            if (budget or self.failure is not None) != self.coverage.pagination.interrupted:
                raise ValueError("a read is interrupted exactly when it broke off or a budget stopped it")
            derived = coverage_reasons(self.coverage, broke_off=self.failure is not None, budget_exhausted=budget)
            if set(self.partial_reasons) != derived:
                raise ValueError("partial_reasons must be exactly the reasons the coverage establishes")
        else:
            if self.failure is None or _FAILURE_OUTCOME_BY_KIND[self.failure.kind] is not self.outcome:
                raise ValueError("a failed source carries the failure that matches its outcome")
            if counts.received or self.partial_reasons or self.coverage.complete:
                raise ValueError("a failed source carries no records and no coverage claim")
            pagination = self.coverage.pagination
            if (
                self.coverage.window_coverage is not WindowCoverage.UNKNOWN
                or self.coverage.truncation is not Truncation.UNKNOWN
                or self.coverage.queried_window is not None
                or not pagination.interrupted
                or pagination.has_more is not None
                or pagination.total_reported is not None
            ):
                raise ValueError("a failed source observed no window and makes no pagination claim")
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

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
        populate_by_name=True,
        json_schema_extra=_EVIDENCE_RULES,
    )

    @model_validator(mode="after")
    def _consistent(self) -> IncidentEvidence:
        source_ids = [source.source_id for source in self.sources]
        if source_ids != sorted(set(source_ids)):
            raise ValueError("sources must be sorted by unique source_id")
        by_id = {source.source_id: source for source in self.sources}
        for source in self.sources:
            if source.coverage.requested_window != self.requested_window:
                raise ValueError("every source must be collected against the evidence set's requested window")
        per_source: dict[str, list[EvidenceRecord]] = {sid: [] for sid in source_ids}
        for record in self.records:
            source = by_id.get(record.source_id)
            if source is None:
                raise ValueError("every record must cite a listed source")
            _check_record_against_source(record, source, self.requested_window)
            if record.mapping != resolve_mapping(record.entities, self.mappings):
                raise ValueError("each mapping outcome must equal resolving its entities against the assertions")
            per_source[record.source_id].append(record)
        for sid, records in per_source.items():
            _check_source_counts(by_id[sid].coverage, records)
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
        return self


def _reparsed_time(time: EventTime, window: TimeWindow) -> EventTime:
    """Recompute a record's time state from the original value it carries."""
    if time.original_type is OriginalType.ABSENT:
        value: Any = _ABSENT
    elif time.original_type is OriginalType.OBJECT:
        value = {}
    elif time.original_type is OriginalType.ARRAY:
        value = []
    elif time.original_type is OriginalType.FLOAT and time.original_value is None:
        value = math.nan
    else:
        value = time.original_value
    return parse_event_time(time.original_field, value, window=window, clock_uncertainty_ms=time.clock_uncertainty_ms)


def _check_record_against_source(record: EvidenceRecord, source: SourceResult, window: TimeWindow) -> None:
    provenance = record.provenance
    if (
        provenance.product is not source.product
        or provenance.api_family is not source.api_family
        or provenance.source_tool != source.source_tool
        or provenance.endpoint != source.endpoint
        or provenance.scope != source.scope
        or provenance.query != source.query
        or provenance.collected_at != source.collected_at
    ):
        raise ValueError("record provenance must match the source that produced it")
    if record.time != _reparsed_time(record.time, window):
        raise ValueError("a record's time state must follow from its original timestamp and the requested window")


def _check_source_counts(coverage: Coverage, records: Sequence[EvidenceRecord]) -> None:
    counts = coverage.counts
    statuses = [record.time.status for record in records]
    placed = sorted(r.time.utc for r in records if r.time.status is TimeStatus.IN_WINDOW)
    groups: dict[str, int] = {}
    for record in records:
        if record.conflict_group is not None:
            groups[record.conflict_group] = groups.get(record.conflict_group, 0) + 1
    observed = (
        len(records),
        statuses.count(TimeStatus.IN_WINDOW),
        statuses.count(TimeStatus.OUT_OF_WINDOW),
        len(records) - statuses.count(TimeStatus.IN_WINDOW) - statuses.count(TimeStatus.OUT_OF_WINDOW),
        sum(groups.values()),
        sum(1 for r in records if r.time.status is TimeStatus.OUT_OF_WINDOW and r.time.boundary_uncertain),
    )
    claimed = (
        counts.accepted,
        counts.in_window,
        counts.out_of_window,
        counts.untimed,
        counts.conflicting,
        counts.boundary_uncertain,
    )
    if observed != claimed:
        raise ValueError("record counts must match each source's coverage counts")
    if any(size < 2 for size in groups.values()):
        raise ValueError("a conflict group holds at least two differing versions")
    first, last = (placed[0], placed[-1]) if placed else (None, None)
    if (coverage.observed_first_utc, coverage.observed_last_utc) != (first, last):
        raise ValueError("observed bounds must be the earliest and latest in-window record times")


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
    # The limit the caller asked for, and the cap the source actually applied.
    requested_cap: int | None = Field(default=None, ge=0)
    cap: int | None = Field(default=None, ge=0)
    has_more: bool | None = None
    total_reported: int | None = Field(default=None, ge=0)
    post_filtered: bool = False
    clock_uncertainty_ms: int | None = Field(default=None, ge=0)

    @field_validator("query", "filters", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return clean_query(value) if isinstance(value, Mapping) else value

    @model_validator(mode="after")
    def _caps(self) -> SourceContext:
        if self.cap is not None and self.requested_cap is not None and self.cap > self.requested_cap:
            raise ValueError("the effective cap cannot exceed the requested cap")
        return self

    @field_validator("collected_at")
    @classmethod
    def _utc(cls, value: str) -> str:
        return _check_utc(value)


def window_from_epoch_ms(from_ms: int, to_ms: int) -> TimeWindow | None:
    """The window a source was asked for in epoch milliseconds, or None if it is empty."""
    if from_ms >= to_ms:
        return None
    return TimeWindow.from_datetimes(_EPOCH + timedelta(milliseconds=from_ms), _EPOCH + timedelta(milliseconds=to_ms))


def apply_source_page(context: SourceContext, page: SourcePage) -> SourceContext:
    """Carry what the manager observed about one read into the source context.

    Pagination facts (offset, transmitted cap, continuation flag, remote
    total, post-filtering) come from the page. When the page records the
    absolute bounds it submitted, they replace any window derived from clocks.
    """
    updates: dict[str, Any] = {
        "offset": page.offset if page.offset is not None else context.offset,
        "cap": page.cap if page.cap is not None else context.cap,
        "has_more": page.has_more,
        "total_reported": page.total_reported,
        "post_filtered": page.post_filtered or context.post_filtered,
    }
    if page.submitted_window_ms is not None:
        updates["queried_window"] = window_from_epoch_ms(*page.submitted_window_ms)
    return SourceContext.model_validate({**context.model_dump(), **updates})


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

    Records that carry the same evidence (see :func:`evidence_digest`) collapse;
    records with differing evidence under one typed source record ID are all
    kept as a conflict group, which blocks complete coverage. The result does
    not depend on input order. ``failure`` marks a call that broke off after
    returning ``raw_records`` (for example a timeout on a later page);
    ``budget_exhausted`` marks a call the collector stopped early. Either
    makes the source partial.
    """
    if not isinstance(raw_records, (list, tuple)):
        return source_failed(context, SourceFailure(kind=FailureKind.PARSE_FAILED))

    malformed = duplicates = 0
    groups: dict[str, dict[str, EvidenceRecord]] = {}
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
        record = _evidence_record(context, extracted)
        digest = record.digest()
        rid = record.provenance.source_record_id
        base = record_identity(context.source_id, rid) if rid is not None else record.evidence_id
        versions = groups.setdefault(base, {})
        if digest in versions:
            duplicates += 1
            continue
        versions[digest] = record

    records: list[EvidenceRecord] = []
    for base, versions in groups.items():
        if len(versions) == 1:
            records.extend(versions.values())
            continue
        for digest, record in versions.items():
            records.append(
                record.model_copy(update={"evidence_id": version_identity(base, digest), "conflict_group": base})
            )
    records.sort(key=record_sort_key)

    statuses = [record.time.status for record in records]
    counts = RecordCounts(
        received=len(raw_records),
        accepted=len(records),
        in_window=statuses.count(TimeStatus.IN_WINDOW),
        out_of_window=statuses.count(TimeStatus.OUT_OF_WINDOW),
        untimed=len(records) - statuses.count(TimeStatus.IN_WINDOW) - statuses.count(TimeStatus.OUT_OF_WINDOW),
        malformed_dropped=malformed,
        duplicates_dropped=duplicates,
        conflicting=sum(1 for record in records if record.conflict_group is not None),
        boundary_uncertain=sum(
            1 for r in records if r.time.status is TimeStatus.OUT_OF_WINDOW and r.time.boundary_uncertain
        ),
    )
    if failure is not None and not records and not malformed:
        return source_failed(context, failure)
    return SourceEvidence(
        source=_source_result(context, counts, records, failure=failure, budget_exhausted=budget_exhausted),
        records=tuple(records),
    )


def _evidence_record(context: SourceContext, extracted: ExtractedRecord) -> EvidenceRecord:
    record_id = _record_id(extracted.record_id)
    record_id_field = extracted.record_id_field if record_id is not None else None
    time = parse_event_time(
        extracted.time_field,
        extracted.time_value,
        window=context.requested_window,
        clock_uncertainty_ms=context.clock_uncertainty_ms,
    )
    attributes = clean_attributes(extracted.attributes)
    if record_id is not None:
        evidence_id = record_identity(context.source_id, record_id)
    else:
        evidence_id = content_identity(
            context.source_id,
            evidence_digest(
                source_record_id=None,
                source_record_id_field=None,
                time=time,
                event_type=extracted.event_type,
                summary=extracted.summary,
                entities=extracted.entities,
                attributes=attributes,
            ),
        )
    return EvidenceRecord(
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
            source_record_id_field=record_id_field,
            query=context.query,
            collected_at=context.collected_at,
        ),
        time=time,
        event_type=extracted.event_type,
        summary=extracted.summary,
        entities=extracted.entities,
        attributes=attributes,
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
        requested_cap=context.requested_cap,
        cap=context.cap,
        returned=counts.received,
        # An unanswered call makes no claim about what lies beyond it.
        has_more=context.has_more if responded else None,
        total_reported=context.total_reported if responded else None,
        post_filtered=context.post_filtered,
        interrupted=interrupted,
    )
    truncation = truncation_state(pagination)
    # A source that never answered observed no window at all.
    queried = context.queried_window if responded else None
    window = _window_coverage(queried, context.requested_window)
    complete = coverage_is_complete(window_coverage=window, truncation=truncation, pagination=pagination, counts=counts)
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
    if coverage.complete:
        outcome = SourceOutcome.EMPTY if counts.in_window == 0 else SourceOutcome.COMPLETE
        reasons: set[PartialReason] = set()
    else:
        outcome = SourceOutcome.PARTIAL
        reasons = coverage_reasons(coverage, broke_off=failure is not None, budget_exhausted=budget_exhausted)
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
    """Record a source that produced no records; never an empty success.

    Pagination claims and the queried window describe a response, so an
    unanswered call discards them.
    """
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
