---
name: unifi-network-setup
description: Configure the UniFi Network MCP server for a supported MCP client — set controller host, credentials, and permissions
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

This skill may come from a complete UniFi plugin or a standalone `npx skills`
install. Before using a helper script, verify that the plugin's `scripts/`
directory exists. If it does not, do not guess a relative path: follow the
[canonical agent installation guide](https://github.com/sirkirby/unifi-mcp/blob/main/docs/agent-install.md)
for the client's native MCP registration path. That guide covers OpenCode,
Antigravity, Devin Desktop, Cursor, and other manual clients. A standalone
skill install does not install or register the MCP server by itself.

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

Ask which authentication path the user needs:
- API key only for supported device, client, network, and WLAN inventory plus
  API-key-only Integration API lookups
- Local username and password for legacy and session-backed tool families
- Both for the widest tool coverage and independently usable API-key reads if
  the session fails

Ask for the local username when session authentication is selected. Never ask the
user to send a password or API key in chat, and never place a raw secret in a tool
call or command argument. Ask for exactly one indirect provider per secret:
`UNIFI_NETWORK_PASSWORD_FILE=<absolute-path>` or
`UNIFI_NETWORK_PASSWORD_COMMAND=<absolute argv>`, and
`UNIFI_NETWORK_API_KEY_FILE=<absolute-path>` or
`UNIFI_NETWORK_API_KEY_COMMAND=<absolute argv>`. A command provider can call a
Keychain, `pass`, or 1Password helper; it is not run through a shell and must not
prompt. If no indirect provider already exists, explain how to create one outside
the chat transcript or use a client-native masked secret UI, then wait.

Set exactly one spelling per secret; the server refuses to start if two are set.
On the Claude target `set-env.sh` only adds keys. Before changing or deselecting
an authentication path, remove all of that path's existing product-scoped
spellings: `UNIFI_NETWORK_PASSWORD`, `UNIFI_NETWORK_PASSWORD_FILE`, and
`UNIFI_NETWORK_PASSWORD_COMMAND` for session authentication; and
`UNIFI_NETWORK_API_KEY`, `UNIFI_NETWORK_API_KEY_FILE`, and
`UNIFI_NETWORK_API_KEY_COMMAND` for API-key authentication. Then add only the
provider the user selected. The Codex and OpenClaw targets replace the whole
server entry.

### Optional API Key

Explain that UniFi API-key support is limited to inventory reads and explicit
Integration API tools; legacy mutations and full details may still require a local
username and password provider. If selected, configure only an API-key file or
command provider, never the raw key.

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

Before writing policy values, inspect the selected client's existing
`unifi-network` MCP environment. Remove every existing category-specific
`UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>` entry, because those entries take
precedence over server-level defaults. Do not remove unrelated variables. Set
`UNIFI_NETWORK_TOOL_PERMISSION_MODE=confirm`, then add back only the
category/action overrides the user selected.

For read-only setup, explicitly configure:

```text
UNIFI_POLICY_NETWORK_CREATE=false
UNIFI_POLICY_NETWORK_UPDATE=false
UNIFI_POLICY_NETWORK_DELETE=false
```

For requested writes, keep those server-level defaults and add only the selected
category/action overrides using the existing
`UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>=true` format.

## Step 5: Write Configuration

On macOS/Linux, run the target-aware setup script with only values the user provided or selected:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_NETWORK_HOST=<host> \
  UNIFI_NETWORK_USERNAME=<username> \
  'UNIFI_NETWORK_PASSWORD_FILE=<absolute-path>' \
  UNIFI_NETWORK_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_NETWORK_CREATE=false \
  UNIFI_POLICY_NETWORK_UPDATE=false \
  UNIFI_POLICY_NETWORK_DELETE=false
```

Add optional values and policy variables to the same command, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_NETWORK_HOST=<host> \
  UNIFI_NETWORK_USERNAME=<username> \
  'UNIFI_NETWORK_PASSWORD_COMMAND=<absolute-argv>' \
  'UNIFI_NETWORK_API_KEY_FILE=<absolute-path>' \
  UNIFI_NETWORK_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_NETWORK_CREATE=false \
  UNIFI_POLICY_NETWORK_UPDATE=false \
  UNIFI_POLICY_NETWORK_DELETE=false \
  UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE=true
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
