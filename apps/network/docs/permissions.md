# Permission System — Network Server

All tools are always visible and discoverable. Authorization happens at call time through two concepts: **Permission Mode** and **Policy Gates**.

## Permission Mode

Controls how the server handles mutating tool calls globally.

| Variable | Scope | Values | Default |
|----------|-------|--------|---------|
| `UNIFI_TOOL_PERMISSION_MODE` | All servers | `confirm`, `bypass` | `confirm` |
| `UNIFI_NETWORK_TOOL_PERMISSION_MODE` | Network only | `confirm`, `bypass` | inherits global |

- **`confirm`** (default) — mutating tools require the preview-then-confirm flow before executing
- **`bypass`** — skips confirmation for all mutations; intended for automation workflows

The server-specific variable takes priority over the global one.

## Policy Gates

Fine-grained authorization over which mutations are permitted. Most specific rule wins.

| Specificity | Pattern | Example |
|-------------|---------|---------|
| Global action | `UNIFI_POLICY_<ACTION>` | `UNIFI_POLICY_DELETE=false` |
| Server + action | `UNIFI_POLICY_NETWORK_<ACTION>` | `UNIFI_POLICY_NETWORK_CREATE=true` |
| Server + category + action | `UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>` | `UNIFI_POLICY_NETWORK_DEVICES_UPDATE=true` |

Actions: `CREATE`, `UPDATE`, `DELETE`

Accepted values: `true`, `1`, `yes`, `on` (case-insensitive). Unset means the next less-specific rule applies.

## Network Categories

The `<CATEGORY>` segment is the config key in the left column. `tools_manifest.json`
records a shorthand per tool (`client_group`, `firewall`, `oon_policy`) that the server
maps to these keys in `unifi_network_mcp/categories.py`; a variable built from the
shorthand, such as `UNIFI_POLICY_NETWORK_CLIENT_GROUP_DELETE`, is never read. A denied
tool's error names the exact variable to set. A dash means no tool gates on that
action, so the variable has no effect.

| Category | Create | Update | Delete |
|----------|--------|--------|--------|
| `acl_rules` | `UNIFI_POLICY_NETWORK_ACL_RULES_CREATE` | `UNIFI_POLICY_NETWORK_ACL_RULES_UPDATE` | `UNIFI_POLICY_NETWORK_ACL_RULES_DELETE` |
| `client_groups` | `UNIFI_POLICY_NETWORK_CLIENT_GROUPS_CREATE` | `UNIFI_POLICY_NETWORK_CLIENT_GROUPS_UPDATE` | `UNIFI_POLICY_NETWORK_CLIENT_GROUPS_DELETE` |
| `clients` | — | `UNIFI_POLICY_NETWORK_CLIENTS_UPDATE` | — |
| `content_filters` | — | `UNIFI_POLICY_NETWORK_CONTENT_FILTERS_UPDATE` | `UNIFI_POLICY_NETWORK_CONTENT_FILTERS_DELETE` |
| `devices` | `UNIFI_POLICY_NETWORK_DEVICES_CREATE` | `UNIFI_POLICY_NETWORK_DEVICES_UPDATE` | — |
| `dns` | `UNIFI_POLICY_NETWORK_DNS_CREATE` | `UNIFI_POLICY_NETWORK_DNS_UPDATE` | `UNIFI_POLICY_NETWORK_DNS_DELETE` |
| `dynamic_dns` | `UNIFI_POLICY_NETWORK_DYNAMIC_DNS_CREATE` | `UNIFI_POLICY_NETWORK_DYNAMIC_DNS_UPDATE` | `UNIFI_POLICY_NETWORK_DYNAMIC_DNS_DELETE` |
| `events` | — | `UNIFI_POLICY_NETWORK_EVENTS_UPDATE` | — |
| `firewall_policies` | `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE` | `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE` | `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_DELETE` |
| `gateway_settings` | — | `UNIFI_POLICY_NETWORK_GATEWAY_SETTINGS_UPDATE` | — |
| `networks` | `UNIFI_POLICY_NETWORK_NETWORKS_CREATE` | `UNIFI_POLICY_NETWORK_NETWORKS_UPDATE` | `UNIFI_POLICY_NETWORK_NETWORKS_DELETE` |
| `oon_policies` | `UNIFI_POLICY_NETWORK_OON_POLICIES_CREATE` | `UNIFI_POLICY_NETWORK_OON_POLICIES_UPDATE` | `UNIFI_POLICY_NETWORK_OON_POLICIES_DELETE` |
| `port_forwards` | `UNIFI_POLICY_NETWORK_PORT_FORWARDS_CREATE` | `UNIFI_POLICY_NETWORK_PORT_FORWARDS_UPDATE` | `UNIFI_POLICY_NETWORK_PORT_FORWARDS_DELETE` |
| `qos_rules` | `UNIFI_POLICY_NETWORK_QOS_RULES_CREATE` | `UNIFI_POLICY_NETWORK_QOS_RULES_UPDATE` | — |
| `routes` | `UNIFI_POLICY_NETWORK_ROUTES_CREATE` | `UNIFI_POLICY_NETWORK_ROUTES_UPDATE` | — |
| `snmp` | — | `UNIFI_POLICY_NETWORK_SNMP_UPDATE` | — |
| `switch` | `UNIFI_POLICY_NETWORK_SWITCH_CREATE` | `UNIFI_POLICY_NETWORK_SWITCH_UPDATE` | `UNIFI_POLICY_NETWORK_SWITCH_DELETE` |
| `system` | `UNIFI_POLICY_NETWORK_SYSTEM_CREATE` | `UNIFI_POLICY_NETWORK_SYSTEM_UPDATE` | `UNIFI_POLICY_NETWORK_SYSTEM_DELETE` |
| `traffic_routes` | — | `UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_UPDATE` | — |
| `usergroups` | `UNIFI_POLICY_NETWORK_USERGROUPS_CREATE` | `UNIFI_POLICY_NETWORK_USERGROUPS_UPDATE` | — |
| `vouchers` | `UNIFI_POLICY_NETWORK_VOUCHERS_CREATE` | — | `UNIFI_POLICY_NETWORK_VOUCHERS_DELETE` |
| `vpn_clients` | — | `UNIFI_POLICY_NETWORK_VPN_CLIENTS_UPDATE` | `UNIFI_POLICY_NETWORK_VPN_CLIENTS_DELETE` |
| `vpn_servers` | — | `UNIFI_POLICY_NETWORK_VPN_SERVERS_UPDATE` | — |
| `wlans` | `UNIFI_POLICY_NETWORK_WLANS_CREATE` | `UNIFI_POLICY_NETWORK_WLANS_UPDATE` | `UNIFI_POLICY_NETWORK_WLANS_DELETE` |

