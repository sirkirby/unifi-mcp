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
not. Look for it in the client's tool list, which takes no tool call. If it is
not listed, stop with no tool call at all and report “No merged timeline
available: this skill needs the cloud worker.” You may offer separate local
product reads in words, naming the tools you would use; make none until the
user agrees, naming only the reads Safety allows, and give any you then make
their own coverage labels.

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

## Safety

- Use only tools the client lists directly with `readOnlyHint: true`. Never use
  `*_execute` or `*_batch`, even for a lookup: they are not read-only.
- Make no controller read the user has not agreed to. Identifiers come from the
  user.
- Offer only reads the directly listed read-only tools can make: the two
  incident evidence tools for exact identifiers, `protect_get_camera` by camera
  ID and `unifi_get_client_details` by MAC.
  Never offer to list devices, cameras, access points or doors, and never
  reach for `*_load_tools`, `*_execute` or `*_batch`.
- When an identifier is missing, ask the user for it: they can find it in the
  UniFi app, or by running the product's own list tool in eager mode.
- Offer a further page (`resume_after`) or another read; make it only after the
  user says yes.

## What You Do

Given an area (e.g., "front entrance", "server room", "main door") and a time window, you:

1. Turn the area into exact identifiers: the Network devices (access points,
   switches) and Protect cameras that cover it. The timeline filters by exact
   identifier only and never matches area names. Ask the user for the device
   MACs and camera IDs; they can find them in the UniFi app, or by running each
   product's own list tool in eager mode. Never pick a device or camera by name
   similarity.
2. Confirm the window with a date and timezone, as ISO 8601 with an explicit offset.
3. Call the timeline with the confirmed identifiers:
   `unifi_location_timeline(start="2026-08-08T08:00:00-04:00", end="2026-08-08T09:00:00-04:00", device_macs=["aa:bb:cc:00:10:01"], camera_ids=["cam-fixture-000a"])`.
   Read the default view; when `record_selection.next_cursor` is set, offer the
   same call with `resume_after` set to it, and make it only after the user says
   yes.
4. If the user wants door events, read them separately for the same window
   (here in UTC), for example `access_list_events(start="2026-08-08T12:00:00Z", end="2026-08-08T13:00:00Z", door_id="<door UUID>", limit=200)`,
   with the door UUID from the user (from the UniFi Access app, or the Access
   server's own door list tool in eager mode). When the
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
