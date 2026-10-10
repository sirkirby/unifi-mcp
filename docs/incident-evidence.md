# Incident evidence contract

`unifi_core.incident_evidence` is the one versioned, closed model every incident
surface uses to say what it observed, where each observation came from, and what
it could not check. MCP tools, API routes, the relay and the worker consume it;
none of them define their own evidence semantics.

| Piece | Location |
|-------|----------|
| Contract, time parsing, mapping, coverage and assembly | `packages/unifi-core/src/unifi_core/incident_evidence.py` |
| Manager read result (`SourcePage`) | `packages/unifi-core/src/unifi_core/source_page.py` |
| Network normalizers | `packages/unifi-core/src/unifi_core/network/incident_evidence.py` |
| Protect normalizers | `packages/unifi-core/src/unifi_core/protect/incident_evidence.py` |
| JSON Schema artifact | `tests/fixtures/incident_evidence/incident-evidence.v1.schema.json` |
| Golden corpus | `tests/fixtures/incident_evidence/cases/*.json` |
| Invalid corpus | `tests/fixtures/incident_evidence/invalid/*.json` |
| Legacy timeline projection | `unifi_core.event_timeline.normalized_event_from_record` |

Normalizers are pure: no controller I/O, no app imports. Collection (calling
managers, enforcing budgets) belongs to the caller.

## Shape

An `IncidentEvidence` set carries `schema` and `schema_version`, the requested
window, budgets, any mapping assertions, one `SourceResult` per source call and
the `EvidenceRecord`s those sources produced. `overall` and `coverage_complete`
are derived and validated, never trusted from the producer.

- **Provenance.** Each record names its product, API family, source tool,
  endpoint when known, controller/site/location scope, query parameters,
  collection time, and the source record ID exactly as returned (string or
  integer) with the field it came from. Query, filter and attribute keys are
  lowercase snake case and never secret-like names; tool error text is never
  copied.
- **Identity.** Evidence IDs are `|`-separated, a character source IDs cannot
  contain, and record IDs are percent-encoded: `<source>|int|7` and
  `<source>|str|7` are different records. Records without an ID are
  `<source>|sha256|<digest>`. The digest hashes the record's own sanitized
  evidence, never the raw payload, so excluded fields (secrets, buffer stamps,
  recognized identity, display names) cannot change identity. Repeats with the
  same evidence collapse; differing evidence under one source ID is kept as a
  conflict group of `<base>|version|<digest>` records that blocks complete
  coverage. Results do not depend on input order.
- **Time.** Windows are half-open, `start <= t < end`, compared in UTC at the
  timestamp's stated precision. Each record keeps the original field, type and
  value, the format, offset, precision and any known clock uncertainty, plus a
  fixed-width UTC string whose lexical order is time order. Missing,
  malformed, timezone-less (`ambiguous_timezone`) and out-of-window times are
  explicit statuses; collection time never stands in for event time. Protect
  event time is the event `start`, so an event that began before the window is
  out-of-window even if its `end` falls inside.
- **Mapping.** Records list the identifiers they state (Network MACs by role,
  Protect camera IDs). Mappings resolve only against explicit
  `MappingAssertion`s by exact identifier: one target is `verified`, several
  are `ambiguous`, none is `missing`. Names and nearby timestamps never create
  a mapping or an identity. Protect recognized-face and plate fields are not
  carried.
- **Coverage.** Each source reports requested and queried windows, filters,
  pagination (offset, requested and effective cap, returned, `has_more`,
  remote total, post-cap filtering, interruption), truncation and counts of
  received, accepted, in-window, out-of-window, untimed, malformed, duplicate,
  conflicting and boundary-uncertain records. Only the source's own
  continuation flag (`has_more: false`) or remote total proves the tail was
  read; a cap never does. `population_total` is set only when coverage is
  complete.
- **Failure.** Sources end `complete`, `empty`, `partial` (with sorted
  reasons), or one of `unavailable`, `auth_failed`, `permission_denied`,
  `timeout`, `unsupported`, `parse_failed`, `not_attempted`. A response that
  broke off keeps its records as `partial` with the failure attached. A failed
  source makes no window or pagination claim. `failure_from_exception` never
  raises; unclassifiable errors are `unavailable`.
