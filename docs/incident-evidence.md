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
| Client view (bounded projection) | `packages/unifi-core/src/unifi_core/incident_evidence_view.py` |
| Client view JSON Schema artifact | `tests/fixtures/incident_evidence/incident-evidence-view.v1.schema.json` |
| Golden client views | `tests/fixtures/incident_evidence/views/*.json` |
| Bounded client views (adversarial documents, every page) | `tests/fixtures/incident_evidence/view-bounds/*.json` |

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
  `<source>|sha256|<digest>` (or `<source>|fields|<digest>`, below). The digest hashes the record's own sanitized
  evidence, never the raw payload, so excluded fields (secrets, buffer stamps,
  recognized identity, display names) cannot change identity. A Network
  summary is the stored `msg`, `message` or `description` when the record has
  one; otherwise it is the v2 `message_raw` with only MAC- and IP-shaped role
  `id`s filled in, so names, and role IDs that are names, keep their `{ROLE}`
  placeholders (falling back to `title_raw`). Network tool responses
  (`unifi_list_events`, `unifi_list_alarms`) render names into `msg`, so their
  records without an ID use basis `content_hash_without_summary`: the digest
  that identifies them treats `summary` as null, and reads that differ only in
  that text become versions of one identity, never two events. Repeats with
  the same evidence collapse; differing evidence under one source ID (or one
  `fields` identity) is kept as a conflict group of `<base>|version|<digest>`
  records that blocks complete coverage. Results do not depend on input order.
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
  read; a cap never does, and neither does a total below the rows already
  read. `population_total` is set only when coverage is complete.
- **Retention.** Each source's `retention_coverage` says whether the
  controller still held every event of the queried window. It is always
  `unknown`: neither product reports its oldest retained event, so an `empty`
  source means the controller returned no event for the window, not that none
  occurred before the controller discarded it. Network's `/stat/sysinfo`
  `data_retention_*` settings describe statistics scales, and Protect's
  `recordingRetentionDurationMs` and per-camera `recordingStart` describe
  video; how either bounds the event log is not verified, so neither is used
  to place a window inside or outside retention. Any all-clear must say so.
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
| Network `get_events_page` and `read_events_page` (v2) | the last page of `total_page_count`, remote `total_element_count`, or an empty/short page when no page count is reported | submitted `timestampFrom`/`timestampTo` |
| Network `get_events_page` (legacy) | fewer rows than the `_limit` sent (at most 3000) | `[collected_at - within_hours, request_started_at]` floored to ms |
| Network `get_alarms_page` (v2) | a `total_page_count` of 1, remote total, or a short page of at most 100 when no page count is reported | submitted 30-day bounds |
| Network `get_alarms_page` (legacy) | the full alarm list is the total | caller-supplied, else unknown |
| Protect `list_events_page` | fewer raw rows than `limit` (the NVR reports no totals), on the raw path (`camera_id` or `metadata_fields`) only; the SDK path filters after the limit and never proves the end | submitted `start`/`end`, unknown if either is omitted |
| Protect `list_smart_detections_page` | fewer raw rows than `limit`, before confidence filtering, on the raw path only | as above |

The list methods (`get_events`, `get_alarms`, `list_events`,
`list_smart_detections`) return the same rows for tools and raise
`UniFiMalformedResponseError` instead of silently dropping an unreadable Network
row. Network manager failures carry fixed operation, exception class and HTTP
status text only; controller text never leaves the manager.

Tool responses (`normalize_*_tool_response`) carry no continuation state, so
their sources are never complete. The relay and worker can report what tools
returned but cannot present an all-clear until tools expose page state.

## Client view

A full document carries every record with its raw attributes and repeated
provenance; at default budgets it can exceed 2 MB, more than MCP clients accept
in one tool result. `client_view(evidence, max_records_returned=..., resume_after=...)`
projects a validated document into a `unifi-incident-evidence-view` (version 1,
schema artifact above). It is pure and deterministic and keeps no state between
calls.

