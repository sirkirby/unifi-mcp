---
name: unifi-network
description: How to manage UniFi network infrastructure — devices, clients, firewall, VPN, routing, WLANs, Traffic Flows, and statistics. Use this skill when the user mentions UniFi, Ubiquiti, network management, WiFi configuration, firewall rules, port forwarding, VPN, QoS, bandwidth, traffic flows, connected clients, network devices, or any UniFi networking task.
---

# UniFi Network MCP Server

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

You have access to a UniFi Network MCP server that lets you query and manage a UniFi Network Controller. It provides 209 tools covering devices, clients, firewall, VPN, routing, WLANs, Traffic Flows, statistics, and more.

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
