---
name: security-digest
description: Generate a security digest summarizing events across UniFi Protect cameras, Access door events, and Network firewall activity. Use when asked about what happened overnight, security summary, event digest, recent activity, or reviewing camera and access events.
---

# Security Digest

## Dependencies

Requires: protect
Optional: network, access

Verify required tools through MCP discovery before collecting data; discovery alone
does not prove controller connectivity or authorization. If a required server/tool
is missing or a required read fails, stop and report it unavailable. Optional sources
may be skipped only when the report visibly names the missing source and resulting
coverage limits. Use the product setup skill for connection help; never request secrets.

## Coverage and Limitations

Every report must include a **Coverage and Limitations** section: name each requested
source and its status (available, unavailable, partial, or capped), requested time
window/timezone or current-state collection time, actual filters, returned counts,
limits, pagination, and any failed calls or unknown fields. Counts describe retrieved
records, not totals unless completeness is established. A successful empty query is
an observation; a failed or missing source is unavailable, never an empty result.
If a limit is reached, label the source capped unless further bounded reads establish
coverage. If completeness cannot be established, label it partial. Do not claim
complete coverage, all-clear, or overall health from unavailable, partial, or capped
data; say “No concerning activity found in the retrieved records” when appropriate.

Separate **Observations** (cite source/tool, record ID and timestamp when available),
**Hypotheses** (correlations and alternative explanations), and **Identity** (only
explicit source-backed credential/account attribution, with its limits). Timing,
similar names, proximity, or absence of a matching event alone proves neither
identity nor cause. A credential event identifies the recorded account, not who
physically used it. Missing mappings or clock uncertainty limit correlations.

## Setup Check

Before generating a digest, verify the primary server is reachable:

- Call `protect_tool_index` to discover the Protect tools; then check each required read response for success. Discovery is not a controller connectivity test.
- Server credentials may be supplied outside the agent's environment; do not infer missing configuration from that environment alone.

For full cross-product correlation (CORR-01 through CORR-05), the unifi-network and unifi-access plugins must also be configured. Check availability by calling `unifi_tool_index` and `access_tool_index`. Mark rules that span missing servers unevaluated and name the missing evidence in the single-source report.

## Collection Budget

Choose an explicit interval and timezone before collecting. At most three batches
(one per available product) plus one bounded follow-up batch per product; stop at
six calls or 60 seconds, whichever comes first. Record budget exhaustion as partial.
Do not keep increasing caps to obtain an all-clear. The default smart-detection
confidence filter excludes low-score records; record that filter as a coverage limit.

## Generating a Digest

### Determine the Time Range

Default ranges if the user does not specify:
- **overnight** — last 12 hours (6 pm to 6 am)
- **today** — since midnight
- **recent** — last 4 hours

### Gather Events (parallel batch calls per server)

Use each server's batch tool to gather events in parallel within that server. Do not call these tools one at a time.

**From Protect** (required):

Use `protect_list_smart_detections` as the primary source — these are the highest-signal events (person, vehicle, package, animal). Only add `protect_list_events` with `event_type=motion` if you need raw motion data beyond smart detections. Skip `protect_recent_events` for digests — it only contains the last few minutes of buffered events and adds little value for historical ranges.

```
protect_batch(operations=[
  { "tool": "protect_list_smart_detections", "arguments": { "start": "...", "end": "...", "limit": 50, "compact": true } },
  { "tool": "protect_list_events", "arguments": { "start": "...", "event_type": "ring", "limit": 20, "compact": true } }
])
```

Use `compact=true` on all event queries for digests — it strips thumbnail_id, category, sub_category, and is_favorite fields, reducing response size by ~40%.

Canonical event rows use `camera`; names may be absent. Use `protect_list_cameras` when name resolution is needed and retain the source camera ID.

**From Access** (if available):

```
access_batch(operations=[
  { "tool": "access_list_events", "arguments": { "start": "...", "end": "...", "topic": "unlocks", "limit": 100 } },
  { "tool": "access_list_events", "arguments": { "start": "...", "end": "...", "topic": "access_denial", "limit": 100 } },
  { "tool": "access_get_activity_summary", "arguments": { "days": 1 } }
])
```

**From Network** (if available):

```
unifi_batch(operations=[
  { "tool": "unifi_list_alarms" },
  { "tool": "unifi_list_events", "arguments": { "within_hours": 12, "start": 0, "limit": 100 } }
])
```

The three batch calls (Protect, Access, Network) can be issued concurrently — they target independent servers.

## Analyzing Events

Use these reference documents to classify and correlate the gathered events:

