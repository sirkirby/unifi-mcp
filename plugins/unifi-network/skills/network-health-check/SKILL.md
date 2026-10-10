---
name: network-health-check
description: Run a UniFi network health check — diagnose device status, connectivity issues, firmware updates, and system health. Use when asked to check network health, find what's down, diagnose connectivity issues, or get a network status summary.
---

# Network Health Check

## Dependencies

Requires: network
Optional: none

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

Before running a health check, verify the MCP server is configured:

- Verify tool availability and the required read responses; the MCP server may have its own environment or credential provider.
- If required reads fail, stop and direct the user to the `unifi-network-setup` skill.
- Use `unifi_tool_index` to confirm available tools. If no UniFi tools are listed, the server is not connected.

## Health Check Procedure

Use `unifi_batch` to gather all required data in a single parallel operation:

```
unifi_batch(operations=[
  { "tool": "unifi_get_system_info" },
  { "tool": "unifi_get_network_health" },
  { "tool": "unifi_list_devices" },
  { "tool": "unifi_list_alarms" }
])
```

This single batch call replaces sequential tool calls and returns all data needed for the report. Do not call these tools one at a time.

If device or alarm issues are found and more detail is needed, a follow-up batch can add:

```
unifi_batch(operations=[
  { "tool": "unifi_list_clients" },
  { "tool": "unifi_get_top_clients" }
])
```

## Analyzing Results

Use these reference documents to interpret the data returned by the batch call:

- `references/device-states.md` — maps device `state` integer codes to human-readable status (online, offline, isolated, etc.) and explains what each state means operationally. Do not guess at state codes — consult this reference before classifying device status.
- `references/alarm-types.md` — describes known alarm types, their severity levels, and recommended remediation steps. Consult before classifying alarm severity or suggesting actions.
- `references/health-subsystems.md` — explains the per-subsystem health fields returned by `unifi_get_network_health` (WAN, LAN, WLAN, VPN), how to interpret `status` values, and the recommended diagnostic priority order: **WAN → LAN → WLAN → VPN**.

From the device list, identify:
- **Non-online devices** — any device with `state` != 1; these are not all offline. Check `references/device-states.md` for the full state code table.
- **Devices needing updates** — check the `upgradeable` field. Report current vs available firmware version.
- **High-load devices** — check CPU/memory utilization if present in device stats.
- **Devices with poor uptime** — recently rebooted devices may indicate instability.

For each active alarm, classify severity using `references/alarm-types.md` and provide a plain-language explanation with remediation steps from that reference.

## Report Format

Present findings using this structure:

```
## Network Health Report

**Overall Status:** [Healthy within checked scope / Warning / Critical / Unavailable / Partial]
**Controller:** [version] — uptime [X days]

### Devices ([online]/[total])
- [List any offline or problematic devices with their state code and meaning]
- [List devices needing firmware updates with current and available versions]

### Active Alarms ([count])
- [Summarize each alarm with severity and recommendation]

### Recommendations
1. [Actionable item]
2. [Actionable item]
```

When all required reads succeeded with established coverage, summarize “No issues found in the checked scope.” Otherwise report partial or unavailable coverage, even when no issues were retrieved.

## Tips

- Always use `unifi_batch` for initial data gathering — sequential tool calls are significantly slower.
- If `unifi_get_network_health` shows WAN health issues, that likely explains many downstream problems — lead with that finding and follow the WAN → LAN → WLAN → VPN diagnostic priority from `references/health-subsystems.md`.
- Don't overwhelm the user with raw data. Focus on what is broken or needs attention.
- Consult the reference docs before classifying device state codes or alarm meanings — misclassification leads to bad recommendations.
