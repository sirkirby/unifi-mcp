---
name: setup
description: Configure the UniFi Network MCP server — set controller host, credentials, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Network MCP Server

Walk the user through configuring their UniFi Network controller connection. **Ask each question one at a time using AskUserQuestion. Wait for the answer before proceeding.**

## Step 0: Check Prerequisites

Before asking the user for any credentials, run the prereq check so the most common silent failures (missing `uvx`, malformed existing settings) are caught up front:

**macOS / Linux:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/check-prereqs.sh "unifi-network"
```

**Windows:** PowerShell setups can skip this step — `uvx` availability is checked when the MCP server first launches. Just remind the user to install `uv` if it's missing.

If the script exits non-zero, **stop and report the error to the user**. Do not proceed to credentials. The script's output already explains what to fix (install `uv`, repair `.claude/settings.local.json`, etc.).

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" (e.g., 192.168.1.1)

## Step 2: Credentials

Ask for:
1. Username (local admin account — **not** a Ubiquiti SSO account)
2. Password

Username and password are **required**. These must be local admin credentials on the UniFi controller.

### Optional: API Key

After collecting credentials, mention:

"UniFi also supports API keys, but API key auth is **experimental** — it's limited to read-only operations and a subset of tools. Ubiquiti is still expanding API key support. Would you also like to configure an API key?"

If yes, ask for the API key string and include it as `UNIFI_NETWORK_API_KEY` in the configuration. If no, skip it.

## Step 4: Optional Settings

Ask: "Any additional settings to configure?"

Options:
- "Use defaults" — port 443, site 'default', SSL verification off, lazy tool loading
- "Customize" — ask about each: port, site name, SSL verification, tool registration mode

## Step 5: Permission Configuration

Ask: "Do you want to enable any write permissions? By default, the server is read-only for high-risk categories."

Options:
- "Read-only for now" — skip, can be configured later
- "Enable common write permissions" — enable firewall, port forwards, QoS, traffic routes, VPN clients
- "Enable all write permissions" — enable everything except delete operations
- "Custom" — ask which categories to enable

## Step 6: Write Configuration

Use the appropriate script for the user's platform to write all collected values to `.claude/settings.local.json`. The script handles creating the file, merging into existing env vars, and masking sensitive values in output.

Check the platform from your environment info. On **Windows** use `set-env.ps1`, on **macOS/Linux** use `set-env.sh`:

**macOS / Linux:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set-env.sh \
  UNIFI_NETWORK_HOST=<host> \
  UNIFI_NETWORK_USERNAME=<username> \
  UNIFI_NETWORK_PASSWORD=<password>
```

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/set-env.ps1" UNIFI_NETWORK_HOST=<host> UNIFI_NETWORK_USERNAME=<username> UNIFI_NETWORK_PASSWORD=<password>
```

Only pass variables the user provided values for. Use the `UNIFI_NETWORK_` prefix so it doesn't conflict with other server plugins.

If permissions were enabled, also pass those (same script, separate call):
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set-env.sh \
  UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE=true \
  UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true \
  UNIFI_POLICY_NETWORK_PORT_FORWARDS_CREATE=true \
  UNIFI_POLICY_NETWORK_PORT_FORWARDS_UPDATE=true
```

Common permission variables for "enable all write":
- `UNIFI_POLICY_NETWORK_NETWORKS_CREATE=true`, `UNIFI_POLICY_NETWORK_NETWORKS_UPDATE=true`
- `UNIFI_POLICY_NETWORK_WLANS_CREATE=true`, `UNIFI_POLICY_NETWORK_WLANS_UPDATE=true`
- `UNIFI_POLICY_NETWORK_DEVICES_UPDATE=true`
- `UNIFI_POLICY_NETWORK_CLIENTS_UPDATE=true`
- `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_CREATE=true`, `UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true`
- `UNIFI_POLICY_NETWORK_PORT_FORWARDS_CREATE=true`, `UNIFI_POLICY_NETWORK_PORT_FORWARDS_UPDATE=true`
- `UNIFI_POLICY_NETWORK_TRAFFIC_ROUTES_UPDATE=true`
- `UNIFI_POLICY_NETWORK_QOS_RULES_CREATE=true`, `UNIFI_POLICY_NETWORK_QOS_RULES_UPDATE=true`
- `UNIFI_POLICY_NETWORK_VPN_CLIENTS_UPDATE=true`
- `UNIFI_POLICY_NETWORK_ROUTES_CREATE=true`, `UNIFI_POLICY_NETWORK_ROUTES_UPDATE=true`

## Step 7: Verify and Restart

Tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code (or run `/reload-plugins`) to connect the MCP server.

**After restart, run `/mcp` to verify.** You should see `unifi-network` listed as connected, with a tool count next to it.

If it's missing or shows 0 tools, the server failed to start. Diagnose in this order:

1. `/plugin` — confirm the plugin shows **enabled** (not just installed). If only installed, enable it and re-run `/reload-plugins`.
2. `which uvx` — if it returns nothing, install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`), restart your shell, then restart Claude Code.
3. `claude --debug` (in a fresh shell) — surfaces MCP server startup errors. Look for `unifi-network` in the output and report any error to the maintainer.
4. Verify the credentials by running the same `uvx unifi-network-mcp` command manually with the same env vars to see if it can reach your controller.

Once `/mcp` shows the server connected, the UniFi tools (`unifi_execute`, `unifi_tool_index`, etc.) will be available."

Show a summary table of what was configured.
