---
name: incident-investigation
description: Investigate a network incident by correlating device events with camera footage and physical access logs. Use when the user reports a device going offline, a network anomaly, or wants to understand what caused an infrastructure event.
---

# Network Incident Investigation

## Dependencies

Requires: network, relay
Optional: protect, access

Verify required tools through MCP discovery before collecting data; discovery alone
does not prove controller connectivity or authorization. If a required server/tool
is missing or a required read fails, stop and report it unavailable. Optional sources
may be skipped only when the report visibly names the missing source and resulting
coverage limits. Use the product setup skill for connection help; never request secrets.

The relay provides `unifi_location_timeline`; local product servers do not. If it
is unavailable, stop the merged-timeline workflow and report “No merged timeline
available.” Offer separate local product reads with their own coverage labels.
A relay response alone does not establish complete source coverage.

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

You are investigating a network infrastructure event using cross-product correlation.

## What You Do

Given an incident (e.g., "switch went offline", "AP stopped responding"), you:

1. Get the device event details from Network (device name, time, status change)
2. Call `unifi_location_timeline` with the time window around the incident
3. Look for correlated events:
   - Camera footage near the device location at the time of the incident
   - Physical access events (was someone in the area?)
   - Other devices on the same network segment affected?
4. Present a timeline of what happened with your assessment

## Requirements

- Network server must be connected (this is the primary data source)
- Protect server adds camera correlation (optional but valuable)
- Access server adds physical access context (optional)

## Example Prompts

- "A switch went offline at 2 AM — what happened?"
- "The guest WiFi AP has been dropping — investigate"
- "We lost connectivity to the warehouse at 3:15 PM, what do you see?"
