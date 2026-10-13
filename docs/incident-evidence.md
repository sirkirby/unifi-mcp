# Incident evidence contract

`unifi_core.incident_evidence` is the one versioned, closed model every incident
surface uses to say what it observed, where each observation came from, and what
it could not check. MCP tools, API routes and the cloud worker consume it, and
the relay forwards it; none of them define their own evidence semantics.

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
| Bounded collection and combining | `packages/unifi-core/src/unifi_core/incident_collection.py` |
| Network and Protect collectors | `unifi_core/network/incident_collection.py`, `unifi_core/protect/incident_collection.py` |
| Collection request models | `unifi_core/network/models/incident_evidence.py`, `unifi_core/protect/models/incident_evidence.py` |
| Mocked controller answers for collection | `tests/fixtures/incident_evidence/collection/controller_responses.json` |
| Client view (bounded projection) | `packages/unifi-core/src/unifi_core/incident_evidence_view.py` |
| Client view JSON Schema artifact | `tests/fixtures/incident_evidence/incident-evidence-view.v1.schema.json` |
| Golden client views | `tests/fixtures/incident_evidence/views/*.json` |
| Bounded client views (adversarial documents, every page) | `tests/fixtures/incident_evidence/view-bounds/*.json` |

Normalizers are pure: no controller I/O, no app imports. The collectors call
manager page reads and enforce budgets (see [Collecting evidence](#collecting-evidence)).

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
| Protect `list_events_raw_page` | fewer raw rows than `limit` | submitted `start`/`end` |
| Network `read_events_page` | as `get_events_page`, from one request | v2: the absolute `timestampFrom`/`timestampTo` sent (`window_ms`), else as `get_events_page` |

The list methods (`get_events`, `get_alarms`, `list_events`,
`list_smart_detections`) return the same rows for tools and raise
`UniFiMalformedResponseError` instead of silently dropping an unreadable Network
row. Network manager failures carry fixed operation, exception class and HTTP
status text only; controller text never leaves the manager.

Tool responses (`normalize_*_tool_response`) carry no continuation state, so
their sources are never complete. The list tools' responses cannot support an
all-clear; the incident evidence tools return complete evidence documents.

## Collecting evidence

`collect_network_incident_evidence(event_manager, request, site=...)` and
`collect_protect_incident_evidence(event_manager, request)` take one window,
optional exact identifiers and budgets, and return a validated
`IncidentEvidence`. They never raise for a source failure; failures, budget
exhaustion and truncation are in the document. MCP tools and API routes are
thin adapters over them.

### Inputs

`NetworkIncidentRequest` and `ProtectIncidentRequest` validate every input
before any read:

| Field | Meaning |
|-------|---------|
| `start`, `end` | ISO 8601 with an explicit UTC offset; a bound without one is rejected as ambiguous. `start < end`. |
| `device_macs` (Network) | Exact MACs, compared in canonical form. Names are rejected, never resolved. |
| `camera_ids` (Protect) | Exact camera IDs (letters, digits, `.`, `_`, `:`, `-`), never trimmed or case-folded. At most 5: each camera is its own source, and every source is returned in full. |
| `location_id` | The caller's label for the investigated location, recorded in each source's `scope`: 1 to 128 characters, none of them a control character, quote or backslash. |
| `max_window_seconds` | Default 86400, at most 2592000. |
| `max_events` | Default 1000, at most 10000. |
| `max_calls` | Default 20, at most 100. |
| `max_elapsed_ms` | Default 30000, at most 120000. |
| `mappings` | Optional explicit `MappingAssertion`s, at most 20; records are resolved against them by exact identifier. Each `id` is 1 to 64 characters with no control character, quote or backslash, and an assertion states no `role`. |

Validation messages name the field and reason, never the rejected value.
The Network `site`, which comes from server configuration or the API route
rather than the request, follows the `location_id` rule:
`collect_network_incident_evidence` refuses one that breaks it before any read.
Every label and assertion is repeated in the [client view](#client-view), so
these bounds, with the camera and assertion counts, keep every valid
request's view within its size budget; identifiers are refused, never cut.

### Budgets

Budgets are checked before every read; a read never asks for more rows than
the events budget has left, and a read still running when the elapsed budget
runs out is cancelled. The first spent budget stops collection.

| Budget | Counts | When spent |
|--------|--------|------------|
| `window` | the requested window's duration | nothing is read; every source is `not_attempted` with failure `budget_exhausted` |
| `events` | every row a request returned, including out-of-window rows and rows an exact-identifier filter later removed | reading stops |
| `calls` | every HTTP request a read sends: the page request, the Network API-version probe, and every retry (uiprotect's status and reconnect retries, the retry after a re-login, aiohttp's own). Logins are not charged, and neither is connecting: each connection manager connects in its shared connect attempt, a task of its own, which a read only waits for within the `elapsed` budget. A request the budget cannot pay for is refused before it is sent | reading stops |
| `elapsed` | wall time across reads, including connecting and, in the API, acquiring the manager | the running read is cancelled; usage is reported at the limit |

A read's charge applies only in its own task. Persistent background tasks
(the shared connect attempt, the Protect bootstrap refresh, the Network
websocket, API event listeners) start with no charge, and any task a read
happens to start inherits a charge it cannot use, so a read never throttles
them and they never draw on it.

A spent budget appears three ways: its kind in `budgets.exhausted`; the source
it stopped is `partial` with `budget_exhausted` among its `partial_reasons`
and `pagination.interrupted: true` (or `not_attempted` if it returned
nothing); every later source is `not_attempted`. Truncation the stop caused
stays visible as `truncated` or `truncation_unknown`. Overall is then
`partial` or `failed`, never `complete` or `empty`.

### Sources

| Product | Sources | Read | Window | Filters recorded |
|---------|---------|------|--------|------------------|
| Network | `network.events` | `EventManager.read_events_page`, one request per page of up to 100 rows by page number | v2: the requested window as absolute millisecond bounds, widened by one boundary millisecond (below); legacy: a lookback long enough to reach `start` from any read within the elapsed budget. The queried window is what was submitted (the part every read covered) | v2: the categories and severities the controller applied; `device_macs` |
| Protect | `protect.events`, or `protect.events.camera.NN` per camera in ID order | `EventManager.list_events_raw_page`, 100 rows per read by offset, newest first | the exact window in whole milliseconds | `camera_id` |

Reading a source stops when the source proves its end (`has_more: false`, a
short page, or its remote total reached), when a read fails, or when a budget
is spent. Only a source read in a single request can be complete. Neither
product offers a snapshot or cursor, so across several offset reads an event
inserted or removed between reads shifts later offsets and a row can be
skipped while totals stay equal (Protect reports none). A source read in more
than one request is therefore `partial` with `truncation_unknown`, decided
before any exact-identifier filter that could hide the movement. A short last
read keeps every offset a whole number of pages and never asks for more rows
than the events budget has left.

On the v2 path the event log is asked for the window itself, so a quiet window
on a busy controller can be read in one page and be complete. The query
records `timestamp_from_ms`/`timestamp_to_ms` in place of `within_hours`.
Whether the controller treats `timestampFrom` and `timestampTo` as inclusive
or exclusive has not been verified against a live controller, so the bounds
are widened, never narrowed: `timestampFrom` is the window start floored to
milliseconds minus 1 ms, and `timestampTo` is the window end rounded up to
milliseconds. Under any reading the controller then returns all of
`[start, end)`; an event it returns at a widened edge is placed by its own
timestamp and reported out-of-window. Subtracting a millisecond from the end
instead would lose the window's last millisecond while still claiming it was
covered. The legacy path only takes a lookback relative to now, so its rows
newer than the window are read, counted against the events budget and
reported out-of-window.
`device_macs` keeps rows naming one of the MACs in any role; rows the filter
cannot read stay in and count as malformed. The filtered page says
`post_filtered`, so only the source's own end proof can make it complete.
Network alarms are not collected in this slice.

`list_events_raw_page` is one GET to the NVR `events` endpoint with explicit
bounds, limit and offset. It does not use the SDK's `get_events`, which pages
without bound when given a start time and drops event types it does not know,
and it does no camera-name or Known Face lookups. NVR failures become
fixed-text errors that keep the class and HTTP status, so `401` is
`auth_failed` and `403` is `permission_denied`.

### Read-only by construction

Collectors receive the product `EventManager` and call only the methods in
each collector module's `READ_METHODS` (`read_events_page`,
`list_events_raw_page`). Tests run collection through a view that exposes only
those methods, and through the real SDK decoders with the HTTP exchange
replaced, asserting every request: Protect sends only GET; Network sends only
the read-query POSTs its event API requires (`/system-log/count`,
`/system-log/all`, `/stat/event`).

### Combining evidence sets

`combine_incident_evidence(documents)` merges evidence sets for the same
requested window, for example one per product, into one validated set. It is
pure and order-independent, and the same set passed twice counts once. Every
source keeps its own outcome, failure, reasons and coverage; a source ID that
two sets describe differently is an error. Mapping assertions are the union of
every set's assertions and every record is resolved again against them.
Budget limits and usage are summed, except `window_seconds`, which is the
smallest limit. `exhausted` is the union of every set's exhausted kinds, so
combining never hides exhaustion, even when the summed usage stays below the
summed limit.

### Client view

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
  as an older server's, can carry a longer one.
- Request validation bounds the rest (at most 5 cameras, 20 assertions, and
  the label and identifier rules under [Inputs](#inputs)), so only
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
it is counted in `too_large`, and only `detail=full` shows it.

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

### Surfaces

| Surface | Network | Protect |
|---------|---------|---------|
| MCP tool (`readOnlyHint: true`) | `unifi_get_incident_evidence` | `protect_get_incident_evidence` |
| REST (`GET`, read scope) | `/v1/sites/{site_id}/incident-evidence/network` | `/v1/sites/{site_id}/incident-evidence/protect` |
| GraphQL (read permission) | `network { incidentEvidence(...) { document } }` | `protect { incidentEvidence(...) { document } }` |

Tool arguments, REST query parameters and GraphQL arguments are the request
fields above (`mappings` is a JSON-encoded string in REST and a JSON value in
GraphQL), plus three presentation arguments, validated with the request before
any read:

| Argument | Meaning |
|----------|---------|
| `detail` | `view` (default) returns the [client view](#client-view); `full` returns the whole evidence document, for programmatic consumers. |
| `max_records_returned` | Record citations in the view, 1 to 50, default 25. Rejected with `detail=full`. |
| `resume_after` | A view's `record_selection.next_cursor`; the view of the same request then returns the records after it (see [continuation](#client-view)). Rejected with `detail=full`. |

The MCP tools wait for the server's controller connection like every domain
tool, within the same bound. A call made while the controller is still
connecting, unreachable or rejecting the login returns that standard
connection error, reads nothing and counts against no budget.

Every surface renders through `EvidencePresentation.render`, so the same input
and controller answers give the same payload. MCP returns
`{"success": true, "data": <view or evidence>}`; REST returns
`{"data": <view or evidence>, "render_hint": ...}`; GraphQL returns it as the
JSON `document` field, because the JSON Schema artifacts, not the GraphQL
schema, are the contract. Invalid input is an MCP error response, REST 422 or
GraphQL `BAD_REQUEST`, naming declared fields and list indexes only (an
undeclared key is never echoed). The Network site, recorded in each source's
scope, follows the `location_id` rule: the API checks its `site_id`, and the
MCP tool refuses a configured site (`UNIFI_NETWORK_SITE`) that breaks the
rule before any read, saying how to fix it. Evidence too broad for its view
(see [Size](#client-view)) is refused the same way, as an MCP error response,
REST 422 or GraphQL `BAD_REQUEST` stating the source and assertion counts;
`detail=full` still returns it. Framework argument coercion errors drop the
rejected value too, and expected client errors are logged as one fixed line,
without a traceback or the query source. GraphQL classifies errors by
exception type, never by message text. A controller that does not run the
product is refused before collection on both surfaces: REST 409
`capability_mismatch`, GraphQL `CAPABILITY_MISMATCH`. The API validates input
and checks the window budget before acquiring a manager, acquires it inside
the first read so waiting for it is charged to the elapsed budget, reports an
acquisition failure as a classified source failure (a refused login or
bootstrap is `auth_failed` or `permission_denied` with its status; connection
managers log only the operation and exception class), and never starts a background event
listener for collection: it reuses an existing event manager or builds an
uncached one. The evidence is identical for the
same input and controller answers: the contract's key rules exclude every
secret-like name, so egress redaction has nothing to remove. A source failure
is still a successful response; check `overall` and `coverage_complete`.

### Read-only clients in lazy mode

The default lazy registration mode lists only meta-tools, and its route to a
domain tool, `*_execute`, is not read-only, so a client that permits only
`readOnlyHint: true` tools could reach no controller read. Each app's
`LAZY_DIRECT_TOOLS` (in `categories.py`) names read-only tools that lazy mode
registers directly at startup, so they are listed with their own annotations.
Only the named tools register: the other tools in their modules are held and
register when first loaded, so `*_execute` and `*_tool_index` reach them as
before. Startup fails if a named tool is not read-only or anything else
registers. `meta_only` mode still lists only meta-tools, and eager mode lists
every tool.

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
    time, usage above the limit must be reported exhausted. A kind may be
    reported exhausted below its limit: a combined set sums limits and usage
    and keeps every kind any one collection spent. `exhausted` is sorted and
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

## Relay and worker consumers

The cloud worker provides `unifi_location_timeline` when a relay is connected.
The relay does not register or handle it: it forwards the product evidence
tools like any other read-only tool, and local product servers serve those
tools but not the timeline. The timeline returns the same standard success
envelope as the product tools: `{"success": true, "data": <view or
IncidentEvidence>}`. It calls each product tool with `detail: "full"`, combines the full documents,
and returns the combined set's [client view](#client-view) unless its own
`detail` is `full`; `max_records_returned` and `resume_after` apply to that
view, which fits the same output budget. A product document from outside
request validation, such as an older server's with a longer site, has its
labels cut and marked in the view like any other; a combined set too broad
for its view is refused with Core's message, and `detail: "full"` still
returns it. A successful
transport envelope does not establish complete collection: inspect `overall`,
`coverage_complete`, each source outcome and `budgets.exhausted`. Total source
failure returns `overall: "failed"`, never an empty all-clear.

The worker forwards `start` and `end` with explicit UTC offsets to
`unifi_get_incident_evidence` and `protect_get_incident_evidence`. It accepts
`device_macs`, `camera_ids`, `mappings`, `location_id`, the four `max_*`
budgets described above, `detail`, `max_records_returned` and `resume_after`,
under the same bounds as the product tools: a count over its limit is refused
as such ("at most 5", "at most 20"), apart from a malformed identifier.
`products` defaults to Network and Protect; requested
Access collection produces an explicit `unsupported` source. The legacy
`start_time`/`end_time`, `area_hint` and `event_types` arguments are rejected.
Use exact identifiers and explicit assertions to select evidence and mappings.

Every source is returned in full, so a call reads at most 7 sources: as many as
one location produces (Network, a Protect source per camera, at most 5, and
Access). The worker counts selected locations × requested products, with Protect counted
once per camera ID, and refuses a call over the limit before any read, naming
the counts; select one `location_id`, or fewer products or cameras. A failed
location still contributes its sources, so the limit keeps the view of every
allowed call within budget.

The worker sends one evidence-tool call to each selected location through its
relay and validates the
committed JSON Schema plus all 13 semantic rules before combining. Missing tools,
disconnected locations, transport failures, error envelopes and malformed
responses become failed sources within the combined document. Error envelopes
carry no typed failure, so they are `unavailable`; raw error text is never
inspected or copied. Failed calls make no queried-window or pagination claim.
A product document with mismatched window, limits, mappings, product or requested
location scope becomes `parse_failed`.

Budgets are per product collection at each selected location. Combining sums
limits and usage, takes the smallest window limit and keeps every exhausted
kind. An unanswered transport call cannot report controller usage; its synthetic
source document reports zero observed usage. Those zeros do not imply complete
coverage. Transport failure sources have distinct deterministic IDs per location.
Product source IDs remain product-owned: contradictory sets with the same
source ID fail combination, including across locations. Select `location_id`
when different controllers return conflicting source IDs; the consumer never
silently rewrites provenance or merges them.

The TypeScript consumer uses pinned Ajv as a development dependency to generate
a committed standalone validator for the schema's closed shapes and conditional
rules. Hand-written checks supply the cross-field semantics JSON Schema cannot
express. Wrangler bundles the standalone artifact from `worker/src`; the deployed
Worker needs neither Python nor runtime code generation. Schema-artifact drift
is checked by `npm --prefix apps/worker/worker run check:evidence-schema`.
The shared `cases/` expected documents must validate and every `invalid/` case
must fail at its declared schema or semantic layer.

`tests/fixtures/incident_evidence/combine/` contains Python-generated input/output
pairs for order independence, deduplication, mapping union, conflicting source
IDs, exhausted budgets and mixed failures.
`tests/test_incident_combine_fixtures.py` checks generator drift against Core
and TypeScript compares canonical JSON with those outputs. TypeScript
also projects every golden case into the client view and compares canonical
JSON with the golden views in `views/`:

```bash
uv run --package unifi-core python tests/fixtures/incident_evidence/generate_combine.py --check
npm --prefix apps/worker/worker test
```

Regenerate after an intentional change by omitting `--check`; Python remains the
reference. Evidence digests serialize numbers using RFC 8785's ECMAScript
binary64 form: `1.0` and `1` hash identically, and negative zero becomes `0`.
Core's existing ASCII string escapes, key order and identity type tags are
preserved. JavaScript uses `JSON.stringify` for these numbers. The numeric
golden case and combine fixtures cover integral floats, exponent thresholds,
signed zero and large integers; integers needing exact precision beyond
binary64 should be represented as strings.

`unifi_core.event_timeline` still provides the legacy projection for other callers. The worker's timeline no longer returns that projection,
which cannot carry coverage or failure state.
