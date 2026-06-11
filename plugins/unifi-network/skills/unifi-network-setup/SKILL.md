---
name: unifi-network-setup
description: Configure the UniFi Network MCP server for Claude Code, Codex, or OpenClaw — set controller host, credentials, and permissions
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi Network MCP Server

Walk the user through configuring their UniFi Network controller connection. Ask one question at a time and wait for the answer before continuing.

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
bash <path-to-plugin>/scripts/check-prereqs.sh --target <claude|codex|openclaw> "unifi-network"
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File <path-to-plugin>/scripts/check-prereqs.ps1 -Target <claude|codex|openclaw> -PluginName "unifi-network"
```

If the script exits non-zero, stop and report the error. Do not proceed to credentials.

## Step 1: Controller Host

Ask: "What is your UniFi controller's IP address or hostname?" Example: `192.168.1.1`.

## Step 2: Credentials

Ask for:
1. Username, using a local admin account, not a Ubiquiti SSO account
2. Password

Username and password are required.

### Optional API Key

After collecting username and password, explain that UniFi API key support is experimental and limited to read-only operations and a subset of tools. Ask whether to configure an API key too.

If yes, ask for the API key and include `UNIFI_NETWORK_API_KEY`. If no, skip it.

## Step 3: Optional Settings

Ask whether to use defaults or customize:
- Defaults: port `443`, site `default`, SSL verification `false`, lazy tool loading
- Customize: ask for port, site, SSL verification, and tool registration mode

## Step 4: Permission Configuration

Ask whether to enable write permissions:
- Read-only for now
- Enable common write permissions: firewall, port forwards, QoS, traffic routes, VPN clients
- Enable all write permissions except delete operations
- Custom categories

Collect any selected policy variables. Use the existing `UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>=true` format.

## Step 5: Write Configuration

On macOS/Linux, run the target-aware setup script with only values the user provided or selected:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_NETWORK_HOST=<host> \
  UNIFI_NETWORK_USERNAME=<username> \
  UNIFI_NETWORK_PASSWORD=<password>
```

Add optional values and policy variables to the same command, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_NETWORK_HOST=<host> \
  UNIFI_NETWORK_USERNAME=<username> \
  UNIFI_NETWORK_PASSWORD=<password> \
  UNIFI_NETWORK_API_KEY=<api-key> \
  UNIFI_POLICY_NETWORK_FIREWALL_UPDATE=true
```

The script handles the client-specific write:
- Claude target: merges env vars into `.claude/settings.local.json`
- Codex target: replaces the `unifi-network` MCP server via `codex mcp add --env ... -- uvx ...`
- OpenClaw target: replaces the `unifi-network` MCP server via `openclaw mcp set ...`

## Step 6: Final Message

For Claude Code, tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code or run `/reload-plugins`, then confirm the plugin is enabled with `/plugin`."

For Codex, tell the user:

"Codex MCP server `unifi-network` configured. Restart Codex so the updated MCP server is loaded."

For OpenClaw, tell the user:

"OpenClaw MCP server `unifi-network` configured. Restart the OpenClaw Gateway so the updated MCP server is loaded."
