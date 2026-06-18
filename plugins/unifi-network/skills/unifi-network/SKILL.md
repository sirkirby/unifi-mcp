---
name: unifi-network
description: How to manage UniFi network infrastructure — devices, clients, firewall, VPN, routing, WLANs, Traffic Flows, and statistics. Use this skill when the user mentions UniFi, Ubiquiti, network management, WiFi configuration, firewall rules, port forwarding, VPN, QoS, bandwidth, traffic flows, connected clients, network devices, or any UniFi networking task.
---

# UniFi Network MCP Server

You have access to a UniFi Network MCP server that lets you query and manage a UniFi Network Controller. It provides 177 tools covering devices, clients, firewall, VPN, routing, WLANs, Traffic Flows, statistics, and more.

## Tool Discovery

The server uses **lazy loading** by default — only meta-tools are registered initially. Use them to find and call any tool:

| Meta-Tool | Purpose |
|-----------|---------|
| `unifi_tool_index` | Discover tools by name/description; use `category`, `search`, or `include_schemas` to filter |
| `unifi_execute` | Call any tool by name (essential in lazy mode) |
| `unifi_batch` | Run multiple tools in parallel |
| `unifi_batch_status` | Check async batch job status |

**Workflow:** Call `unifi_tool_index` to find the right tool, then `unifi_execute` to call it. For multiple independent queries, use `unifi_batch` — it's significantly faster than sequential calls.

## Safety Model

The server is "secure by default" because it controls real network infrastructure.

**Read operations** — always available. All `list_*`, `get_*`, and query tools work without special permissions.

**Mutations** — permission-gated with mixed defaults:
- **Enabled by default:** firewall policies, port forwards, traffic routes, QoS rules, VPN clients, ACL rules, vouchers, user groups
- **Disabled by default (high-risk):** networks, WLANs, devices, clients, routes, VPN servers
- **Delete operations** — always disabled by default

If a mutation fails with a permission error, tell the user the env var to set: `UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>=true`

**Confirmation flow** — every mutation uses preview-then-confirm:
1. Default call → returns preview of what would change
2. Call with `confirm=true` → executes the mutation

Always preview first and show the user before confirming.

## Response Format

All tools return: `{"success": true, "data": ...}`, `{"success": false, "error": "..."}`, or `{"success": true, "requires_confirmation": true, "preview": ...}`. Always check `success` first.

**Redacted secrets:** Secret fields — WLAN passphrases (`x_passphrase`), VPN private/preshared keys, whole VPN config blobs (imported WireGuard/OpenVPN config files), and SNMP community strings — come back as `***REDACTED***` by default. Raw values are controlled by process policy (`UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=false` or global `UNIFI_REDACT_SENSITIVE_FIELDS=false`), not by tool arguments. On an update, send **only** the fields you are changing — to keep a secret unchanged, omit it; never echo `***REDACTED***` back, which is rejected so the placeholder can't overwrite the real secret.

## Device Classification

`unifi_list_devices` returns a `device_category` field that accurately classifies devices:
- `ap` — real access points (excludes USP Smart Power strips that report as `uap` type)
- `switch` — switches
- `gateway` — UDM/USG gateways
- `pdu` — smart power strips, UPS devices
- `wan` — cable internet (UCI) devices

Use `device_category` (not `type`) when counting or filtering devices. The `device_type` filter parameter uses this classification.

Additional enriched fields: `upgradable` (bool), `connection_network` (VLAN name), `uplink` (topology), `load_avg_1`, `mem_pct`, `model_eol`.

## Efficiency Tips

- **Batch reads** — `unifi_batch` for parallel queries (biggest efficiency win)
- **`unifi_lookup_by_ip`** — faster than listing all clients when you know the IP
- **Use filters** — most list tools accept time range, type, and ID parameters
- **`unifi_get_top_clients`** — fastest way to find bandwidth hogs
- **`unifi_get_traffic_flows`** — query historical Insights > Flows records when the user asks who talked to what, which ports/protocols were used, or where traffic went
- **Check health first** — `unifi_get_network_health` for quick "is everything OK?"
- **Device counts** — use `device_category` field, not `type`, for accurate AP/switch/PDU counts

## Authentication

Username and password are **required** (local admin credentials, not Ubiquiti SSO). API key support exists but is **experimental** — limited to read-only operations and a subset of tools.

To configure, run `/unifi-network:unifi-network-setup` or set env vars manually:
```
UNIFI_NETWORK_HOST=192.168.1.1
UNIFI_NETWORK_USERNAME=admin
UNIFI_NETWORK_PASSWORD=your-password
```

## Other UniFi Servers

If the user also has cameras or door access control, other UniFi MCP plugins are available:
- `unifi-protect` — security cameras, NVR, recordings, smart detections
- `unifi-access` — door locks, credentials, visitors, access policies

Cameras and access readers appear as network clients — use `unifi_lookup_by_ip` to cross-reference if troubleshooting connectivity for those devices.

## Tool Reference

For the complete list of all 177 tools organized by category with descriptions, tips, and common scenarios, read `references/network-tools.md`.
