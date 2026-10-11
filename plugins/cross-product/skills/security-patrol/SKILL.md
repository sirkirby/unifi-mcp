---
name: security-patrol
description: Summarize retrieved activity at a specific area across all UniFi products (Network, Protect, Access) in a given time window. Use when the user asks about activity at a door, entrance, room, or area.
---

# Security Patrol

## Dependencies

Requires: relay
Optional: network, protect, access

Verify required tools through MCP discovery before collecting data; discovery alone
does not prove controller connectivity or authorization. If a required server/tool
is missing or a required read fails, stop and report it unavailable. Optional sources
may be skipped only when the report visibly names the missing source and resulting
coverage limits. Use the product setup skill for connection help; never request secrets.

The relay provides `unifi_location_timeline`; local product servers do not. If it
is unavailable, stop the merged-timeline workflow and report “No merged timeline
available.” Offer separate local product reads with their own coverage labels.
Security Patrol needs at least one available product; a multi-product claim needs
at least two. A relay response alone does not establish complete source coverage.

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

You are investigating activity at a specific area across all connected UniFi products.

## What You Do

Given an area (e.g., "front entrance", "server room", "main door") and a time window, you:

1. Call `unifi_location_timeline` with the area_hint and time range
2. Interpret the unified timeline — look for patterns:
   - Motion with no badge-in found in retrieved records (coverage and alternate entry paths may explain the gap)
   - New devices appearing when someone arrives
   - Access denied followed by continued motion
   - Device/camera outages that coincide
3. Present a clear narrative: what happened, in what order, and what's notable

## Example Prompts

- "Show me everything that happened at the front entrance in the last hour"
- "What activity was there near the server room overnight?"
- "Security check on the loading dock since 6 PM"
