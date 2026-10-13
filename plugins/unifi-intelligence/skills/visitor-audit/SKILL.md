---
name: visitor-audit
description: Audit visitor activity by reading Access door events and setting them beside Network evidence from the cloud worker's timeline near the same doors. Needs the cloud worker with a connected relay. Use when the user wants recorded access activity and nearby network activity, with identity limits.
---

# Visitor Audit

## Dependencies

Requires: access, worker
Optional: network

This skill needs the cloud worker. The cloud worker provides
`unifi_location_timeline` through a connected relay; local product servers do
not. If it is unavailable, stop the merged-timeline workflow and report “No
merged timeline available: this skill needs the cloud worker.” Offer separate
local product reads with their own coverage labels.

Verify required tools through MCP discovery before collecting data; discovery alone
does not prove controller connectivity or authorization. If a required server/tool
is missing or a required read fails, stop and report it unavailable. Optional sources
may be skipped only when the report visibly names the missing source and resulting
coverage limits. Use the product setup skill for connection help; never request secrets.

The timeline collects Network and Protect evidence only and reports Access as
`unsupported`, so this audit never asks it for Access and never presents Access
records as timeline evidence. Access events come from the Access server's own
read-only event tool, reached directly or through the cloud worker. A timeline
response alone does not establish complete source coverage.

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

State the two sources apart: the Access read with its filters, returned count and
limit; and the timeline's Network coverage (`overall`, `coverage_complete`, the
Network source's outcome and `budgets.exhausted`). The timeline's coverage says
nothing about Access.

Separate **Observations** (cite source/tool, record ID and timestamp when available),
**Hypotheses** (correlations and alternative explanations), and **Identity** (only
explicit source-backed credential/account attribution, with its limits). Timing,
similar names, proximity, or absence of a matching event alone proves neither
identity nor cause. A credential event identifies the recorded account, not who
physically used it. Missing mappings or clock uncertainty limit correlations.

You are auditing visitor activity by setting recorded door access beside network
evidence near the same doors.

## What You Do

Given a time window (e.g., "today", "this week"), you:

1. Confirm the window with a date and timezone, and the doors to audit by UUID
   from `access_list_doors()`, or all doors.
2. Read the door events from Access for the window, for example
   `access_list_events(start="2026-08-08T13:00:00Z", end="2026-08-08T21:00:00Z", limit=500)`,
   adding `door_id` for one door. When the returned count equals `limit`, label
   the read capped and offer a narrower window.
3. Turn the doors' surroundings into exact Network device MACs, such as the
   access points that serve the entrance: ask the user, or show candidates from
   `unifi_list_devices(device_type="ap")` and let the user choose. Never pick a
   device by name similarity.
4. Read Network evidence for the same window from the timeline:
   `unifi_location_timeline(start="2026-08-08T09:00:00-04:00", end="2026-08-08T17:00:00-04:00", products=["network"], device_macs=["aa:bb:cc:00:10:01"])`.
   When `record_selection.next_cursor` is set, offer the same call with
   `resume_after` set to it.
5. Describe temporal correlations as hypotheses:
   - Match recorded door events with Network client connections on those devices
     in the same window
   - List devices observed during each recorded access window; ownership is unknown
6. Present separate Observations, Hypotheses, Identity, and Coverage and Limitations
   sections. Attribute door events only to their recorded account; do not infer
   actual visitor identity, visit duration without exit evidence, or device
   ownership from timing.

## Example Prompts

- "Who visited today and what devices did they bring?"
- "Visitor audit for this week — any unusual guest device activity?"
- "Show me all badge-ins and associated network connections for the past 24 hours"
