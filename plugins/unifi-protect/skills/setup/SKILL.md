---
name: setup
description: Configure the UniFi Protect MCP server for Claude Code or Codex — set NVR host, credentials, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Protect MCP Server

Walk the user through configuring their UniFi Protect NVR connection. Ask one question at a time and wait for the answer before continuing.

## Interaction Rules

Use the client target that matches the current agent runtime:
- Claude Code: `claude`
- Codex: `codex`

If the runtime is unclear, ask which client to configure. For questions, use the platform's blocking question tool when available (`AskUserQuestion` in Claude Code, `request_user_input` in Codex). If no blocking question tool is available, ask in chat with numbered options and wait for the user's reply.

On macOS and Linux, resolve setup scripts relative to this skill file:
- `../../scripts/check-prereqs.sh`
- `../../scripts/set-env.sh`

When the host exposes a plugin-root variable such as `CLAUDE_PLUGIN_ROOT`, using `$CLAUDE_PLUGIN_ROOT/scripts/...` is also valid. Do not assume the current shell directory is the plugin root.

On Windows with Claude Code, use `../../scripts/set-env.ps1` for the final Claude settings write. On Windows with Codex, call `codex mcp add` directly with the same env variables if Bash is unavailable.

## Step 0: Check Prerequisites

Before asking for credentials, run:

```bash
bash <path-to-plugin>/scripts/check-prereqs.sh --target <claude|codex> "unifi-protect"
```

If the script exits non-zero, stop and report the error. Do not proceed to credentials.

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" Example: `192.168.1.1`.

If another UniFi MCP server is already configured, ask whether Protect is on the same controller. For Claude, existing values may be in `.claude/settings.local.json`. For Codex, existing values may be visible through `codex mcp list` and `codex mcp get <server>`.

## Step 2: Credentials

If the user already configured shared `UNIFI_*` credentials for another UniFi server, mention they can reuse those credentials. Only set `UNIFI_PROTECT_*` values when Protect credentials differ.

Ask for:
1. Username, using a local admin account, not a Ubiquiti SSO account
2. Password

Username and password are required.

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
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex> \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  UNIFI_PROTECT_PASSWORD=<password>
```

Add optional values and policy variables to the same command, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex> \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  UNIFI_PROTECT_PASSWORD=<password> \
  UNIFI_PROTECT_API_KEY=<api-key> \
  UNIFI_POLICY_PROTECT_CAMERAS_UPDATE=true
```

The script handles the client-specific write:
- Claude target: merges env vars into `.claude/settings.local.json`
- Codex target: replaces the `unifi-protect` MCP server via `codex mcp add --env ... -- uvx ...`

## Step 5: Final Message

For Claude Code, tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code or run `/reload-plugins`, then confirm the plugin is enabled with `/plugin`."

For Codex, tell the user:

"Codex MCP server `unifi-protect` configured. Restart Codex so the updated MCP server is loaded."
