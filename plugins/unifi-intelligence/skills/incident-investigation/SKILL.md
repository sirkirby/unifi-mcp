---
name: incident-investigation
description: Investigate one UniFi Network device incident (a switch, AP or gateway going offline, disconnecting or misbehaving) over an explicit, bounded time window, with Protect camera context, using only the local read-only evidence tools. Produces a cited report that states its coverage. Use when the user asks what happened to a Network device at a given time.
---

# Network Device Incident Investigation

Investigate one Network device incident over one explicit window. Every claim in
the report cites **evidence**: records and per-source **coverage** returned by
the two incident evidence tools. Each tool returns a bounded **view** of its
evidence document (`schema: "unifi-incident-evidence-view"`) that fits in one
tool result: every source's outcome, failure and coverage, plus the record
citations that fit (at most `max_records_returned`), with omitted records
counted and a cursor to read the rest. The local product servers are the whole
transport; nothing here needs the cloud worker or the relay.

## Dependencies

Requires: network, protect
Optional: worker

The investigation needs `unifi_get_incident_evidence` (Network) and
`protect_get_incident_evidence` (Protect). Discovery shows a tool is listed, not
that its controller is reachable or authorized; the evidence documents report
that per source.

- **Protect not connected.** Stop the canonical investigation and report Protect
  unavailable. Offer a Network-only investigation; with the user's consent, run
  the same workflow without the Protect call and label the report
  "Network-only: Protect unavailable, no camera context". A Network-only report
  never reaches complete coverage of the incident.
- **Network not connected.** Stop and report Network unavailable. There is no
  device evidence to investigate.
- **Cloud worker.** Not needed. Its location timeline, reached through a
  connected relay, collects the same evidence through these two tools and
  returns one combined document; this workflow calls the tools directly so each
  product's document and budgets stay separate. When you reach the product
  servers through the cloud worker, call the same two evidence tools.

Use the product setup skills for connection help; never ask for secrets.

## Coverage and Limitations

Every report has a Coverage and Limitations section built from the evidence
documents, never from memory or from record counts alone:

- One line per evidence document: `overall`, `coverage_complete` and budgets.
- One line per document on `record_selection`: records returned, collected and
  omitted from the view.
- One line per source in each document: outcome, partial reasons, failure,
  queried window, filters, pagination, truncation, retention and counts
  (formats under [Report](#report)).
- Products, cameras and mappings that were not read, and why.

Claims are bounded by coverage:

- **Complete coverage** ("every source read the full window") only when every
  document in the investigation has `coverage_complete: true` and `overall` is
  `complete` or `empty`.
- **All-clear** — the sentence "No events were recorded in the window by any
  source." — only when every document has `overall: "empty"` and
  `coverage_complete: true`, and Protect was read. Otherwise write "No
  concerning activity found in the retrieved records" with the coverage gap
  beside it.
- **Retention.** Neither product reports how long it keeps events, so every
  source's `coverage.retention_coverage` is `unknown`. Whenever any source is
  `empty`, including beside the all-clear, write this sentence: "Neither
  controller reports how long it keeps events (retention `unknown`), so events
  older than its retention may have been discarded without a trace."
- Counts are retrieved records. `population_total` is a total only when the
  source is complete.
- Records omitted from the view (`record_selection.omitted`) are a
  presentation limit, not a coverage gap: coverage and counts still describe
  every collected record. Make no claim about omitted records beyond their
  counts. Records counted in `too_large` have identifiers too long to cite in a
  view, or a citation too large to fit beside its sources; only
  `detail="full"` shows them.
- A record's `truncated` names free text the view cut to a prefix (`summary`,
  `event_type`, `original_value`, `source_tool`) with its full length; a
  source's `truncated` names its labels cut the same way (`source_tool`,
  `controller_id`, `site`, `location_id`). Quote only the prefix, mark it as
  cut, and claim nothing about the text that was cut off.
- A failed source (`unavailable`, `auth_failed`, `permission_denied`,
  `timeout`, `unsupported`, `parse_failed`, `not_attempted`) is missing
  evidence, never an empty result.

## Safety

The investigation reads; it never changes anything.

- Call only tools the client lists with `readOnlyHint: true`. Reach every tool
  directly by its own name; the lazy-mode `*_execute` and `*_batch` dispatchers
  are not read-only and are not part of this workflow.
