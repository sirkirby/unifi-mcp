# Permission System

The UniFi MCP permission system gives you precise control over how tools behave — from fully interactive with confirmation prompts, to fully automated, to hard read-only enforcement — without hiding tools from agents.

## Core Concept

All tools are always visible and discoverable. Authorization is checked at **call time**, not at registration time. This means agents can always see what tools exist and get clear, actionable errors when a policy gate blocks an action.

There are two independent concepts:

| Concept | What it controls |
|---------|-----------------|
| **Permission Mode** | Whether mutations require a preview-then-confirm step |
| **Policy Gates** | Hard on/off switches that disable specific actions entirely |

---

## Permission Mode

Permission mode controls how mutating tools (create, update, delete) behave when called. Read-only tools are unaffected by this setting.

| Mode | Behavior |
|------|----------|
| `confirm` (default) | Mutations return a preview first; execution requires `confirm=true` |
| `bypass` | Mutations execute immediately without a confirmation step |

### How Confirmation Works

When mode is `confirm` and a mutating tool is called without `confirm=true`:

```json
{
  "success": true,
  "requires_confirmation": true,
  "action": "update",
  "resource_type": "network",
  "resource_name": "IoT VLAN",
  "preview": {
    "current": {"name": "IoT VLAN"},
    "proposed": {"name": "IoT Devices"}
  },
  "message": "Will update network 'IoT VLAN'. Set confirm=true to execute."
}
```

The agent reviews the preview and re-calls with `confirm=true` to apply the change.

### Permission Mode Environment Variables

Resolution order: most specific wins.

| Variable | Scope | Example |
|----------|-------|---------|
| `UNIFI_TOOL_PERMISSION_MODE` | Global (all servers) | `confirm` or `bypass` |
| `UNIFI_<SERVER>_TOOL_PERMISSION_MODE` | Per-server | `UNIFI_NETWORK_TOOL_PERMISSION_MODE=bypass` |

---

## Policy Gates

Policy gates are hard boundaries that disable specific actions regardless of permission mode. A denied tool is still visible in the tool index — it returns a clear error explaining exactly which variable to set to re-enable it.

**Error example:**
```
Update is disabled by policy for networks. Set UNIFI_POLICY_NETWORK_NETWORKS_UPDATE=true to enable.
```

### Actions

| Action | Covers |
|--------|--------|
| `CREATE` | Adding new resources |
| `UPDATE` | Modifying existing resources |
| `DELETE` | Removing resources |

### Policy Gate Environment Variables

Three-level hierarchy — most specific wins. If no gate is set for an action, it is allowed.

| Variable Pattern | Scope | Example |
|-----------------|-------|---------|
| `UNIFI_POLICY_<ACTION>` | Global — all servers, all categories | `UNIFI_POLICY_DELETE=false` |
| `UNIFI_POLICY_<SERVER>_<ACTION>` | Per-server — all categories on that server | `UNIFI_POLICY_NETWORK_UPDATE=false` |
| `UNIFI_POLICY_<SERVER>_<CATEGORY>_<ACTION>` | Per-server, per-category | `UNIFI_POLICY_NETWORK_NETWORKS_UPDATE=true` |

**Accepted values:** `true`, `1`, `yes`, `on` (case-insensitive) to allow; `false`, `0`, `no`, `off` to deny.

### Example: selectively re-enabling within a broad deny

```bash
# Deny all updates globally
UNIFI_POLICY_UPDATE=false

# But allow firewall policy updates on the network server
UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true
```

The most specific variable wins, so the category-level override takes effect.

---

## Practical Scenarios

### Zero config (default)
All tools work. Mutations require a confirmation step before executing. Safest option for interactive use with an LLM.

```bash
# No variables needed — this is the default
```

### Power user: skip confirmation prompts
```bash
UNIFI_TOOL_PERMISSION_MODE=bypass
```

### Enterprise read-only: block all mutations
```bash
UNIFI_POLICY_CREATE=false
UNIFI_POLICY_UPDATE=false
UNIFI_POLICY_DELETE=false
```

