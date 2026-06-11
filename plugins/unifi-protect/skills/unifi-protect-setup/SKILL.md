---
name: unifi-protect-setup
description: Configure the UniFi Protect MCP server for Claude Code, Codex, or OpenClaw — set NVR host, credentials, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Protect MCP Server

Walk the user through configuring their UniFi Protect NVR connection. Ask one question at a time and wait for the answer before continuing.

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
bash <path-to-plugin>/scripts/check-prereqs.sh --target <claude|codex|openclaw> "unifi-protect"
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File <path-to-plugin>/scripts/check-prereqs.ps1 -Target <claude|codex|openclaw> -PluginName "unifi-protect"
```

If the script exits non-zero, stop and report the error. Do not proceed to credentials.

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" Example: `192.168.1.1`.

If another UniFi MCP server is already configured, ask whether Protect is on the same controller. For Claude, existing values may be in `.claude/settings.local.json`. For Codex, existing values may be visible through `codex mcp list` and `codex mcp get <server>`. For OpenClaw, existing values may be visible through `openclaw mcp list` and `openclaw mcp show <server>`.

## Step 2: Credentials

If the user already configured shared `UNIFI_*` credentials for another UniFi server, mention they can reuse those credentials. Only set `UNIFI_PROTECT_*` values when Protect credentials differ.

Ask for:
1. Username, using a local admin account, not a Ubiquiti SSO account
2. Password

Username and password are required.

> **AI-powered alarms need SuperAdmin.** The alarm-rule tools (`protect_alarm_list_rules` / `protect_alarm_get_rule`) surface AI-powered alarms from the UniFi-OS Alarm Manager only when the account is **SuperAdmin**; otherwise they return the classic automations view (with a `_meta` notice that AI alarms need SuperAdmin). A standard local admin runs every Protect tool fine. Mention SuperAdmin only if the user asks about AI alarms; don't require it for normal setup. On a combined UDM console, SuperAdmin also grants Network/UniFi-OS control — call that out so the user can decide.

### Optional API Key

After collecting username and password, explain that UniFi API key support is experimental and limited to read-only operations and a subset of tools. Ask whether to configure an API key too.

If yes, ask for the API key and include `UNIFI_PROTECT_API_KEY`. If no, skip it.

## Step 3: Permission Configuration

Ask whether to enable write permissions. By default, Protect mutations are disabled for camera settings, recording control, PTZ, and reboots.

Options:
- Read-only for now
- Enable camera management
- Enable all device management
- Custom categories

Collect any selected policy variables. Use the existing `UNIFI_POLICY_PROTECT_<CATEGORY>_<ACTION>=true` format.

## Step 4: Write Configuration

On macOS/Linux, run the target-aware setup script with only values the user provided or selected:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  UNIFI_PROTECT_PASSWORD=<password>
```

Add optional values and policy variables to the same command, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  UNIFI_PROTECT_PASSWORD=<password> \
  UNIFI_PROTECT_API_KEY=<api-key> \
  UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true
```

The script handles the client-specific write:
- Claude target: merges env vars into `.claude/settings.local.json`
- Codex target: replaces the `unifi-protect` MCP server via `codex mcp add --env ... -- uvx ...`
- OpenClaw target: replaces the `unifi-protect` MCP server via `openclaw mcp set ...`

## Step 5: Final Message

For Claude Code, tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code or run `/reload-plugins`, then confirm the plugin is enabled with `/plugin`."

For Codex, tell the user:

"Codex MCP server `unifi-protect` configured. Restart Codex so the updated MCP server is loaded."

For OpenClaw, tell the user:

"OpenClaw MCP server `unifi-protect` configured. Restart the OpenClaw Gateway so the updated MCP server is loaded."