- Make no remediation, configuration change, reboot, block, acknowledgement or
  other mutation, even when the cause looks obvious. Recommend actions in words
  for the user to decide.
- Investigate the one confirmed window, once. Continuous monitoring, polling or
  subscriptions are outside this workflow.
- Offer only reads the directly listed read-only tools can make: the two
  incident evidence tools for exact identifiers, `protect_get_camera` by camera
  ID and `unifi_get_client_details` by MAC.
  Never offer to list devices, cameras, access points or doors, and never
  reach for `*_load_tools`, `*_execute` or `*_batch`.
- When an identifier is missing, ask the user for it: they can find it in the
  UniFi app, or by running the product's own list tool in eager mode.
- Never page with `resume_after`, split the window, raise a budget or call
  `detail="full"` without the user's yes to that follow-up. Offer it, end your
  turn and wait.
- Identity stays with explicit, source-backed identifiers. Faces, plates,
  people's names and similar names never identify a person or establish a
  mapping.

## Workflow

Work in this order, every time:

1. **Confirmation.** Show the inputs and budgets, then end your turn and wait
   for the user's reply (step 1).
2. **Mapping lookups.** Check the tools and run the read-only mapping lookups
   (steps 2 and 3). Ask nothing further unless nothing proves a mapping.
3. **Evidence.** One call per evidence tool (step 4), then read the views
   (step 5). Each follow-up read waits for the user's yes.
4. **Report** (step 6).

### 1. Confirm the inputs

Collect, before any read:

- **Incident:** what happened, in the user's words.
- **Device:** the exact Network device MAC. If the user gives only a name, ask
  for the MAC, from the UniFi app or the Network server's own device list tool
  in eager mode. Never pick a device by name similarity.
- **Window:** start and end with a date and timezone. Convert to ISO 8601 with
  an explicit offset (`2026-08-08T08:00:00-04:00`) and show both forms. Ask for
  a missing date, timezone or end; never assume the client's timezone. The
  window is half-open: `start <= t < end`.
- **Cameras:** cameras the user wants as context, by exact Protect camera ID, or
  "none". A camera the user only describes is used only once the user gives its
  ID or an exact identifier proves which camera it is; a name, description or
  location never does. Ask for the Protect camera ID, from the UniFi Protect app
  or the Protect server's own camera list tool in eager mode; otherwise leave
  the camera out and report it as unresolved.
- **Budgets:** state the values you will pass. Defaults: `max_window_seconds`
  equal to the window length, `max_events=1000`, `max_calls=20`,
  `max_elapsed_ms=30000`, `max_records_returned=25`. A window longer than 86400
  seconds needs the user's agreement; 2592000 is the hard limit. Each tool caps
  events at 10000, calls at 100, elapsed time at 120000 ms and
  `max_records_returned` at 50. Protect takes at most 5 camera IDs, and each
  call at most 20 mapping assertions. Mapping identifiers are at most 64
  characters and `location_id` at most 128, none of them holding a control
  character, quote or backslash; assertions carry no `role`.

**Stop here, even when the request already names every input.** Show this
block, end your turn and wait for the user's reply. Make no lookup, evidence
call or other controller read until the user confirms; a correction gets a new
block.

```text
Window: <start> to <end> (<timezone>); UTC <start> to <end>
Device: <MAC>
Cameras: <camera IDs | none>; unresolved: <descriptions | none>
Products: Network and Protect (or Network only, with the reason)
Budgets: max_window_seconds <n>, max_events <n>, max_calls <n>, max_elapsed_ms <n>, max_records_returned <n>
Next: the mapping lookups, then one call per evidence tool. Reply yes, or correct any line.
```

Done when the user has replied and confirmed device MAC, window with offset,
camera scope, products and budgets.

### 2. Check the evidence tools