### Lock down deletes only
```bash
UNIFI_POLICY_DELETE=false
```

### Multi-server: different modes per server
```bash
# Network server: no confirmation prompts
UNIFI_NETWORK_TOOL_PERMISSION_MODE=bypass

# Protect server: keep human-in-the-loop (default confirm)
# (no variable needed — confirm is the default)
```

### Workflow automation (n8n, Make, Zapier)
```bash
UNIFI_TOOL_PERMISSION_MODE=bypass
```

Or in a Claude Desktop / MCP client config:
```json
{
  "mcpServers": {
    "unifi-network": {
      "command": "uv",
      "args": ["run", "unifi-network-mcp"],
      "env": {
        "UNIFI_HOST": "192.168.1.1",
        "UNIFI_USERNAME": "admin",
        "UNIFI_PASSWORD": "your-password",
        "UNIFI_TOOL_PERMISSION_MODE": "bypass"
      }
    }
  }
}
```

---

## Key Behavioral Difference from the Old System

| | Old system | New system |
|---|------------|------------|
| Denied tools visible to agents? | No — hidden at registration | Yes — always visible |
| Where is access checked? | At server startup (registration) | At call time |
| Agent feedback on denied action | Tool doesn't exist | Clear error with fix instructions |
| Requires server restart to change? | Yes | No |

---

## Backwards Compatibility

Legacy environment variables are honored with a deprecation warning logged to stderr.

| Legacy variable | Maps to | Deprecation guidance |
|----------------|---------|---------------------|
| `UNIFI_AUTO_CONFIRM=true` | `UNIFI_TOOL_PERMISSION_MODE=bypass` | Use `UNIFI_TOOL_PERMISSION_MODE=bypass` |
| `UNIFI_PERMISSIONS_<CAT>_<ACTION>=true/false` | `UNIFI_POLICY_<SERVER>_<CAT>_<ACTION>=true/false` | Use `UNIFI_POLICY_` prefix pattern |

Example migration:
```bash
# Old
UNIFI_AUTO_CONFIRM=true
UNIFI_PERMISSIONS_NETWORKS_CREATE=false

# New
UNIFI_TOOL_PERMISSION_MODE=bypass
UNIFI_POLICY_NETWORK_NETWORKS_CREATE=false
```

---

## Confirmation System Details

### Per-call override
Pass `confirm=true` in any mutating tool call to execute immediately, regardless of the global permission mode.

### Three levels of confirmation control

| Level | How | When to use |
|-------|-----|-------------|
| Per-call | `confirm=true` argument | LLM explicitly confirms a single operation |
| Per-session | System prompt instructs the agent | User's standing instruction for the session |
| Per-environment | `UNIFI_TOOL_PERMISSION_MODE=bypass` | Automation, no human in the loop |

---

## Troubleshooting

### "Action is disabled by policy" error
The relevant policy gate is set to `false`. The error message includes the exact variable to set. Enable it and re-call — no server restart required.

### Mutation executed without asking for confirmation
`UNIFI_TOOL_PERMISSION_MODE` (or the server-specific variant) is set to `bypass`, or the legacy `UNIFI_AUTO_CONFIRM=true` is present. Remove or set to `confirm` to re-enable the preview step.

### Tool not appearing in tool index at all
Policy gates never remove tools from registration or discovery. Index contents
depend on the registration mode: `lazy` uses the generated manifest for the
full catalog, `eager` indexes the registered catalog, and `meta_only` initially
indexes only meta-tools. Executing a known domain tool in `meta_only` lazily
registers its module, so later index results can include those loaded tools. If
a tool is missing in `lazy` mode, the manifest may be stale; run
`make network-manifest` to regenerate it.

### Legacy variables not taking effect
Ensure the variable name matches the old format exactly (`UNIFI_PERMISSIONS_<CAT>_<ACTION>`). Check stderr logs for the deprecation warning confirming the variable was detected. If the new `UNIFI_POLICY_` variable is also set, the new one takes precedence.

---

## Related Documentation

- [Configuration Guide](configuration.md)
- [Security Best Practices](security.md)
- [Tool Index API](tool-index.md)
