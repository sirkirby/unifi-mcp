---
name: unifi-network
description: How to manage UniFi network infrastructure — devices, clients, firewall, VPN, routing, WLANs, Traffic Flows, and statistics. Use this skill when the user mentions UniFi, Ubiquiti, network management, WiFi configuration, firewall rules, port forwarding, VPN, QoS, bandwidth, traffic flows, connected clients, network devices, or any UniFi networking task.
---

# UniFi Network MCP Server

You have access to a UniFi Network MCP server that lets you query and manage a UniFi Network Controller. It provides 194 tools covering devices, clients, firewall, VPN, routing, WLANs, Traffic Flows, statistics, and more.

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

If a mutation fails with a permission error, tell the user the env var to set: `UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>=true`. Use the exact variable named in the error: `<CATEGORY>` is the server's config key (`CLIENT_GROUPS`, `FIREWALL_POLICIES`, `OON_POLICIES`), not the `permission_category` shorthand in `tools_manifest.json` (`client_group`, `firewall`, `oon_policy`), and a variable built from the shorthand is never read.

**Confirmation flow** — every mutation uses preview-then-confirm:
1. Default call → returns preview of what would change
2. Call with `confirm=true` → executes the mutation

Always preview first and show the user before confirming.

## Response Format

All tools return: `{"success": true, "data": ...}`, `{"success": false, "error": "..."}`, or `{"success": true, "requires_confirmation": true, "preview": ...}`. Always check `success` first. Network/WLAN and VPN-state writes are read back after execution and also report `mutation_applied`, `partial_success`, `persisted_fields`, `unchanged_fields`, `dropped_fields`, `coerced_fields`, and actual post-write details. Already-satisfied no-op fields appear in `unchanged_fields` and do not make a failed write partially successful. A failed confirmed write is not necessarily a rollback; inspect those fields before retrying or compensating.

**Redacted secrets:** Secret fields — WLAN passphrases (`x_passphrase`), VPN private/preshared keys, whole VPN config blobs (imported WireGuard/OpenVPN config files), SNMP community strings, SNMPv3 passwords, and device-SSH credentials — come back as `***REDACTED***` by default. Raw values are controlled by process policy (`UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=false` or global `UNIFI_REDACT_SENSITIVE_FIELDS=false`), not by tool arguments. On an update, send **only** the fields you are changing — to keep a secret unchanged, omit it; never echo `***REDACTED***` back, which is rejected so the placeholder can't overwrite the real secret.
