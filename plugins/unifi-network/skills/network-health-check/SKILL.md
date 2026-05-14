---
name: network-health-check
description: Run a UniFi network health check — diagnose device status, connectivity issues, firmware updates, and system health. Use when asked to check network health, find what's down, diagnose connectivity issues, or get a network status summary.
---

# Network Health Check

## Setup Check

Before running a health check, verify the MCP server is configured:

- Check that `UNIFI_NETWORK_HOST` is set in the environment.
- If it is not set or the connection fails, stop and direct the user to the `unifi-network-setup` skill to configure the UniFi Network MCP server.
- Use `unifi_tool_index` to confirm available tools. If no UniFi tools are listed, the server is not connected.

## Health Check Procedure

Use `unifi_batch` to gather all required data in a single parallel operation:

```
unifi_batch([
  { "tool": "unifi_get_system_info" },
  { "tool": "unifi_get_network_health" },
  { "tool": "unifi_list_devices" },
  { "tool": "unifi_list_alarms" }
])
```

This single batch call replaces sequential tool calls and returns all data needed for the report. Do not call these tools one at a time.

If device or alarm issues are found and more detail is needed, a follow-up batch can add:

```
unifi_batch([
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
- **Offline devices** — any device with `state` != 1. Check `references/device-states.md` for the full state code table.
- **Devices needing updates** — check the `upgradeable` field. Report current vs available firmware version.
- **High-load devices** — check CPU/memory utilization if present in device stats.
- **Devices with poor uptime** — recently rebooted devices may indicate instability.

For each active alarm, classify severity using `references/alarm-types.md` and provide a plain-language explanation with remediation steps from that reference.

## Report Format

Present findings using this structure:

```
## Network Health Report

**Overall Status:** [Healthy / Warning / Critical]
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

A healthy network gets a brief "all clear" summary. Do not manufacture concerns for quiet periods.

## Tips

- Always use `unifi_batch` for initial data gathering — sequential tool calls are significantly slower.
- If `unifi_get_network_health` shows WAN health issues, that likely explains many downstream problems — lead with that finding and follow the WAN → LAN → WLAN → VPN diagnostic priority from `references/health-subsystems.md`.
- Don't overwhelm the user with raw data. Focus on what is broken or needs attention.
- Consult the reference docs before classifying device state codes or alarm meanings — misclassification leads to bad recommendations.