| Field | Content |
|-------|---------|
| `requested_window`, `overall`, `coverage_complete`, `budgets`, `mappings` | Copied unchanged. |
| `sources[]` | Each source's `source_id`, `product`, `source_tool`, `scope`, `outcome`, `failure`, `partial_reasons` and whole `coverage`, unchanged apart from cut labels, and `truncated`. API family, endpoint, query and collection time stay in the full document. |
| `records[]` | Citations: `evidence_id`, `conflict_group` (versions only, see below), `product`, `source_tool`, `source_record_id`, `time` (`status`, `utc`, `boundary_uncertain` and the original field, type and value), `event_type`, `summary`, `entity_ids`, `mapping` (`status`, `target_ids`, assertion `sources`), and `truncated`. Raw attributes are dropped. |
| `record_selection` | `max_records_returned`; `omission: "presentation_limit"`; `resume_after`; `collected`, `before_resume`, `returned` and `omitted` tallies (`total`, `in_window`, `out_of_window`, `untimed`); `too_large`; `limited_by`; `next_cursor`. |

**Size.** A view takes at most 20,000 estimated tokens as an MCP tool result
(`{"success": true, "data": <view>}`), well under the roughly 25,000 tokens
clients accept. `estimated_tokens` costs the JSON an MCP server sends (indented
by two spaces, non-ASCII text unescaped, quotes, backslashes and control
characters escaped):
- Every string value costs one token per UTF-8 byte it is sent in. No token
  of a byte-level tokenizer is shorter than a byte, so no text costs fewer
  estimated tokens than it really uses, however degenerate: a long
  whitespace run, repeated punctuation, letters in no word, multi-byte or
  emoji characters. Ordinary text costs about four times what it uses.
- Field names (the view's own and the snake_case filter names a source
  records), numbers and `true`, `false` and `null` cost what they are:
  letters in a name one token per four, digits in a name one per three, a
  number one per digit plus three, every other character its bytes. JSON's
  indentation, quotes, colons and commas cost six tokens per member and
  two per item.

The view's serialized UTF-8 size is also capped at 80,000 bytes, four per
budget token (`serialized_bytes`, `VIEW_BYTE_LIMIT`). Tokenizers average about
four bytes a token over ordinary text, and a view the estimate fits is far
smaller, since every string byte is a token of its own; only an estimate that
undercounted some text could pass the cap. It is a backstop, not the bound:
such a view is refused, with an error naming the limit and how to read less
(`max_records_returned`, or `detail=full`), rather than sent. The cap bounds
bytes, not tokens; the estimate bounds tokens. The token bound holds for any
valid document, not only for what valid requests collect:
- Overall status, coverage, failures, outcomes, reasons and assertions are
  never dropped or cut. A failure is a kind and an HTTP status, never
  controller or exception text.
- A source's labels (`source_tool` and the scope's `controller_id`, `site`
  and `location_id`) are cut to their first 128 estimated tokens (128 bytes),
  and the source's `truncated` names each cut label with its full length in
  characters (`{}` when nothing was cut). An ASCII label the request rules
  accept is never cut; one with multi-byte characters is cut past 128 bytes
  (a label of 128 emoji to its first 32), and a document from elsewhere, such
  as an older relay's, can carry a longer one.
- Request validation bounds the rest (at most 5 cameras, 20 assertions, and
  a bounded label and identifier length and character set), so only
  records are fitted to what remains.
- A document whose sources and assertions alone, labels cut, would exceed the
  budget has no honest view: every surface refuses it with an error that
  states the source and assertion counts and how to narrow the request
  (`detail=full` still returns the document). Valid requests never reach it.

**Free text and identifiers.** `summary` is cut to its first 200 estimated
tokens (200 bytes), `event_type` and a string `time.original_value` to 40, and
`source_tool` to 128, as in its source. Long whitespace runs and other
degenerate text are cut like any long text. The cut
text is a prefix of the original, and the record's `truncated` names each cut
field with its full length in characters; it is `{}` when nothing was cut.
Identifiers (`evidence_id`, `source_record_id`, `entity_ids`, `target_ids`)
are never cut. A record whose citation would take more than 2,500 estimated
tokens, or whose evidence ID is longer than 256 characters, is never returned:
it is counted in `too_large`, and only the full document shows it.

**Conflict groups.** A record that is one of several differing versions of
one identity (a `|version|<digest>` evidence ID) carries its `conflict_group`
exactly as in the full document; every other record omits the key, never
stating `null`. Records sharing a group are versions of one event, never
distinct events, whether the identity is a source record ID or a summary-free
`fields` hash. The group is the evidence ID without its suffix, so it is
always shorter than the cited ID: it is costed inside the citation's
2,500-token limit and the view's budget like any other identifier, never cut,
and ordinary citations cost nothing more. Members of one group can fall on
different pages; the source's `counts.conflicting` and its
`conflicting_records` reason say how many versions exist. The schema requires
the key exactly on versions; that it equals the evidence ID's own base is a
semantic check consumers must run.