- `references/event-types.md` — guide to event fields and controller-dependent event codes from Protect, Access, and Network, with key fields and digest relevance. Consult before labeling any event type.
- `references/correlation-rules.md` — the five cross-product review heuristics (CORR-01 through CORR-05) with their logic, time windows, and recommended responses. Apply these when data from multiple servers is available.
- `references/severity-model.md` — how base severity is computed and modified by time of day, location, and event frequency. Includes the full classification matrix. Apply this before assigning High/Medium/Low labels.

Smart detection events (person, vehicle, package) are the highest-signal items — prioritize these when reviewing Protect data.

Network `start` is an integer pagination offset, not a timestamp. Set
`within_hours` to cover the requested interval relative to collection time, then
filter returned timestamps to the explicit interval. If historical coverage is
not available, say so. Access defaults to admin events: request `topic="unlocks"`
and `topic="access_denial"` separately; an activity summary or websocket buffer
does not fill historical gaps. Record the 50/20 Protect caps and every other limit.

**Status classification:**
- `clear` — no notable events in the checked scope, only when all requested sources and the full interval have established coverage. Say “No notable events found in the checked scope.”
- `partial` / `unavailable` — any capped, failed, missing, or incompletely covered source; report observations without an all-clear.
- `notable` — medium-severity events present; worth reviewing.
- `alert` — one or more high-severity events or fired correlations; prompt review warranted.

Do not invent concerns for quiet periods.

## Cross-Product Correlation

When events from multiple servers are available, apply the five review heuristics from `references/correlation-rules.md`:

| Rule | Sources | Window | Severity | Pattern |
|------|---------|--------|----------|---------|
| CORR-01 | Protect + Access | 2 min | High | Motion at an entry camera with no corresponding badge-in |
| CORR-02 | Network + Protect | 5 min | Medium | New/unknown device on the network near a person detection |
| CORR-03 | Access + Protect | 10 min | High | Access denied at a door followed by continued motion |
| CORR-04 | Network + Protect | 5 min | High | Network device offline coinciding with camera disconnections |
| CORR-05 | Access + Protect | 5 min | Low | After-hours badge-in with no approach motion before it (audit trail) |

When multiple rules fire on the same events, the highest severity wins and the rules are listed together in a single merged incident. See `references/correlation-rules.md` for full logic and pseudocode.

## Report Format

```
## Security Digest — [date/time range]

### Coverage and Limitations
[Per-source status, interval/timezone, filters, counts/caps, failures and gaps]

### Summary
[1-2 sentence overview]

### Notable Events
[Chronological; only events worth human attention]

**[Time] — [Event description]**
- Source: [Protect/Access/Network]
- Severity: [High/Medium/Low]
- [Correlation rule if applicable]

### Activity Counts
| Source | Events | Notable |
|--------|--------|---------|
| Protect | [count] | person=[n] vehicle=[n] package=[n] |
| Access | [count] | denied=[n] |
| Network | [count] | alarms=[n] |

### Recommendations
[Only if action is warranted]
```

## Tips

- Use each server's batch tool for parallel data gathering within that server. The three server batches (Protect, Access, Network) can run concurrently.
- Smart detections (person, vehicle, package) are the highest-signal events — surface these first when summarizing.
- If only one MCP server is available, produce a single-source digest. Name every missing source in Coverage and Limitations.
- Use `protect_get_event_thumbnail` to offer visual evidence for notable person or vehicle detections when the user wants to see what triggered an alert.
- The most security value comes from overnight and 24h ranges where time-of-day severity modifiers (from `references/severity-model.md`) elevate routine events to notable ones.
- Include Coverage and Limitations before conclusions, including on quiet periods.

## Report Examples

### Unavailable source

**Coverage and Limitations:** Protect unavailable: required event read failed.
No digest could be completed. Access and Network were not queried.
**Observations:** No Protect records retrieved; this is not an empty successful query.
**Hypotheses:** Not assessed. **Identity:** Not assessed.

### Partial coverage

**Coverage and Limitations:** Protect returned 8 records for 00:00–06:00 UTC;
Access unavailable; Network not configured. Cross-product rules unevaluated.
**Observations:** No concerning activity found in the retrieved Protect records.
**Hypotheses:** Missing access evidence prevents assessing badge/motion patterns.
**Identity:** Device ownership and physical identity remain unknown.

### Capped query

**Coverage and Limitations:** Protect smart detections returned 50/50 and rings
20/20 for 00:00–06:00 UTC; both queries capped, completeness unknown. Counts
are retrieved records. Access and Network unavailable.
**Observations:** 50 detections and 20 rings retrieved, not a full activity total.
**Hypotheses:** Additional events may be outside these results.
**Identity:** Timing does not establish who carried a device. Status: partial.
