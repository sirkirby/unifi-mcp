---
name: setup
description: Configure the UniFi Access MCP server — set controller host, credentials, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Access MCP Server

Walk the user through configuring their UniFi Access controller connection. **Ask each question one at a time using AskUserQuestion. Wait for the answer before proceeding.**

## Step 0: Check Prerequisites

Before asking the user for any credentials, run the prereq check so the most common silent failures (missing `uvx`, malformed existing settings) are caught up front:

**macOS / Linux:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/check-prereqs.sh "unifi-access"
```

**Windows:** PowerShell setups can skip this step — `uvx` availability is checked when the MCP server first launches. Just remind the user to install `uv` if it's missing.

If the script exits non-zero, **stop and report the error to the user**. Do not proceed to credentials. The script's output already explains what to fix.

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" (e.g., 192.168.1.1)

If the user already has Network or Protect configured (check `.claude/settings.local.json` for existing `UNIFI_*` env vars), ask: "Is Access on the same controller?" If yes, use the same host.

## Step 2: Authentication

Access uses dual authentication — explain this to the user:

"UniFi Access has two auth paths:
- **API key** (port 12445) — for read-only operations (listing doors, events, devices)
- **Username + password** (port 443) — required for mutations (lock/unlock, credentials, visitors)

You can configure one or both."

Ask: "Which auth paths do you want to set up?"

Options:
- "API key only" — read-only access to Access data
- "Username and password only" — full access including mutations
- "Both" — recommended for full flexibility

## Step 3: Collect Credentials

Based on their choice, ask for API key and/or username+password (one question at a time).

## Step 4: Permission Configuration

Ask: "Do you want to enable any write permissions? By default, ALL mutations are disabled for Access (door lock/unlock, credentials, visitors)."

Options:
- "Read-only for now" — can view doors, events, users but not control anything
- "Enable door control" — lock/unlock doors
- "Enable credential management" — create/revoke NFC, PIN, mobile credentials
- "Enable visitor management" — create/delete visitor passes
- "Enable all" — door control + credentials + visitors + device reboot
- "Custom" — ask which categories to enable

## Step 5: Write Configuration

Use the appropriate script for the user's platform to write all collected values to `.claude/settings.local.json`. Check the platform from your environment info. On **Windows** use `set-env.ps1`, on **macOS/Linux** use `set-env.sh`:

**macOS / Linux:**
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set-env.sh \
  UNIFI_ACCESS_HOST=<host> \
  UNIFI_ACCESS_API_KEY=<api-key> \
  UNIFI_ACCESS_USERNAME=<username> \
  UNIFI_ACCESS_PASSWORD=<password>
```

**Windows:**
```powershell
powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/set-env.ps1" UNIFI_ACCESS_HOST=<host> UNIFI_ACCESS_API_KEY=<api-key> UNIFI_ACCESS_USERNAME=<username> UNIFI_ACCESS_PASSWORD=<password>
```

If the host and credentials are the same as existing shared `UNIFI_*` vars, use the shared prefix instead to avoid duplication.

If permissions were enabled, also pass those:
```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/set-env.sh \
  UNIFI_POLICY_ACCESS_DOORS_UPDATE=true \
  UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE=true \
  UNIFI_POLICY_ACCESS_VISITORS_CREATE=true
```

Permission variables by option:
- **Door control:** `UNIFI_POLICY_ACCESS_DOORS_UPDATE=true`
- **Credential management:** `UNIFI_POLICY_ACCESS_CREDENTIALS_CREATE=true`, `UNIFI_POLICY_ACCESS_CREDENTIALS_DELETE=true`
- **Visitor management:** `UNIFI_POLICY_ACCESS_VISITORS_CREATE=true`, `UNIFI_POLICY_ACCESS_VISITORS_DELETE=true`
- **Enable all:** all of the above + `UNIFI_POLICY_ACCESS_DEVICES_UPDATE=true`, `UNIFI_POLICY_ACCESS_POLICIES_UPDATE=true`

## Step 6: Verify and Restart

Tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code (or run `/reload-plugins`) to connect the MCP server.

**After restart, run `/mcp` to verify.** You should see `unifi-access` listed as connected, with a tool count next to it.

If it's missing or shows 0 tools, the server failed to start. Diagnose in this order:

1. `/plugin` — confirm the plugin shows **enabled** (not just installed). If only installed, enable it and re-run `/reload-plugins`.
2. `which uvx` — if it returns nothing, install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`), restart your shell, then restart Claude Code.
3. `claude --debug` (in a fresh shell) — surfaces MCP server startup errors. Look for `unifi-access` in the output and report any error to the maintainer.
4. Verify the credentials by running the same `uvx unifi-access-mcp` command manually with the same env vars to see if it can reach your controller.

Once `/mcp` shows the server connected, the UniFi Access tools will be available."

Show a summary table of what was configured, noting which auth paths are active and what permissions are enabled.
