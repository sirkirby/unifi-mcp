# Permission System

The UniFi MCP permission system gives you precise control over how tools behave — from fully interactive with confirmation prompts, to fully automated, to hard read-only enforcement — without hiding tools from agents.

## Core Concept

All tools are always visible and discoverable. Authorization is checked at **call time**, not at registration time. This means agents can always see what tools exist and get clear, actionable errors when a policy gate blocks an action.

There are two independent concepts:

| Concept | What it controls |
|---------|-----------------|
| **Permission Mode** | Whether mutations require a preview-then-confirm step |
| **Policy Gates** | Hard on/off switches that disable specific actions entirely |

### Site Manager: nothing to gate

The Site Manager server is read-only. Its nine domain tools only read, are annotated `readOnlyHint: true`, and need no permission mode, confirmation, preview token or policy gate; `UNIFI_POLICY_*` variables have no Site Manager actions to act on. What limits it instead is the account behind its API key, which can read every console on the account.

Its dispatch meta-tools carry conservative annotations, because a dispatcher's hint must hold for any tool it could run: `sitemanager_tool_index` and `sitemanager_batch_status` are read-only, while `sitemanager_execute`, `sitemanager_batch` and `sitemanager_load_tools` are not. A client that approves only read-only tools can still call the nine tools directly, which is why the default `lazy` mode lists all nine. See [Site Manager permissions](../apps/sitemanager/docs/permissions.md).

The rest of this page applies to the Network, Protect and Access servers and, where stated, the API server.

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

### Preview Tokens (opt-in)

In `confirm` mode the server does not check that a preview came first: a client can send `confirm=true` on its first call. Preview tokens close that gap. When they are enabled, every preview response carries a `preview_token`, and a call with `confirm=true` is refused unless it sends back a token issued for the same tool and the same arguments.

```json
{
  "success": true,
  "requires_confirmation": true,
  "preview": {"current": {"name": "IoT VLAN"}, "proposed": {"name": "IoT Devices"}},
  "preview_token": "kQ4m...",
  "preview_token_expires_in": 300,
  "message": "Will update name on network 'IoT VLAN'. Set confirm=true to execute. Send the preview_token from this response with confirm=true."
}
```

A token is single use and expires after `UNIFI_PREVIEW_TOKEN_TTL_SECONDS`. Any presented token is spent, including one refused for changed arguments, so a changed request needs a new preview. Tokens are held in process memory and do not survive a restart. A token is a server-side, single-use secret that is not bound to a client or session: on a shared HTTP server, any client that holds it can redeem it within its lifetime. Every mutating tool gains an optional `preview_token` argument while the mode is on; the committed tool manifests are generated with it off.

| Variable | Scope | Example |
|----------|-------|---------|
| `UNIFI_REQUIRE_PREVIEW_TOKEN` | Global (all servers) | `true` |
| `UNIFI_<SERVER>_REQUIRE_PREVIEW_TOKEN` | Per-server, wins over global | `UNIFI_NETWORK_REQUIRE_PREVIEW_TOKEN=true` |
| `UNIFI_PREVIEW_TOKEN_TTL_SECONDS` | All servers | `300` (default), clamped to 10 to 3600 |

The mode applies to tool calls on the Network, Protect and Access MCP servers, including calls made through `unifi_execute` and `unifi_batch`. The API server's action endpoint has its own confirm flow and does not check tokens. The setting is read at startup. An unrecognized value counts as `true`. `bypass` mode executes mutations without a preview, so it requires no token; the server logs a warning at startup when both are set.

What a token proves is narrow: the server produced a preview for exactly this request. It does not prove a human read it, because an agent can call the preview and then execute with its token. It guarantees that a preview always exists for a client to show, and that the executed request is the one that was previewed. Human approval still belongs to the MCP client.

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

