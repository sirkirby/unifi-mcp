---
name: unifi-access-setup
description: Configure the UniFi Access MCP server for Claude Code, Codex, or OpenClaw — set controller host, credentials, API key, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Access MCP Server

Walk the user through configuring their UniFi Access controller connection. Ask one question at a time and wait for the answer before continuing.

## Interaction Rules

Use the client target that matches the current agent runtime:
- Claude Code: `claude`
- Codex: `codex`
- OpenClaw: `openclaw`

If the runtime is unclear, ask which client to configure. For questions, use the platform's blocking question tool when available (`AskUserQuestion` in Claude Code, `request_user_input` in Codex). If no blocking question tool is available, ask in chat with numbered options and wait for the user's reply.

On macOS and Linux, resolve setup scripts relative to this skill file:
- `../../scripts/check-prereqs.sh`
- `../../scripts/set-env.sh`

When the host exposes a plugin-root variable such as `CLAUDE_PLUGIN_ROOT`, using `$CLAUDE_PLUGIN_ROOT/scripts/...` is also valid. Do not assume the current shell directory is the plugin root.

On Windows with Claude Code, use `../../scripts/set-env.ps1` for the final Claude settings write. On Windows with Codex, prefer the native PowerShell prereq script and call `codex mcp add` directly with the same env variables if Bash is unavailable. On Windows with OpenClaw, call `openclaw mcp set` directly with a JSON object containing `command`, `args`, and `env` if Bash is unavailable. Do not run the Bash prereq script on Windows unless the user explicitly asks to use a Bash environment.

## Step 0: Check Prerequisites

Before asking for credentials, run the prereq checker for the current OS.

On macOS/Linux:

```bash
bash <path-to-plugin>/scripts/check-prereqs.sh --target <claude|codex|openclaw> "unifi-access"
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File <path-to-plugin>/scripts/check-prereqs.ps1 -Target <claude|codex|openclaw> -PluginName "unifi-access"
```

If the script exits non-zero, stop and report the error. Do not proceed to credentials.

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" Example: `192.168.1.1`.

If another UniFi MCP server is already configured, ask whether Access is on the same controller. For Claude, existing values may be in `.claude/settings.local.json`. For Codex, existing values may be visible through `codex mcp list` and `codex mcp get <server>`. For OpenClaw, existing values may be visible through `openclaw mcp list` and `openclaw mcp show <server>`.

## Step 2: Authentication

Access supports two auth paths:
- API key for read-oriented Access API calls
- Local proxy session with username and password for mutations and broader tool coverage

Ask whether the user wants API key only, username/password only, or both. Recommend both when they want full Access management.

For username/password, ask for:
1. Username, using a local admin account, not a Ubiquiti SSO account
2. Password

For API key, ask for the key and include `UNIFI_ACCESS_API_KEY`.

At least one auth path is required.

## Step 3: Optional Settings

Ask whether to use defaults or customize:
- Defaults: controller port `443`, Access API port `12445`, SSL verification `false`, lazy tool loading
- Customize: ask for controller port, API port, SSL verification, and tool registration mode

## Step 4: Permission Configuration

Ask whether to enable write permissions. By default, Access mutations are disabled for credentials, visitors, policies, and door controls.

Options:
- Read-only for now
- Enable visitor and credential management
- Enable door operations
- Enable all Access write permissions except delete operations
- Custom categories

Collect any selected policy variables. Use the existing `UNIFI_POLICY_ACCESS_<CATEGORY>_<ACTION>=true` format.

## Step 5: Write Configuration

On macOS/Linux, run the target-aware setup script with only values the user provided or selected:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_ACCESS_HOST=<host> \
  UNIFI_ACCESS_API_KEY=<api-key> \
  UNIFI_ACCESS_USERNAME=<username> \
  UNIFI_ACCESS_PASSWORD=<password>
```

Add optional values and policy variables to the same command, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_ACCESS_HOST=<host> \
  UNIFI_ACCESS_API_KEY=<api-key> \
  UNIFI_ACCESS_USERNAME=<username> \
  UNIFI_ACCESS_PASSWORD=<password> \
  UNIFI_ACCESS_API_PORT=12445 \
  UNIFI_POLICY_ACCESS_VISITORS_CREATE=true
```

The script handles the client-specific write:
- Claude target: merges env vars into `.claude/settings.local.json`
- Codex target: replaces the `unifi-access` MCP server via `codex mcp add --env ... -- uvx ...`
- OpenClaw target: replaces the `unifi-access` MCP server via `openclaw mcp set ...`

## Step 6: Final Message

For Claude Code, tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code or run `/reload-plugins`, then confirm the plugin is enabled with `/plugin`."

For Codex, tell the user:

"Codex MCP server `unifi-access` configured. Restart Codex so the updated MCP server is loaded."

For OpenClaw, tell the user:

"OpenClaw MCP server `unifi-access` configured. Restart the OpenClaw Gateway so the updated MCP server is loaded."