- **Overall.** `failed` when no source returned data, `empty` only when every
  source is a complete empty success, `complete` when every source is complete
  or empty and no budget is exhausted, otherwise `partial`.
- **Budgets.** Window, event, call and elapsed limits are inputs; usage and the
  exhausted kinds are reported, and exhaustion makes the set partial.

## Collecting from managers

Evidence that can be complete comes from manager pages, not tool responses.
`SourcePage` carries the facts a list hides: every row the source returned
(unreadable rows included, so they are counted as malformed), `has_more`, the
remote total, the offset and cap actually transmitted, the answering API path,
the epoch-millisecond bounds actually submitted, and whether rows were
filtered after the cap. Pass the page to the context helper and normalize it:

```python
page = await network_event_manager.get_events_page(within=2, limit=100)
context = network_events_context(
    requested_window=window,
    request_started_at=started,  # captured just before the call
    collected_at=finished,
    within_hours=2,
    limit=100,
    page=page,
)
evidence = normalize_network_page(page, context)
```

| Manager page | Exhaustion proof | Queried window |
|--------------|------------------|----------------|
| Network `get_events_page` (v2) | remote `total_element_count`, or an empty/short page | submitted `timestampFrom`/`timestampTo` |
| Network `get_events_page` (legacy) | fewer rows than the `_limit` sent (at most 3000) | `[collected_at - within_hours, request_started_at]` floored to ms |
| Network `get_alarms_page` (v2) | remote total, or a short page of at most 100 | submitted 30-day bounds |
| Network `get_alarms_page` (legacy) | the full alarm list is the total | caller-supplied, else unknown |
| Protect `list_events_page` | fewer raw rows than `limit` (the NVR reports no totals) | submitted `start`/`end`, unknown if either is omitted |
| Protect `list_smart_detections_page` | fewer raw rows than `limit`, before confidence filtering | as above |

The list methods (`get_events`, `get_alarms`, `list_events`,
`list_smart_detections`) return the same rows for tools and raise
`UniFiMalformedResponseError` instead of silently dropping an unreadable Network
row. Network manager failures carry fixed operation, exception class and HTTP
status text only; controller text never leaves the manager.

Tool responses (`normalize_*_tool_response`) carry no continuation state, so
their sources are never complete. The relay and worker can report what tools
returned but cannot present an all-clear until tools expose page state.

## Current product contracts

| Tool | Arguments | Records at |
|------|-----------|-----------|
| `unifi_list_events` | `within_hours` (lookback from now), `limit`, `start` (offset), `event_type`, `categories`, `severities` | top-level `events` |
| `unifi_list_alarms` | `include_archived`, `limit` (no time range) | top-level `alarms` |
| `protect_list_events` | `start`, `end` (ISO 8601), `limit`, `event_type`, `camera_id`, `compact`, `metadata_fields` | `data.events` |
| `protect_list_smart_detections` | `start`, `end`, `limit`, `detection_type`, `camera_id`, `min_confidence`, `compact`, `metadata_fields` | `data.detections` |

Protect `start`/`end` that are omitted or unparseable reach the controller as no
bound. `metadata_fields` is recorded in the query because it changes the
request path. Smart detections are filtered by confidence after the NVR applies
`limit`; the effective threshold (`min_confidence`, or the server's
`smart_detection_min_confidence` exposed on the Protect `EventManager`) is
recorded in the filters.

## Validating evidence outside Python

The schema artifact encodes every rule one JSON document can express on its
own: closed objects and enums; evidence-key grammar; evidence ID shape;
`overall`/`coverage_complete` against source outcomes and budget exhaustion;
success, partial and failure outcome shapes and failure kind per outcome;
complete-coverage preconditions; exhaustion proof for `not_truncated` and
`truncated`; observed bounds present exactly when in-window records exist;
placed versus unplaced times; and mapping outcome shapes.

JSON Schema cannot compare values across fields or recompute derived values, so
**a schema-valid document is not yet trustworthy evidence. An all-clear
(`overall: "empty"`, `coverage_complete: true`) is valid only after the schema
and every check below pass.** `validate_incident_evidence` performs all of them
in Python; a TypeScript consumer must implement them. Strings compare by code
point unless stated otherwise.