In the client's tool list, confirm `unifi_get_incident_evidence` and
`protect_get_incident_evidence` are present and annotated
`readOnlyHint: true`. The default lazy registration mode lists both directly
beside the meta-tools; eager mode lists every tool. Use
`unifi_tool_index(name="unifi_get_incident_evidence", include_schemas=True)`
or `protect_tool_index(name="protect_get_incident_evidence", include_schemas=True)`
to read a schema. A tool that is absent (for example in `meta_only` mode) is
unavailable: apply [Dependencies](#dependencies).

Note also whether the mapping lookups `protect_get_camera` and
`unifi_get_client_details` are listed directly with `readOnlyHint: true`; that
decides who establishes the mappings in step 3. In lazy mode,
`unifi-network-mcp` 0.38.1 and `unifi-protect-mcp` 0.9.1 and later list them
directly, and the UniFi Network and Protect plugins pin those servers; earlier
server releases list them only in eager mode.

Done when each evidence tool is confirmed listed and read-only, or recorded
as unavailable, and each mapping lookup is recorded as listed or not.

### 3. Establish camera mappings

A **mapping** ties the incident device to a camera by exact identifier. It has
exactly two sources:

- `operator_input`: the user states the relationship for exact IDs ("camera
  `cam-…` is attached to switch `aa:bb:…`").
- `product_inventory`: read-only lookups show an exact-identifier relationship.
  Read the camera's `mac` with `protect_get_camera(camera_id="<id>")`, then
  read that MAC as a Network client with
  `unifi_get_client_details(mac_address="<camera mac>")`. Protect returns the
  MAC as 12 bare hex digits, and the Network lookup matches only the
  controller's colon form, so a bare MAC finds nothing: write the camera MAC as
  six lowercase colon-separated pairs (`a1b2c3d4e5f6` becomes
  `a1:b2:c3:d4:e5:f6`) before the lookup. Leave `summary` at its default,
  `false`: the summary form drops `sw_mac` and `sw_port` and keeps `ap_mac`
  only for wireless clients. The mapping holds when the client's uplink
  identifier (`ap_mac` for wireless, `sw_mac`, plus `sw_port` for a port, when
  wired) equals the incident device MAC, with both written in that same
  lowercase colon form before comparing. A client record that states no uplink
  identifier gives no mapping. These are current-state reads;
  say so, because the camera may have been elsewhere during the window.

When both lookups are listed directly with `readOnlyHint: true`, run them
yourself, once the user has confirmed the inputs, for every requested camera ID,
without asking again. In the default
lazy mode, `unifi-network-mcp` 0.38.1 and `unifi-protect-mcp` 0.9.1 and later,
the servers the Network and Protect plugins pin, list them directly beside the
evidence tools; eager mode lists every tool.
Camera and device listings are not listed directly in lazy mode, and they
select candidates only; they prove no mapping. Call each lookup by its own
name; never reach a lookup through `*_execute`.

Ask the user for the mapping only when there is no proof:

- **Lookups unavailable.** A lookup is not listed directly (for example in
  `meta_only` mode, or lazy mode on a server release before those versions), or
  its call fails.
- **No relationship shown.** The lookups ran, but the client record states no
  uplink identifier or names a different device.

When you ask, say which case applies and what the lookups returned, and ask for
the exact-identifier relationship; an answer becomes an `operator_input`
mapping. A camera the user only described gets no lookup until the user gives
its exact ID.

State each `product_inventory` mapping with the uplink field you compared and
both values: "`sw_mac` `aa:bb:cc:00:10:01` with `sw_port` 3 equals the incident
device MAC" for a wired camera, "`ap_mac` `aa:bb:cc:00:10:01` equals the
incident device MAC" for a wireless one. A port number or a device name alone
proves nothing.

Names, locations, nearby timestamps and "probably" never establish a mapping.
A candidate is ambiguous when the user's description fits more than one camera
or the lookups disagree; report it as ambiguous, leave that camera out, and
continue. Turn each mapping into assertions in both directions, so records from
either product resolve:

```python
mappings = [
    {
        "entity": {"kind": "network_device", "id_kind": "mac", "id": "aa:bb:cc:00:10:01"},
        "target": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-000a"},
        "source": "product_inventory",
    },
    {
        "entity": {"kind": "camera", "id_kind": "protect_camera_id", "id": "cam-fixture-000a"},
        "target": {"kind": "network_device", "id_kind": "mac", "id": "aa:bb:cc:00:10:01"},
        "source": "product_inventory",
    },
]
```

Done when every requested camera is mapped with a source, reported ambiguous,
or reported unmapped.

### 4. Collect evidence

Make one call per evidence tool with the confirmed window, budgets and the same
`mappings` and `location_id`:

```python
unifi_get_incident_evidence(
    start="2026-08-08T08:00:00-04:00",
    end="2026-08-08T09:00:00-04:00",
    location_id="fixture-location-a",
    max_window_seconds=3600,
    max_events=1000,
    max_calls=20,
    max_elapsed_ms=30000,
    max_records_returned=25,
    mappings=mappings,
)
protect_get_incident_evidence(
    start="2026-08-08T08:00:00-04:00",
    end="2026-08-08T09:00:00-04:00",
    camera_ids=["cam-fixture-000a"],
    location_id="fixture-location-a",
    max_window_seconds=3600,
    max_events=1000,
    max_calls=20,
    max_elapsed_ms=30000,
    max_records_returned=25,
    mappings=mappings,
)
```

- Leave `detail` at its default, the view. `detail="full"` returns the whole
  evidence document, which can exceed what a client accepts in one result;
  call it only after the user says yes to it.
- Network reads the site event log for the window. Leaving `device_macs` out
  keeps upstream and neighbour events, which often explain a device incident;
  pass `device_macs=["<device mac>"]` only when the user wants the device's own
  events. Filtering never reduces the rows read or the events budget.
- Protect reads each mapped camera as its own source. With no mapped camera,
  skip the Protect call and report "no camera mapped", unless the user asks for
  every camera as unmapped context; then omit `camera_ids`, and report those
  records as unmapped context that is never tied to the device.
- A response with `success: false` is a tool failure: report the product as
  unavailable with the error's operation, and make no claim from it.

Done when each tool was called once, or its absence is recorded.

### 5. Read the evidence

Read each view before writing anything from it:

1. `requested_window` equals the confirmed window in UTC, and every source's
   `coverage.requested_window` equals it.
2. Record `overall` and `coverage_complete`. They agree: `coverage_complete`
   is true exactly for `complete` and `empty`. A document that contradicts
   itself (for example `coverage_complete: true` beside a `partial` source) is
   untrustworthy: report the contradiction and claim nothing complete from it.
3. Per source: outcome and `partial_reasons`, `failure`,
   `coverage.queried_window` and `window_coverage`, `filters`, `pagination`
   (`returned`, `cap`, `has_more`, `total_reported`, `post_filtered`,
   `interrupted`), `truncation`, `retention_coverage` (always `unknown`),
   `counts`, `population_total`.
4. `budgets.exhausted`: any kind listed means collection stopped early, and
   every later source is `not_attempted`.
5. `record_selection`: `collected`, `before_resume`, `returned` and `omitted`
   counts by placement; `too_large`; `limited_by`, the limit that stopped the
   view (`max_records_returned` or `output_budget`, or null when nothing more
   was left); and `next_cursor`, set exactly when a limit stopped it.
6. Per record: `evidence_id`, `product`, `source_tool`, `source_record_id`,
   `time.status` (`in_window`, `out_of_window`, `missing`, `malformed`,
   `ambiguous_timezone`), `time.utc`, `time.boundary_uncertain`, the original
   time field, type and value, `event_type`, `summary`, `entity_ids`,
   `mapping.status` (`verified`, `ambiguous`, `missing`, `not_evaluated`) with
   its `target_ids` and `sources`, and `truncated`. Only `in_window` records are observations
   of the window. Unplaced and out-of-window records are reported under
   coverage, with their original value, never moved into the window.

A bounded follow-up read is worth offering only when it would change coverage
or show omitted records:

| Evidence says | Follow-up to offer |
|---|---|
| `window` exhausted | Narrow the window, or raise `max_window_seconds` to its length |
| `events` or `calls` exhausted, or `budget_exhausted` | Repeat that product's call with a larger budget or a narrower window |
| `timeout`, or `elapsed` exhausted | Repeat once with a larger `max_elapsed_ms` |
| `truncation_unknown` | Split the window into parts that each fit one page, and read each part |
| `next_cursor` set (records omitted from the view) | Repeat the same call with `resume_after` set to `next_cursor`; it returns the records after the cursor, even those sharing its timestamp. When `limited_by` is `max_records_returned`, raising it (at most 50) also helps; narrowing to exact `device_macs` or `camera_ids` reduces what is collected |
| `too_large` above 0 | None in the view: report the count; those records are shown only by `detail="full"`, which can exceed one tool result |
| `auth_failed`, `permission_denied`, `unsupported` | None: point to the product setup skill |

The offers for `truncation_unknown` and for omitted records are mandatory.
Whenever a source has `truncation_unknown`, Unanswered Questions and Next Reads
says "split the window" and gives the call with its new `start` and `end`.
Whenever `next_cursor` is set, it gives the same call with
`resume_after="<next_cursor>"`, the cursor copied exactly. These are offers:
make no follow-up call until the user says yes to it, then use the same
evidence tool and report each view separately. List tools return records
without continuation state, so they never complete coverage.

Done when every source in every view has its outcome, coverage and counts
recorded, and every follow-up has been offered or ruled out.

### 6. Write the report

Write the [Report](#report). Done when every section is present, every
observation carries a citation, and every coverage claim matches the documents.

## Report

Use these sections, in order:

1. **Incident and Inputs:** the incident, device MAC, window as given and in
   UTC with its offset, camera scope, mapping assertions with their sources
   (for `product_inventory`, the uplink field compared and both values, as in
   step 3), and the budgets passed.
2. **Coverage and Limitations:** per document, its line and its records line,
   then one line per source:

   ```text
   <document>: overall `<overall>`, coverage_complete `<true|false>`; budgets window <seconds>/<limit> s, events <used>/<limit>, calls <used>/<limit>, elapsed <used>/<limit> ms; exhausted: <kinds|none>.
   <document> records: returned <n> of <n> collected (in-window <n> of <n>), max_records_returned <n>; resumed after <resume_after|none> (<before_resume.total> before it); omitted <n> (in-window <n>, too large <n>), limited by <limited_by|none>, next cursor <next_cursor|none>; a presentation limit, not a coverage gap.
   - `<source_id>` (<product>, `<source_tool>`): outcome `<outcome>`; reasons <reasons|none>; failure <`kind`|none>; queried <start> to <end> (`<window_coverage>`) or queried none (`unknown`); filters <key=value|none>; returned <n>, cap <n>, has_more `<true|false|null>`, truncation `<truncation>`, retention `<retention_coverage>`; received <n>, accepted <n>, in-window <n>, out-of-window <n>, untimed <n>, malformed <n>, duplicates <n>, conflicting <n>, boundary-uncertain <n>.
   ```

   Then the complete-coverage or all-clear sentence when
   [allowed](#coverage-and-limitations), or the gap that rules it out, and the
   retention sentence when any source is `empty`.
3. **Observations:** one line per record in the view, in the view's order,
   copied field by field from the record. Cite one line per record you report;
   a summary by type or count may follow the lines, never replace them:

   ```text
   - `<evidence_id>` <time.utc, or time `<time.status>`> (<product>, `<source_tool>`, record `<source_record_id>`): <summary> `<event_type>`; mapping `<mapping.status>`.
   ```

   Write `(no summary)` when `summary` is null. For a record with no usable
   time, add its original time field, type and value after the mapping. For
   each field in `truncated`, end the line with `; truncated <field> from <n>
   characters`, so the cut is never presented as the whole text. Copy every
   cited value exactly as returned: times, IDs, MACs and summaries. Never
   reformat or round a time: `2026-08-08T11:59:59.999000Z` is cited as written,
   never as `2026-08-08T11:59:59.999Z`. Any other change to a cited value is a
   shortening: end the line with `; shortened <field> in this report from <n>
   characters`.
   `source_tool` is the read family named in the record (for example
   `unifi_list_events`), not the evidence tool you called. Anywhere else in
   the report, refer to a record by its full `evidence_id` in backticks. Never
   abbreviate a citation: no bare record IDs, no product prefixes such as
   `N/` or `P/`, no ellipses.
4. **Hypotheses:** each is labelled a correlation, names the observations it
   rests on, and gives at least one alternative explanation. Timing and
   proximity are correlation; the evidence never states cause.
5. **Identity:** only explicit, source-backed attribution: a MAC, a camera ID,
   a recorded account. A device or account is not a person. Object classes such
   as `person` identify no one.
6. **Unanswered Questions and Next Reads:** what the evidence cannot answer,
   and the bounded follow-ups from step 5, each with the call it would make.

Worked reports for complete evidence with records omitted from the view, and
for empty, partial, failed, ambiguously mapped and malformed-time evidence, are in
[references/report-examples.md](references/report-examples.md). Read it before
writing your first report.

## Example Prompts

- "Switch `aa:bb:cc:00:10:02` dropped off at 8:45 this morning, New York time.
  What happened between 8:00 and 9:00?"
- "The front-door AP went offline around 02:00 UTC on 8 August. Camera
  `cam-fixture-000a` is plugged into it. Investigate 01:30 to 02:30 UTC."
