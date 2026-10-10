# Incident evidence contract

`unifi_core.incident_evidence` is the one versioned, closed model every incident
surface uses to say what it observed, where each observation came from, and what
it could not check. MCP tools, API routes, the relay and the worker consume it;
none of them define their own evidence semantics.

| Piece | Location |
|-------|----------|
| Contract, time parsing, mapping, coverage and assembly | `packages/unifi-core/src/unifi_core/incident_evidence.py` |
| Network normalizers | `packages/unifi-core/src/unifi_core/network/incident_evidence.py` |
| Protect normalizers | `packages/unifi-core/src/unifi_core/protect/incident_evidence.py` |
| JSON Schema artifact | `tests/fixtures/incident_evidence/incident-evidence.v1.schema.json` |
| Golden corpus | `tests/fixtures/incident_evidence/cases/*.json` |
| Invalid corpus | `tests/fixtures/incident_evidence/invalid/*.json` |
| Legacy timeline projection | `unifi_core.event_timeline.normalized_event_from_record` |

Normalizers are pure: no controller I/O, no app imports. Collection (calling
managers or tools, enforcing budgets) belongs to the caller.

## Shape

An `IncidentEvidence` set carries `schema` and `schema_version`, the requested
window, budgets, any mapping assertions, one `SourceResult` per source call and
the `EvidenceRecord`s those sources produced. `overall` and `coverage_complete`
are derived and validated, never trusted from the producer.

- **Provenance.** Each record names its product, API family, source tool,
  endpoint when known, controller/site/location scope, query parameters,
  collection time, and the source record ID exactly as returned (string or
  integer) with the field it came from. Evidence IDs are typed
  (`<source>:int:7` and `<source>:str:7` are different records). Records
  without an ID get a `<source>:sha256:<hash>` evidence ID instead of an
  invented one. Identical repeats collapse into one record; differing records
  under one source ID are all kept as a conflict group
  (`<source>:str:<id>#<hash>`) and block complete coverage. Results do not
  depend on input order. Secret-named keys are excluded from queries, filters
  and attributes; tool error text is never copied.
- **Time.** Windows are half-open, `start <= t < end`, compared in UTC at the
  timestamp's stated precision. Each record keeps the original field, type and
  value, the format (epoch seconds or milliseconds by magnitude, or ISO 8601),
  offset, precision and any known clock uncertainty, plus a fixed-width UTC
  string whose lexical order is time order. Missing, malformed,
  timezone-less (`ambiguous_timezone`) and out-of-window times are explicit
  statuses; collection time never stands in for event time. Protect event time
  is the event `start`, so an event that began before the window is
  out-of-window even if its `end` falls inside.
- **Mapping.** Records list the identifiers they state (Network MACs by role,
  Protect camera IDs). Mappings resolve only against explicit
  `MappingAssertion`s by exact identifier (MACs ignore case and separators):
  one target is `verified`, several are `ambiguous`, none is `missing`. Names
  and nearby timestamps never create a mapping or an identity. Protect
  recognized-face and plate fields are not carried.
- **Coverage.** Each source reports requested and queried windows, filters,
  pagination (offset, requested and effective cap, returned, `has_more`,
  reported total, whether results were filtered after the cap, whether the read
  was interrupted), truncation (`not_truncated`, `truncated`, `unknown`) and
  counts of received, accepted, in-window, out-of-window, untimed, malformed,
  duplicate, conflicting and boundary-uncertain records. The queried window
  comes from bounds captured around the request, never from collection time.
  Coverage is complete only when the queried window covers the requested one,
  the tail is not truncated, the read started at offset 0 and was not
  interrupted, and no record is malformed, untimed, conflicting, or out of
  window but within known clock uncertainty of a boundary. A short list after
  an offset, after post-cap filtering, or at a clamped cap never proves
  completeness. `population_total` is set only when coverage is complete.
- **Failure.** Sources end `complete`, `empty`, `partial` (with sorted
  reasons), or one of `unavailable`, `auth_failed`, `permission_denied`,
  `timeout`, `unsupported`, `parse_failed`, `not_attempted`. A response that
  broke off keeps its records as `partial` with the failure attached. A failed
  source makes no window or pagination claim. `failure_from_exception` never
  raises; unclassifiable errors are `unavailable`. The Network event manager
  raises `UniFiMalformedResponseError` for an unreadable envelope instead of
  returning an empty list, which classifies as `parse_failed`.
- **Overall.** `failed` when no source returned data, `empty` only when every
  source is a complete empty success, `complete` when every source is complete
  or empty and no budget is exhausted, otherwise `partial`. Only
  `coverage_complete` evidence (complete or empty) may support an all-clear.