1. **Windows.** Every UTC string matches
   `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$`; every window has
   `start < end`. Each `sources[i].coverage.requested_window` equals
   `requested_window` field for field.
2. **Window coverage.** `queried_window` null → `unknown`; else
   `queried.start <= requested.start` and `queried.end >= requested.end` →
   `covered`; else `not_covered`.
3. **Truncation.** With `seen = (offset ?? 0) + returned`: `has_more` true →
   `truncated`; else if `total_reported` is set and `post_filtered` is false:
   `total_reported > seen` → `truncated`, otherwise `not_truncated` unless
   `interrupted`; else if `interrupted` → `unknown`; else if `has_more` is
   false → `not_truncated`; else `unknown`. Also `returned == counts.received`
   and `cap <= requested_cap` when both are set.
4. **Completeness.** `complete` is true exactly when window coverage is
   `covered`, truncation is `not_truncated`, `offset` is null or 0, the read
   was not `interrupted`, and `malformed_dropped`, `untimed`, `conflicting`
   and `boundary_uncertain` are all 0. `population_total` equals
   `counts.in_window` when complete and is null otherwise.
5. **Partial reasons.** For a `partial` source the sorted, de-duplicated set
   is exactly: `partial_response` iff `failure` is set; `budget_exhausted` as
   reported, where `interrupted` must equal (`failure` set or
   `budget_exhausted` reported); `truncated` or `truncation_unknown` from rule
   3, plus `post_filtered` when unknown and `post_filtered` is true;
   `prefix_not_collected` when `offset > 0`; `window_not_covered` or
   `window_coverage_unknown` from rule 2; `malformed_records`,
   `untimed_records`, `conflicting_records`, `boundary_uncertain` when the
   matching count is non-zero. Complete and empty sources list none, and
   `empty` means `counts.in_window == 0`.
6. **Time.** Recompute each record's `time` from `original_field`,
   `original_type`, `original_value` and `clock_uncertainty_ms`, and require
   every field to match:
   - `absent` or `null` → `missing`, format null.
   - `boolean`, `object`, `array`, or a `float` whose value is null
     (non-finite) → `malformed`, format `unrecognized`.
   - An integer, float, or string matching `^[0-9]+(\.[0-9]+)?$` is an epoch
     number `n` (exact decimal of the JSON number). `n < 1e8` or `n >= 1e14`
     → `malformed`. `n < 1e11` → `epoch_seconds`, microseconds
     `round_half_even(n × 10⁶)`, precision `second` if `n` is integral else
     `microsecond`. Otherwise `epoch_milliseconds`, microseconds
     `round_half_even(n × 10³)`, precision `millisecond` if integral else
     `microsecond`. Basis `epoch_utc`, offset null.
   - Other strings must match
     `^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|z|[+-]\d{2}:?\d{2})?$`
     and form a valid calendar date and clock time, else `malformed`
     (`unrecognized`). With no offset → `ambiguous_timezone` (format
     `iso8601`). Offset hours above 23 or minutes above 59, or a UTC result
     outside years 1–9999, → `malformed`. Precision: no seconds → `minute`,
     no fraction → `second`, 1–3 fraction digits → `millisecond`, else
     `microsecond`. `utc_offset` is `±HH:MM` (`Z` → `+00:00`), basis
     `explicit_offset`.
   - Placed times are `in_window` when `start <= utc < end`, else
     `out_of_window`. `boundary_uncertain` is true when
     `clock_uncertainty_ms > 0` and the time is within that many milliseconds
     of `start` or `end`. Unplaced times have null `utc`, `utc_offset`,
     `timezone_basis` and `precision` and `boundary_uncertain: false`.
7. **Mapping.** An entity's identity is `(id_kind, id)`, except that a
   `mac` whose value, trimmed and lowercased, is six hex pairs joined
   consistently by `:` or `-`, or twelve bare hex digits, uses its lowercase
   colon form. When `mappings` is
   null every mapping is `not_evaluated` with empty arrays and null
   confidence. Otherwise, for each assertion in order whose entity identity
   equals one of the record's entities, keep the first target per target
   identity, the record's matched entity and the assertion's source. No
   targets → `missing`; more than one → `ambiguous` with null confidence; one
   → `verified` with `exact_identifier`. Targets and `matched_on` sort by
   identity, sources by value. The recomputed outcome must equal the stored
   one.
