---
name: setup
description: Configure the UniFi Protect MCP server — set NVR host, credentials, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Protect MCP Server

Walk the user through configuring their UniFi Protect NVR connection. **Ask each question one at a time using AskUserQuestion. Wait for the answer before proceeding.**

## Step 0: Check Prerequisites

Before asking the user for any credentials, run the prereq check so the most common silent failures (missing `uvx`, malformed existing settings) are caught up front:

**macOS / Linux:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/check-prereqs.sh "unifi-protect"
```

**Windows:** PowerShell setups can skip this step — `uvx` availability is checked when the MCP server first launches. Just remind the user to install `uv` if it's missing.

If the script exits non-zero, **stop and report the error to the user**. Do not proceed to credentials. The script's output already explains what to fix.

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" (e.g., 192.168.1.1)

If the user already has a Network server configured (check for `UNIFI_NETWORK_HOST` or `UNIFI_HOST` in `.claude/settings.local.json`), ask: "Is Protect on the same controller as your Network server?" If yes, use the same host.

## Step 2: Credentials

If the user already has Network credentials configured with the shared `UNIFI_` prefix, mention they can reuse those. Only set `UNIFI_PROTECT_` prefixed variables if the credentials differ from the shared ones.

Ask for:
1. Username (local admin account — **not** a Ubiquiti SSO account)
2. Password

Username and password are **required**. These must be local admin credentials on the UniFi controller.

### Optional: API Key

After collecting credentials, mention:

"UniFi also supports API keys, but API key auth is **experimental** — it's limited to read-only operations and a subset of tools. Ubiquiti is still expanding API key support. Would you also like to configure an API key?"

If yes, ask for the API key string and include it as `UNIFI_PROTECT_API_KEY` in the configuration. If no, skip it.

## Step 4: Permission Configuration

Ask: "Do you want to enable any write permissions? By default, ALL mutations are disabled for Protect (camera settings, recording control, PTZ, reboots)."

Options:
- "Read-only for now" — safest, can view everything but change nothing
- "Enable camera management" — camera settings, recording toggle, PTZ, reboot
- "Enable all device management" — cameras + lights + chimes
- "Custom" — ask which categories to enable

## Step 5: Write Configuration

Use the appropriate script for the user's platform to write all collected values to `.claude/settings.local.json`. Check the platform from your environment info. On **Windows** use `set-env.ps1`, on **macOS/Linux** use `set-env.sh`:

**macOS / Linux:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set-env.sh \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  UNIFI_PROTECT_PASSWORD=<password>
```

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/set-env.ps1" UNIFI_PROTECT_HOST=<host> UNIFI_PROTECT_USERNAME=<username> UNIFI_PROTECT_PASSWORD=<password>
```

If the host and credentials are the same as existing shared `UNIFI_*` vars, use the shared prefix instead (same script, different keys).

If permissions were enabled, also pass those:
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set-env.sh \
  UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true
```

Permission variables by option:
- **Camera management:** `UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true`
- **All device management:** `UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true`, `UNIFI_POLICY_PROTECT_LIGHTS_UPDATE=true`, `UNIFI_POLICY_PROTECT_CHIMES_UPDATE=true`

## Step 6: Verify and Restart

Tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code (or run `/reload-plugins`) to connect the MCP server.

**After restart, run `/mcp` to verify.** You should see `unifi-protect` listed as connected, with a tool count next to it.

If it's missing or shows 0 tools, the server failed to start. Diagnose in this order:

1. `/plugin` — confirm the plugin shows **enabled** (not just installed). If only installed, enable it and re-run `/reload-plugins`.
2. `which uvx` — if it returns nothing, install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`), restart your shell, then restart Claude Code.
3. `claude --debug` (in a fresh shell) — surfaces MCP server startup errors. Look for `unifi-protect` in the output and report any error to the maintainer.
4. Verify the credentials by running the same `uvx unifi-protect-mcp` command manually with the same env vars to see if it can reach your controller.

Once `/mcp` shows the server connected, the UniFi Protect tools will be available."

Show a summary table of what was configured.