- **Budgets.** Window, event, call and elapsed limits are inputs; usage and the
  exhausted kinds are reported. A window longer than its budget, or any
  overrun, must be reported exhausted, and exhaustion makes the set partial.
- **Ordering.** Records sort by UTC time, then product, source ID, source
  record ID and evidence ID; untimed records sort last.

## Current product contracts

Adapters follow the current manifests, not assumed uniform arguments:

| Tool | Arguments | Records at |
|------|-----------|-----------|
| `unifi_list_events` | `within_hours` (lookback from now), `limit`, `start` (offset), `event_type`, `categories`, `severities` | top-level `events` |
| `unifi_list_alarms` | `include_archived`, `limit` (no time range) | top-level `alarms` |
| `protect_list_events` | `start`, `end` (ISO 8601), `limit`, `event_type`, `camera_id`, `compact`, `metadata_fields` | `data.events` |
| `protect_list_smart_detections` | `start`, `end`, `limit`, `detection_type`, `camera_id`, `min_confidence`, `compact`, `metadata_fields` | `data.detections` |

The context helpers (`network_events_context`, `network_alarms_context`,
`protect_events_context`) take the tool arguments plus what the collector
captured around the call:

- Network events need `request_started_at` (taken just before the call) and
  `collected_at` (when it returned). The manager reads its clock somewhere in
  between, so only `[collected_at - within_hours, request_started_at]` is
  certainly covered. `start` is an offset; any value but 0 leaves a prefix
  uncollected. `api_path` (`v2` or `legacy`) selects the effective cap: the
  legacy path clamps to 3000, and an unknown path assumes it.
- Network alarms read one v2 page of at most 100, or every legacy alarm; the
  window is the v2 30-day lookback when `api_path="v2"` and
  `request_started_at` are given, otherwise caller-supplied or unknown.
- Protect `start`/`end` that are omitted or unparseable reach the controller as
  no bound, so the queried window is unknown. `compact` and `metadata_fields`
  are recorded in the query because `metadata_fields` changes the request path.
  Smart detections are filtered by confidence after the controller applies
  `limit`; the effective threshold (`min_confidence`, or the server's
  `smart_detection_min_confidence`, exposed on the Protect `EventManager`) is
  recorded and a non-zero threshold marks the list post-filtered.

## What the JSON Schema checks, and what consumers must check

The schema artifact encodes every rule that one JSON object can express on its
own: closed objects and enums, `overall`/`coverage_complete` agreement with
source outcomes and budget exhaustion, success/partial/failure outcome
shapes, failure kind per outcome, complete-coverage preconditions (covered
window, not truncated, offset 0, not interrupted, zero malformed, untimed,
conflicting and boundary-uncertain records), placed versus unplaced times, and
mapping outcome shapes.

JSON Schema cannot compare values across objects or recompute derived values,
so a schema-valid document can still overstate evidence. Consumers that do not
call `validate_incident_evidence` must also check:

1. Every source's `requested_window` equals the set's `requested_window`.
2. Each record's time status, UTC value, format, offset, precision and
   boundary flag follow from its original timestamp, clock uncertainty and the
   half-open requested window.
3. Each record's mapping equals resolving its entities against `mappings` by
   exact identity (MACs compared case- and separator-insensitively).
4. Window coverage follows from comparing the queried and requested windows;
   truncation follows from pagination (`has_more`, reported total versus
   offset plus returned, effective cap, post-filtering, interruption).
5. Source counts, conflict groups and observed first/last times match the
   records that cite the source; `population_total` equals the in-window count.
6. `partial_reasons` are exactly the reasons the coverage establishes.
7. Records cite a listed source, carry that source's provenance, have unique
   evidence IDs derived from the typed source record ID, and are in
   deterministic order.
8. A window longer than the window budget is reported exhausted, and budget
   usage agrees with the exhausted list.
9. No secret-named key appears in queries, filters or attributes.

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
from there. Each case holds the raw per-source payloads and call arguments
(`input`) and the normalized evidence (`expected`). TypeScript consumers
validate `expected` against the schema artifact and must reproduce it from
`input` without importing Python, and reject every case under `invalid/`.

`unifi_core.event_timeline` keeps `NormalizedEvent`, `merge_timelines` and
`filter_by_area` unchanged for existing callers. `normalized_event_from_record`
projects timed evidence onto that legacy shape and returns `None` for untimed
records. A projected list drops coverage and failure state, so callers that
return it must also return the evidence set's source outcomes. The relay
location timeline and the worker timeline still use the legacy path; moving
them onto this contract means calling the current tool names and arguments
above, reading each tool's record path, and reporting per-source outcomes
instead of skipping failed sources.