8. **Evidence IDs.** `digest` is the first 24 hex digits of SHA-256 over the
   ASCII JSON (sorted keys, separators `,` and `:`, non-ASCII escaped as
   `\uXXXX`) of `{"attributes": <attributes>, "entities": [<entity objects with
   kind, id_kind, id, role>], "event_type": …, "source_record_id": null or
   ["int"|"str", <id>], "source_record_id_field": …, "summary": …,
   "time": [original_field, original_type, original_value]}`. A record with a
   source record ID has base `<source_id>|int|<id>` or `<source_id>|str|<id>`,
   with the ID percent-encoded as UTF-8, leaving only `A–Z a–z 0–9 - . _ ~`
   unescaped. Its `evidence_id` is the base, or `<base>|version|<digest>` when
   `conflict_group` equals the base. Without an ID it is
   `<source_id>|sha256|<digest>` with no conflict group. Evidence IDs are
   unique and every conflict group has at least two records.
9. **Records and sources.** Sources are sorted by unique `source_id`. Every
   record cites a listed source and repeats its `product`, `api_family`,
   `source_tool`, `endpoint`, `scope`, `query` and `collected_at`.
   `evidence_id_basis` is `source_record_id` exactly when a source record ID
   is present.
10. **Counts.** Per source: `accepted` = its records; `in_window`,
    `out_of_window` and `untimed` by time status; `conflicting` = records
    with a conflict group; `boundary_uncertain` = out-of-window records with
    `boundary_uncertain`; `received = accepted + malformed_dropped +
    duplicates_dropped`; `observed_first_utc`/`observed_last_utc` are the
    minimum and maximum UTC of in-window records.
11. **Ordering.** Records sort by (UTC null last, UTC, product, source ID,
    source record ID as a string or empty, evidence ID).
12. **Budgets.** `window` is exhausted exactly when `limits.window_seconds` is
    less than the requested window's duration. For events, calls and elapsed
    time, usage above the limit must be reported exhausted and a reported
    exhaustion needs usage at or above the limit. `exhausted` is sorted and
    unique.
13. **Overall.** Recompute rule 5's outcomes and the overall status as
    described under Shape; `coverage_complete` is true exactly for `complete`
    and `empty`.

`tests/fixtures/incident_evidence/invalid/` holds evidence sets that must be
rejected. Cases with `"rejected_by": "schema"` fail schema validation alone;
cases with `"rejected_by": "semantic"` pass the schema and must fail the checks
above.

## Changing the contract

The schema artifact and golden expected outputs are generated and drift-tested
by `packages/unifi-core/tests/test_incident_evidence_golden.py`. After an
intentional change, bump `INCIDENT_EVIDENCE_SCHEMA_VERSION` if serialized
output changes incompatibly, then regenerate and review the diff:

```bash
UNIFI_UPDATE_INCIDENT_GOLDEN=1 uv run --package unifi-core pytest \
  packages/unifi-core/tests/test_incident_evidence_golden.py
```

Corpus fixtures use only synthetic identifiers: locally administered MACs,
RFC 5737 documentation IPs and `fixture-` names. A test enforces this.

## Relay and worker migration

The corpus lives in the top-level `tests/fixtures/` directory because both
Python package tests and the worker's Vitest suite already read shared fixtures
from there. Each case holds per-source inputs (tool envelopes, raw records, or
`"adapter": "page"` manager pages) with call arguments, and the normalized
evidence (`expected`). TypeScript consumers validate `expected` against the
schema artifact and the checks above, must reproduce it from `input` without
importing Python, and must reject every case under `invalid/`.

`unifi_core.event_timeline` keeps `NormalizedEvent`, `merge_timelines` and
`filter_by_area` unchanged for existing callers. `normalized_event_from_record`
projects timed evidence onto that legacy shape and returns `None` for untimed
records. A projected list drops coverage and failure state, so callers that
return it must also return the evidence set's source outcomes. The relay
location timeline and the worker timeline still use the legacy path; moving
them onto this contract means calling the current tool names and arguments
above, reading each tool's record path, reporting per-source outcomes instead
of skipping failed sources, and exposing page state before claiming
completeness.
