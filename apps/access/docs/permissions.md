# Permission System — Access Server

All tools are always visible and discoverable. Authorization happens at call time through two concepts: **Permission Mode** and **Policy Gates**.

## Permission Mode

Controls how the server handles mutating tool calls globally.

| Variable | Scope | Values | Default |
|----------|-------|--------|---------|
| `UNIFI_TOOL_PERMISSION_MODE` | All servers | `confirm`, `bypass` | `confirm` |
| `UNIFI_ACCESS_TOOL_PERMISSION_MODE` | Access only | `confirm`, `bypass` | inherits global |

- **`confirm`** (default) — mutating tools require the preview-then-confirm flow before executing
- **`bypass`** — skips confirmation for all mutations; intended for automation workflows

The server-specific variable takes priority over the global one.

## Policy Gates

Fine-grained authorization over which mutations are permitted. Most specific rule wins.

| Specificity | Pattern | Example |
|-------------|---------|---------|
| Global action | `UNIFI_POLICY_<ACTION>` | `UNIFI_POLICY_DELETE=false` |
| Server + action | `UNIFI_POLICY_ACCESS_<ACTION>` | `UNIFI_POLICY_ACCESS_CREATE=true` |
| Server + category + action | `UNIFI_POLICY_ACCESS_<CATEGORY>_<ACTION>` | `UNIFI_POLICY_ACCESS_DOORS_UPDATE=true` |

Actions: `CREATE`, `UPDATE`, `DELETE`

Accepted values: `true`, `1`, `yes`, `on` (case-insensitive). Unset means the next less-specific rule applies.

## Access Categories

Access defaults all mutations to denied. Operations control physical security hardware — doors, locks, and credential assignments — so explicit opt-in is required for every action.

| Category | Create | Update | Delete | Notes |
|----------|--------|--------|--------|-------|
| `credentials` | `UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE` | — | `UNIFI_POLICY_ACCESS_CREDENTIALS_DELETE` | NFC, PIN, mobile credentials |
| `devices` | — | `UNIFI_POLICY_ACCESS_DEVICES_UPDATE` | — | Hub/reader reboot |
| `doors` | — | `UNIFI_POLICY_ACCESS_DOORS_UPDATE` | — | Lock/unlock physical doors |
| `events` | — | — | — | System-generated, read-only |
| `policies` | — | `UNIFI_POLICY_ACCESS_POLICIES_UPDATE` | — | Access policy assignment |
| `schedules` | — | — | — | Time-based access schedules, read-only |
| `system` | — | — | — | System info, read-only |
| `visitors` | `UNIFI_POLICY_ACCESS_VISITORS_CREATE` | — | `UNIFI_POLICY_ACCESS_VISITORS_DELETE` | Time-bounded visitor passes |

Read-only tools (list, get, status, activity summaries) are always available with no policy configuration required.

## Common Scenarios

### Zero config (default)

No configuration needed. All tools work — reads execute immediately, mutations require confirmation (preview-then-confirm). This is the safest default.

### Restrict to door control only

```bash
UNIFI_POLICY_ACCESS_CREATE=false
UNIFI_POLICY_ACCESS_UPDATE=false
UNIFI_POLICY_ACCESS_DELETE=false
UNIFI_POLICY_ACCESS_DOORS_UPDATE=true
```

### Lock down everything except visitor and credential management

```bash
UNIFI_POLICY_ACCESS_CREATE=false
UNIFI_POLICY_ACCESS_UPDATE=false
UNIFI_POLICY_ACCESS_DELETE=false
UNIFI_POLICY_ACCESS_VISITORS_CREATE=true
UNIFI_POLICY_ACCESS_VISITORS_DELETE=true
UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE=true
UNIFI_POLICY_ACCESS_CREDENTIALS_DELETE=true
```

### Full access management (doors, credentials, policies, visitors)

```bash
UNIFI_POLICY_ACCESS_DOORS_UPDATE=true
UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE=true
UNIFI_POLICY_ACCESS_CREDENTIALS_DELETE=true
UNIFI_POLICY_ACCESS_VISITORS_CREATE=true
UNIFI_POLICY_ACCESS_VISITORS_DELETE=true
UNIFI_POLICY_ACCESS_POLICIES_UPDATE=true
```

### Full bypass for automation

```bash
UNIFI_ACCESS_TOOL_PERMISSION_MODE=bypass
UNIFI_POLICY_ACCESS_CREATE=true
UNIFI_POLICY_ACCESS_UPDATE=true
UNIFI_POLICY_ACCESS_DELETE=true
```

### Claude Desktop example

```json
{
  "env": {
    "UNIFI_POLICY_ACCESS_DOORS_UPDATE": "true",
    "UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE": "true"
  }
}
```

## Confirmation Flow

When `UNIFI_ACCESS_TOOL_PERMISSION_MODE=confirm` (default), mutating tools follow a two-step pattern:

1. Call without `confirm` — returns a preview of the change, no mutation occurs
2. Call with `confirm=true` — executes the mutation

This applies even when a policy gate permits the action.

## Backwards Compatibility

The following deprecated variables are still accepted but will be removed in a future release:

| Deprecated | Equivalent |
|------------|-----------|
| `UNIFI_AUTO_CONFIRM=true` | `UNIFI_TOOL_PERMISSION_MODE=bypass` |
| `UNIFI_PERMISSIONS_<CAT>_<ACTION>=true` | `UNIFI_POLICY_ACCESS_<CAT>_<ACTION>=true` |

Deprecated variables are resolved before new-style variables and have lower priority if both are set.
