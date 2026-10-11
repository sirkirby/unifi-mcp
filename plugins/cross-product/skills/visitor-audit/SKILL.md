---
name: visitor-audit
description: Audit visitor activity by correlating Access badge scans with Network client connections. Use when the user wants recorded access activity and nearby network activity, with identity limits.
---

# Visitor Audit

## Dependencies

Requires: access, relay
Optional: network

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

You are auditing visitor activity by correlating physical access with network presence.

## What You Do

Given a time window (e.g., "today", "this week"), you:

1. Call `unifi_location_timeline` filtering for access badge_scan and network client_connect events
2. Describe temporal correlations as hypotheses:
   - Match Access visitor/badge-in times with new Network client connections in the same window
   - List devices observed during each recorded access window; ownership is unknown
3. Present separate Observations, Hypotheses, Identity, and Coverage and Limitations sections. Attribute badge events only to their recorded account; do not infer actual visitor identity, visit duration without exit evidence, or device ownership from timing.

## Example Prompts

- "Who visited today and what devices did they bring?"
- "Visitor audit for this week — any unusual guest device activity?"
- "Show me all badge-ins and associated network connections for the past 24 hours"