The Claude Code plugins expose only the server-level gates
(`UNIFI_POLICY_<SERVER>_<ACTION>`) as plugin options, so per-category overrides
are not available there. Allow the action server-wide with confirmation mode
on, or keep it off. Codex, OpenClaw and directly launched servers accept every
level.

---

## Read-Only Mode

Read-only mode denies every action that is not a read, whatever the policy gates say. No `UNIFI_POLICY_*` variable re-enables an action while it is on. It is off by default.

It covers the Network, Protect and Access MCP servers and the API server (`POST /v1/actions/{tool}`). Every tool stays listed; calls to non-read tools return an error naming read-only mode. The API server refuses mutation previews (`confirm=false`) as well as confirmed calls with HTTP 403 and writes a `denied` audit row; read actions are unaffected.

**Error example:**
```
Update is disabled for networks: the network server is in read-only mode, which no policy gate overrides.
```

| Variable | Scope | Values |
|----------|-------|--------|
| `UNIFI_READ_ONLY` | Global (all servers) | `true`/`false` |
| `UNIFI_<SERVER>_READ_ONLY` | Per-server (`NETWORK`, `PROTECT`, `ACCESS`); overrides global | `true`/`false` |

The API server resolves the per-server variable from the action's product, so `UNIFI_PROTECT_READ_ONLY=true` also blocks `protect_*` mutations on the API.

**Accepted values:** `true`, `1`, `yes`, `on` (case-insensitive) turn it on; `false`, `0`, `no`, `off` turn it off; unset or empty defers to the next level. Any other value turns read-only mode on and logs a warning, so a misspelt attempt to enable it never leaves mutations allowed.

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
UNIFI_READ_ONLY=true
```
Unlike setting `UNIFI_POLICY_CREATE/UPDATE/DELETE=false`, no more specific policy gate can re-enable an action, and the API server is covered too.

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
| Restart after changing the launcher environment? | Yes | Yes — the new process must inherit it |

Call-time enforcement means a denied tool stays discoverable and receives a
fresh policy check on every invocation. It does not let a running process see
environment changes made later in its parent shell or container configuration.

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
The relevant policy gate is set to `false`. The error message includes the exact
variable to set. Enable it, restart the server so it inherits the updated
environment, and re-call the tool.

### Mutation executed without asking for confirmation
`UNIFI_TOOL_PERMISSION_MODE` (or the server-specific variant) is set to `bypass`, or the legacy `UNIFI_AUTO_CONFIRM=true` is present. Remove or set to `confirm` to re-enable the preview step.

### Tool not appearing in tool index at all
Policy gates never remove tools from registration or discovery. Index contents
depend on the registration mode: `lazy` uses the generated manifest for the
full catalog, `eager` indexes the registered catalog, and `meta_only` initially
indexes only meta-tools. Executing a known domain tool in `meta_only` lazily
registers its module, so later index results can include those loaded tools. If
a tool is missing in `lazy` mode, the relevant manifest may be stale. From the
repository root, run `make -C apps/network manifest`,
`make -C apps/protect manifest`, or `make -C apps/access manifest` for the
affected server.

### A `UNIFI_POLICY_` variable not taking effect
At startup each server compares every `UNIFI_POLICY_*` variable with the gates its tools
register and logs a warning naming each variable no gate matches, with the closest valid
names. Check stderr for `[policy] Unrecognized env var`. The `<CATEGORY>` segment is the
server's config key from its `permissions.md` (`CAMERAS`, `CLIENT_GROUPS`), not the
`permission_category` shorthand in `tools_manifest.json` (`camera`, `client_group`).

### Legacy variables not taking effect
Ensure the variable name matches the old format exactly (`UNIFI_PERMISSIONS_<CAT>_<ACTION>`). Check stderr logs for the deprecation warning confirming the variable was detected. If the new `UNIFI_POLICY_` variable is also set, the new one takes precedence.

---

## Related Documentation

- [Configuration Guide](../apps/network/docs/configuration.md)
- [Security Policy](../SECURITY.md)
- [Tool Index API](tool-index.md)
