---
name: security-patrol
description: Review retrieved activity at one area in a given time window from the cloud worker's merged Network and Protect timeline, with Access door events read separately. Needs the cloud worker with a connected relay. Use when the user asks about activity at a door, entrance, room, or area.
---

# Security Patrol

## Dependencies

Requires: worker
Optional: network, protect, access

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

The timeline collects Network and Protect evidence only; it reports Access as
`unsupported`. Access door events come from a separate Access read, never from
the timeline. Security Patrol needs at least one available product; a
multi-product claim needs at least two. A timeline response alone does not
establish complete source coverage.

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

Report the timeline's own coverage (`overall`, `coverage_complete`, each source's
outcome and `budgets.exhausted`) separately from the Access read, which has its own
returned count and limit.

Separate **Observations** (cite source/tool, record ID and timestamp when available),
**Hypotheses** (correlations and alternative explanations), and **Identity** (only
explicit source-backed credential/account attribution, with its limits). Timing,
similar names, proximity, or absence of a matching event alone proves neither
identity nor cause. A credential event identifies the recorded account, not who
physically used it. Missing mappings or clock uncertainty limit correlations.

You are reviewing activity at one area across the connected UniFi products.

## What You Do

Given an area (e.g., "front entrance", "server room", "main door") and a time window, you:

1. Turn the area into exact identifiers: the Network devices (access points,
   switches) and Protect cameras that cover it. The timeline filters by exact
   identifier only and never matches area names. Ask the user, or show
   candidates from read-only lookups such as `unifi_list_devices(search="entrance")`
   and `protect_list_cameras()` and let the user choose. Never pick a device or
   camera by name similarity.
2. Confirm the window with a date and timezone, as ISO 8601 with an explicit offset.
3. Call the timeline with the confirmed identifiers:
   `unifi_location_timeline(start="2026-08-08T08:00:00-04:00", end="2026-08-08T09:00:00-04:00", device_macs=["aa:bb:cc:00:10:01"], camera_ids=["cam-fixture-000a"])`.
   Read the default view; when `record_selection.next_cursor` is set, offer the
   same call with `resume_after` set to it.
4. If the user wants door events, read them separately for the same window
   (here in UTC), for example `access_list_events(start="2026-08-08T12:00:00Z", end="2026-08-08T13:00:00Z", door_id="<door UUID>", limit=200)`,
   with the door UUID from `access_list_doors()` confirmed by the user. When the
   returned count equals `limit`, label the Access read capped.
5. Interpret the records, labelling every correlation as a hypothesis:
   - Motion with no door event found in the retrieved records (coverage and
     alternate entry paths may explain the gap)
   - Network events on the area's devices when someone arrives
   - Access denied followed by continued motion
   - Device or camera outages that coincide
6. Present a clear narrative: what happened, in what order, and what's notable,
   citing each record.

## Example Prompts

- "Show me everything that happened at the front entrance in the last hour"
- "What activity was there near the server room overnight?"
- "Security check on the loading dock since 6 PM"
