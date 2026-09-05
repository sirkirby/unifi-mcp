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

| Category | Create | Update | Delete |
|----------|--------|--------|--------|
| `acl_rules` | `UNIFI_POLICY_NETWORK_ACL_RULES_CREATE` | `UNIFI_POLICY_NETWORK_ACL_RULES_UPDATE` | `UNIFI_POLICY_NETWORK_ACL_RULES_DELETE` |
| `client_groups` | `UNIFI_POLICY_NETWORK_CLIENT_GROUPS_CREATE` | `UNIFI_POLICY_NETWORK_CLIENT_GROUPS_UPDATE` | `UNIFI_POLICY_NETWORK_CLIENT_GROUPS_DELETE` |
| `clients` | — | `UNIFI_POLICY_NETWORK_CLIENTS_UPDATE` | `UNIFI_POLICY_NETWORK_CLIENTS_DELETE` |
| `devices` | — | `UNIFI_POLICY_NETWORK_DEVICES_UPDATE` | `UNIFI_POLICY_NETWORK_DEVICES_DELETE` |
| `events` | — | `UNIFI_POLICY_NETWORK_EVENTS_UPDATE` | — |
| `firewall_policies` | `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE` | `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE` | `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_DELETE` |
| `mgmt` | — | `UNIFI_POLICY_NETWORK_MGMT_UPDATE` | — |
| `networks` | `UNIFI_POLICY_NETWORK_NETWORKS_CREATE` | `UNIFI_POLICY_NETWORK_NETWORKS_UPDATE` | `UNIFI_POLICY_NETWORK_NETWORKS_DELETE` |
| `port_forwards` | `UNIFI_POLICY_NETWORK_PORT_FORWARDS_CREATE` | `UNIFI_POLICY_NETWORK_PORT_FORWARDS_UPDATE` | `UNIFI_POLICY_NETWORK_PORT_FORWARDS_DELETE` |
| `qos_rules` | `UNIFI_POLICY_NETWORK_QOS_RULES_CREATE` | `UNIFI_POLICY_NETWORK_QOS_RULES_UPDATE` | `UNIFI_POLICY_NETWORK_QOS_RULES_DELETE` |
| `routes` | `UNIFI_POLICY_NETWORK_ROUTES_CREATE` | `UNIFI_POLICY_NETWORK_ROUTES_UPDATE` | `UNIFI_POLICY_NETWORK_ROUTES_DELETE` |
| `snmp` | — | `UNIFI_POLICY_NETWORK_SNMP_UPDATE` | — |
| `system` | `UNIFI_POLICY_NETWORK_SYSTEM_CREATE` | `UNIFI_POLICY_NETWORK_SYSTEM_UPDATE` | `UNIFI_POLICY_NETWORK_SYSTEM_DELETE` |
| `traffic_routes` | `UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_CREATE` | `UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_UPDATE` | `UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_DELETE` |
| `usergroups` | `UNIFI_POLICY_NETWORK_USERGROUPS_CREATE` | `UNIFI_POLICY_NETWORK_USERGROUPS_UPDATE` | `UNIFI_POLICY_NETWORK_USERGROUPS_DELETE` |
| `vouchers` | `UNIFI_POLICY_NETWORK_VOUCHERS_CREATE` | `UNIFI_POLICY_NETWORK_VOUCHERS_UPDATE` | `UNIFI_POLICY_NETWORK_VOUCHERS_DELETE` |
| `vpn_clients` | `UNIFI_POLICY_NETWORK_VPN_CLIENTS_CREATE` | `UNIFI_POLICY_NETWORK_VPN_CLIENTS_UPDATE` | `UNIFI_POLICY_NETWORK_VPN_CLIENTS_DELETE` |
| `vpn_servers` | `UNIFI_POLICY_NETWORK_VPN_SERVERS_CREATE` | `UNIFI_POLICY_NETWORK_VPN_SERVERS_UPDATE` | `UNIFI_POLICY_NETWORK_VPN_SERVERS_DELETE` |
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
