---
name: unifi-protect-setup
description: Configure the UniFi Protect MCP server for a supported MCP client — set NVR host, credentials, and permissions
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

Ask for the username, using a local admin account rather than a Ubiquiti SSO
account. Never ask the user to send the password in chat, and never place it in a
tool call or command argument. Ask for either
`UNIFI_PROTECT_PASSWORD_FILE=<absolute-path>` or
`UNIFI_PROTECT_PASSWORD_COMMAND=<absolute argv>`. A command provider can call a
Keychain, `pass`, or 1Password helper; it is not run through a shell and must not
prompt. If no indirect provider already exists, explain how to create one outside
the chat transcript or use a client-native masked secret UI, then wait.

Set exactly one password spelling; the server refuses to start if two are set. On
the Claude target `set-env.sh` only adds keys. Before changing the password
provider, remove `UNIFI_PROTECT_PASSWORD`, `UNIFI_PROTECT_PASSWORD_FILE`, and
`UNIFI_PROTECT_PASSWORD_COMMAND`. Before changing or skipping API-key setup,
remove `UNIFI_PROTECT_API_KEY`, `UNIFI_PROTECT_API_KEY_FILE`, and
`UNIFI_PROTECT_API_KEY_COMMAND`. Then add only the providers the user selected.
The Codex and OpenClaw targets replace the whole server entry.

> **AI-powered alarms need SuperAdmin.** The alarm-rule tools (`protect_alarm_list_rules` / `protect_alarm_get_rule`) surface AI-powered alarms from the UniFi-OS Alarm Manager only when the account is **SuperAdmin**; otherwise they return the classic automations view (with a `_meta` notice that AI alarms need SuperAdmin). A standard local admin runs every Protect tool fine. Mention SuperAdmin only if the user asks about AI alarms; don't require it for normal setup. On a combined UDM console, SuperAdmin also grants Network/UniFi-OS control — call that out so the user can decide.

### Optional API Key

After collecting the username and password provider, explain that a UniFi Protect API key enables selected capabilities implemented through the Protect Integration API, including sensor settings, per-camera chime ring settings, and viewer liveview assignment. Ask whether to configure an API-key provider too.

If yes, configure `UNIFI_PROTECT_API_KEY_FILE` or
`UNIFI_PROTECT_API_KEY_COMMAND`; never ask for or pass the raw key. If no, skip it.

## Step 3: Permission Configuration

Ask whether to enable write permissions. The guided setup explicitly disables all
Protect mutations unless the user opts in.

Options:
- Read-only for now
- Enable camera management
- Enable all device management
- Custom categories

Before writing policy values, inspect the selected client's existing
`unifi-protect` MCP environment. Remove every existing category-specific
`UNIFI_POLICY_PROTECT_<CATEGORY>_<ACTION>` entry, because those entries take
precedence over server-level defaults. Do not remove unrelated variables. Set
`UNIFI_PROTECT_TOOL_PERMISSION_MODE=confirm`, then add back only the
category/action overrides the user selected.

For read-only setup, explicitly configure
`UNIFI_POLICY_PROTECT_CREATE=false`, `UNIFI_POLICY_PROTECT_UPDATE=false`, and
`UNIFI_POLICY_PROTECT_DELETE=false`. For requested writes, keep those server-level
defaults and add only selected category/action overrides using the existing
`UNIFI_POLICY_PROTECT_<CATEGORY>_<ACTION>=true` format.

## Step 4: Write Configuration

On macOS/Linux, run the target-aware setup script with only values the user provided or selected:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  'UNIFI_PROTECT_PASSWORD_FILE=<absolute-path>' \
  UNIFI_PROTECT_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_PROTECT_CREATE=false \
  UNIFI_POLICY_PROTECT_UPDATE=false \
  UNIFI_POLICY_PROTECT_DELETE=false
```

Add optional values and policy variables to the same command, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_PROTECT_HOST=<host> \
  UNIFI_PROTECT_USERNAME=<username> \
  'UNIFI_PROTECT_PASSWORD_COMMAND=<absolute-argv>' \
  'UNIFI_PROTECT_API_KEY_FILE=<absolute-path>' \
  UNIFI_PROTECT_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_PROTECT_CREATE=false \
  UNIFI_POLICY_PROTECT_UPDATE=false \
  UNIFI_POLICY_PROTECT_DELETE=false \
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
