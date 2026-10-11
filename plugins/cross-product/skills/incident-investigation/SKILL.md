---
name: incident-investigation
description: Investigate one UniFi Network device incident (a switch, AP or gateway going offline, disconnecting or misbehaving) over an explicit, bounded time window, with Protect camera context, using only the local read-only evidence tools. Produces a cited report that states its coverage. Use when the user asks what happened to a Network device at a given time.
---

# Network Device Incident Investigation

Investigate one Network device incident over one explicit window. Every claim in
the report cites **evidence**: records and per-source **coverage** returned by
the two incident evidence tools. The local product servers are the whole
transport; nothing here needs the relay.

## Dependencies

Requires: network, protect
Optional: relay

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
- **Relay.** Not used. The relay's merged location timeline carries no
  per-source coverage, so it never substitutes for the evidence tools. When the
  product servers are reached through a relay connection, call the same two
  evidence tools.

Use the product setup skills for connection help; never ask for secrets.

## Coverage and Limitations

Every report has a Coverage and Limitations section built from the evidence
documents, never from memory or from record counts alone:

- One line per evidence document: `overall`, `coverage_complete` and budgets.
- One line per source in each document: outcome, partial reasons, failure,
  queried window, filters, pagination and truncation, and counts (format under
  [Report](#report)).
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
- Counts are retrieved records. `population_total` is a total only when the
  source is complete.
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
- Identity stays with explicit, source-backed identifiers. Faces, plates,
  people's names and similar names never identify a person or establish a
  mapping.

## Workflow

### 1. Confirm the inputs

Collect, before any read:

- **Incident:** what happened, in the user's words.
- **Device:** the exact Network device MAC. If the user gives only a name, ask
  for the MAC, or show candidates from `unifi_list_devices(search="<name>")`
  when that tool is directly listed and let the user choose. Never pick a
  device by name similarity.
- **Window:** start and end with a date and timezone. Convert to ISO 8601 with
  an explicit offset (`2026-08-08T08:00:00-04:00`) and show both forms. Ask for
  a missing date, timezone or end; never assume the client's timezone. The
  window is half-open: `start <= t < end`.
- **Cameras:** cameras the user wants as context, by exact Protect camera ID, or
  "none". A camera named only by a description is resolved in step 3, or
  dropped.
- **Budgets:** state the values you will pass. Defaults: `max_window_seconds`
  equal to the window length, `max_events=1000`, `max_calls=20`,
  `max_elapsed_ms=30000`. A window longer than 86400 seconds needs the user's
  agreement; 2592000 is the hard limit. Each tool caps events at 10000, calls
  at 100 and elapsed time at 120000 ms.

Done when the user has confirmed device MAC, window with offset, camera scope
and budgets.

### 2. Check the evidence tools

In the client's tool list, confirm `unifi_get_incident_evidence` and
`protect_get_incident_evidence` are present and annotated
`readOnlyHint: true`. The default lazy registration mode lists both directly
beside the meta-tools; eager mode lists every tool. Use
`unifi_tool_index(name="unifi_get_incident_evidence", include_schemas=True)`
or `protect_tool_index(name="protect_get_incident_evidence", include_schemas=True)`
to read a schema. A tool that is absent (for example in `meta_only` mode) is
unavailable: apply [Dependencies](#dependencies).

Done when each evidence tool is confirmed listed and read-only, or recorded
as unavailable.

### 3. Establish camera mappings

A **mapping** ties the incident device to a camera by exact identifier. It has
exactly two sources:

- `operator_input`: the user states the relationship for exact IDs ("camera
  `cam-…` is attached to switch `aa:bb:…`").
- `product_inventory`: read-only lookups show an exact-identifier relationship.
  Read the camera's `mac` with `protect_get_camera(camera_id="<id>")`, then
  read that MAC as a Network client with
  `unifi_get_client_details(mac_address="<camera mac>")`. The mapping holds
  when the client's uplink identifier (`ap_mac` for wireless, `sw_mac`, plus
  `sw_port` for a port, when wired) equals the incident device MAC. A client
  record that states no uplink identifier gives no mapping. These are
  current-state reads; say so, because the camera may have been elsewhere
  during the window.

Use these lookups only when the tools are directly listed with
`readOnlyHint: true` (eager mode). Otherwise ask the user for the mapping.

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
    mappings=mappings,
)
```

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

Read each document before writing anything from it:

1. `requested_window` equals the confirmed window in UTC, and every source's
   `coverage.requested_window` equals it.
2. Record `overall` and `coverage_complete`. They agree: `coverage_complete`
   is true exactly for `complete` and `empty`. A document that contradicts
   itself (for example `coverage_complete: true` beside a `partial` source) is
   untrustworthy: report the contradiction and claim nothing complete from it.
3. Per source: outcome and `partial_reasons`, `failure`,
   `coverage.queried_window` and `window_coverage`, `filters`, `pagination`
   (`returned`, `cap`, `has_more`, `total_reported`, `post_filtered`,
   `interrupted`), `truncation`, `counts`, `population_total`.
4. `budgets.exhausted`: any kind listed means collection stopped early, and
   every later source is `not_attempted`.
5. Per record: `time.status` (`in_window`, `out_of_window`, `missing`,
   `malformed`, `ambiguous_timezone`), `time.boundary_uncertain`, and
   `mapping.status` (`verified`, `ambiguous`, `missing`, `not_evaluated`).
   Only `in_window` records are observations of the window. Unplaced and
   out-of-window records are reported under coverage, with their original
   value, never moved into the window.

A bounded follow-up read is worth offering only when it would change coverage:

| Evidence says | Follow-up to offer |
|---|---|
| `window` exhausted | Narrow the window, or raise `max_window_seconds` to its length |
| `events` or `calls` exhausted, or `budget_exhausted` | Repeat that product's call with a larger budget or a narrower window |
| `timeout`, or `elapsed` exhausted | Repeat once with a larger `max_elapsed_ms` |
| `truncation_unknown` from several reads | Split the window so each part fits one page |
| `auth_failed`, `permission_denied`, `unsupported` | None: point to the product setup skill |

Ask before every follow-up, use the same evidence tool, and report each
document separately. List tools return records without continuation state, so
they never complete coverage.

Done when every source in every document has its outcome, coverage and counts
recorded, and every follow-up has been offered or ruled out.

### 6. Write the report

Write the [Report](#report). Done when every section is present, every
observation carries a citation, and every coverage claim matches the documents.

## Report

Use these sections, in order:

1. **Incident and Inputs:** the incident, device MAC, window as given and in
   UTC with its offset, camera scope, mapping assertions with their sources,
   and the budgets passed.
2. **Coverage and Limitations:** one line per document, then one line per
   source:

   ```text
   <document>: overall `<overall>`, coverage_complete `<true|false>`; budgets window <seconds>/<limit> s, events <used>/<limit>, calls <used>/<limit>, elapsed <used>/<limit> ms; exhausted: <kinds|none>.
   - `<source_id>` (<product>, `<source_tool>`): outcome `<outcome>`; reasons <reasons|none>; failure <`kind`|none>; queried <start> to <end> (`<window_coverage>`) or queried none (`unknown`); filters <key=value|none>; returned <n>, cap <n>, has_more `<true|false|null>`, truncation `<truncation>`; received <n>, accepted <n>, in-window <n>, out-of-window <n>, untimed <n>, malformed <n>, duplicates <n>, conflicting <n>, boundary-uncertain <n>.
   ```

   Then the complete-coverage or all-clear sentence when
   [allowed](#coverage-and-limitations), or the gap that rules it out.
3. **Observations:** one line per cited record, in time order:

   ```text
   - `<evidence_id>` <utc, or time `<status>`> (<product>, `<source_tool>`, record `<source record id>`): <summary> `<event_type>`; mapping `<status>`.
   ```

   `source_tool` is the read family named in the record's provenance (for
   example `unifi_list_events`), not the evidence tool you called.
4. **Hypotheses:** each is labelled a correlation, names the observations it
   rests on, and gives at least one alternative explanation. Timing and
   proximity are correlation; the evidence never states cause.
5. **Identity:** only explicit, source-backed attribution: a MAC, a camera ID,
   a recorded account. A device or account is not a person. Object classes such
   as `person` identify no one.
6. **Unanswered Questions and Next Reads:** what the evidence cannot answer,
   and the bounded follow-ups from step 5, each with the call it would make.

Worked reports for complete, empty, partial, failed, ambiguously mapped and
malformed-time evidence are in
[references/report-examples.md](references/report-examples.md). Read it before
writing your first report.

## Example Prompts

- "Switch `aa:bb:cc:00:10:02` dropped off at 8:45 this morning, New York time.
  What happened between 8:00 and 9:00?"
- "The front-door AP went offline around 02:00 UTC on 8 August. Camera
  `cam-fixture-000a` is plugged into it. Investigate 01:30 to 02:30 UTC."