## Common Scenarios

### Zero config (default)

No configuration needed. All tools work — reads execute immediately, mutations require confirmation (preview-then-confirm). This is the safest default.

### Restrict to firewall and routing changes only

```bash
UNIFI_POLICY_NETWORK_CREATE=false
UNIFI_POLICY_NETWORK_UPDATE=false
UNIFI_POLICY_NETWORK_DELETE=false
UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE=true
UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true
UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_CREATE=true
UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_UPDATE=true
UNIFI_POLICY_NETWORK_PORT_FORWARDS_CREATE=true
UNIFI_POLICY_NETWORK_PORT_FORWARDS_UPDATE=true
```

### Lock down deletes only

```bash
UNIFI_POLICY_NETWORK_DELETE=false
```

### Full bypass for automation (no confirmations, all mutations)

```bash
UNIFI_NETWORK_TOOL_PERMISSION_MODE=bypass
UNIFI_POLICY_NETWORK_CREATE=true
UNIFI_POLICY_NETWORK_UPDATE=true
UNIFI_POLICY_NETWORK_DELETE=true
```

### Claude Desktop example

```json
{
  "env": {
    "UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE": "true",
    "UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE": "true",
    "UNIFI_POLICY_NETWORK_DEVICES_UPDATE": "true"
  }
}
```

## Confirmation Flow

When `UNIFI_NETWORK_TOOL_PERMISSION_MODE=confirm` (default), mutating tools follow a two-step pattern:

1. Call without `confirm` — returns a preview of the change, no mutation occurs
2. Call with `confirm=true` — executes the mutation

This applies even when a policy gate permits the action.

## Backwards Compatibility

The following deprecated variables are still accepted but will be removed in a future release:

| Deprecated | Equivalent |
|------------|-----------|
| `UNIFI_AUTO_CONFIRM=true` | `UNIFI_TOOL_PERMISSION_MODE=bypass` |
| `UNIFI_PERMISSIONS_<CAT>_<ACTION>=true` | `UNIFI_POLICY_NETWORK_<CAT>_<ACTION>=true` |

Deprecated variables are resolved before new-style variables and have lower priority if both are set.