**Selection.** Records are examined in selection order: in-window records
earliest first, then untimed records, then out-of-window records, records at
one time ordered by evidence ID. They are returned until `max_records_returned`
records are returned or the next one would exceed the budget; a record that
would exceed it even as the view's first is counted in `too_large`, like one
over the citation limit. `limited_by` says which limit stopped the view, and
is null when every record was examined. Returned records keep the document's
order. Omission is a presentation limit: coverage, counts and outcomes still
describe every collected record.

**Continuation.** `next_cursor` is set exactly when a limit stopped the view.
It names the last returned record's selection key,
`<rank>|<utc>|<evidence_id>` (rank `0` in-window, `1` untimed with an empty
time, `2` out-of-window). Repeat the same request with `resume_after` set to it
to read the records after it; `before_resume` counts the records at or before
the cursor. Records that share a timestamp are ordered by evidence ID, so every
continuation returns new records: paging through a document returns each
record once, or counts it once as `too_large`. A cursor names a position, not a
snapshot: an event the controller added before that position since the last
read is counted in `before_resume` and not shown. `max_records_returned`
defaults to 25 and is at most 50; narrowing the window or filtering to exact
device MACs or cameras also reduces what is omitted.

Every view of every golden case, and every page of adversarial documents
collected through the SDK decoders at each input bound (escaped,
whitespace, punctuation, multi-byte and emoji characters, often in long
runs, in every controller string; maximal labels and assertions; records
sharing a timestamp; oversized identifiers), stays within the budget and the
byte cap, measured on the bytes an MCP server sends rather than by the
estimate itself, and states the same
overall status, budgets, mappings, outcomes, failures, reasons and coverage as
its document. So does every view of those documents with labels, assertions
and sources beyond request validation added, or it is refused
(`packages/unifi-core/tests/test_incident_evidence_view.py` and
`test_incident_evidence_view_bounds.py`). `tests/fixtures/incident_evidence/view-bounds/`
holds such documents with every page of their views, or the refusal, for
other consumers.

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
success, partial and failure outcome shapes and failure kind per outcome; a
partial source's failure exactly when it lists `partial_response`, and its
read `interrupted` exactly when it carries a failure or `budget_exhausted`;
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
   `total_reported < seen` → `unknown` (a total that contradicts the rows
   read proves nothing), `total_reported > seen` → `truncated`, otherwise
   `not_truncated` unless `interrupted`; else if `interrupted` → `unknown`;
   else if `has_more` is false → `not_truncated`; else `unknown`. Also
   `returned == counts.received` and `cap <= requested_cap` when both are set.
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
   `conflict_group` equals the base. Without an ID, basis `content_hash` is
   `<source_id>|sha256|<digest>` with no conflict group; basis
   `content_hash_without_summary` has base `<source_id>|fields|<digest with
   "summary": null>` and follows the same base-or-version rule. Evidence IDs
   are unique and every conflict group has at least two records.
9. **Records and sources.** Sources are sorted by unique `source_id`. Every
   record cites a listed source and repeats its `product`, `api_family`,
   `source_tool`, `endpoint`, `scope`, `query` and `collected_at`.
   `evidence_id_basis` is `source_record_id` exactly when a source record ID
   is present; otherwise `content_hash` or `content_hash_without_summary`.
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

The schema artifacts, golden expected outputs and golden views are generated
and drift-tested by `packages/unifi-core/tests/test_incident_evidence_golden.py`,
`test_incident_evidence_view.py` and `test_incident_evidence_view_bounds.py`. After an
intentional change, bump `INCIDENT_EVIDENCE_SCHEMA_VERSION` if serialized
output changes incompatibly, then regenerate and review the diff:

```bash
INCIDENT_EVIDENCE_UPDATE_GOLDEN=1 uv run --package unifi-core pytest \
  packages/unifi-core/tests/test_incident_evidence_golden.py \
  packages/unifi-core/tests/test_incident_evidence_view.py \
  packages/unifi-core/tests/test_incident_evidence_view_bounds.py
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
