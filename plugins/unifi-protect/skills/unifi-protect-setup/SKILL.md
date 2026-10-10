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

On Windows, use `../../scripts/set-env.ps1 -Target <claude|codex|openclaw>`
for every target. Use the matching PowerShell prerequisite checker. Both helpers
require uv/uvx; Codex and OpenClaw also require their client CLI. A working
Python 3.11+ on PATH is used first; otherwise uv supplies managed Python
(with a possible first-run download). No separate Python installation is needed.
Do not substitute direct client registration commands, which can expose env
values in process arguments.

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

If another UniFi MCP server is already configured, ask whether Protect is on the same controller. Inspect a sanitized summary of the existing host and variable names only. Do not print full settings or raw `mcp list/get/show` output: these can contain stored credentials.

## Step 2: Credentials

Shared credentials can be reused deliberately; prefer explicit product-scoped
providers when configuring this plugin. Apply the precedence rules below before
assuming an existing shared credential will be selected.

Ask for the username, using a local admin account rather than a Ubiquiti SSO
account. Never ask the user to send the password in chat, and never place it in a
tool call or command argument. Ask for either
`UNIFI_PROTECT_PASSWORD_FILE=<absolute-path>` or
`UNIFI_PROTECT_PASSWORD_COMMAND=<absolute argv>`. A command provider can call a
Keychain, `pass`, or 1Password helper; it is not run through a shell and must not
prompt. If no indirect provider already exists, explain how to create one outside
the chat transcript or use a client-native masked secret UI, then wait.

All three servers apply the same precedence: non-empty `UNIFI_<PRODUCT>_*`
values override shared `UNIFI_*` values; empty values count as unset. This applies
to host, username and credentials even where bundled YAML defaults name different
variables. Shared providers are fallback only. Multiple non-empty spellings
(plain, `_FILE`, `_COMMAND`) at the selected level refuse startup.

The setup helper switches providers atomically: selecting one spelling removes
its saved siblings at the same level while preserving unrelated settings. To
remove an authentication path, pipe a JSON patch setting all three saved
spellings to `null` (for example `UNIFI_PROTECT_PASSWORD`,
`UNIFI_PROTECT_PASSWORD_FILE`, `UNIFI_PROTECT_PASSWORD_COMMAND`). Remove or
override shared fallback settings deliberately too; deleting product settings
alone can reactivate shared credentials. Inherited environment providers must
also be corrected in the launcher. Never delete a working provider in a separate
preparatory write.

Before changing or skipping API-key setup, remove obsolete
`UNIFI_PROTECT_API_KEY`, `UNIFI_PROTECT_API_KEY_FILE`, and
`UNIFI_PROTECT_API_KEY_COMMAND` spellings with null deletions in the same patch;
keep only the selected replacement, or delete all three when deselecting it.

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

Before writing policy values, inspect a sanitized list of the selected client's
existing `unifi-protect` MCP environment variable names.
Remove every existing category-specific
`UNIFI_POLICY_PROTECT_<CATEGORY>_<ACTION>` entry by including null deletions
in the same JSON patch, because those entries take precedence over server-level
defaults. Preserve unrelated variables. Set
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
- Claude: validates and atomically merges `.claude/settings.local.json`
- Codex: stages registration in a private `CODEX_HOME`, merges env without argv,
  validates with the client, then atomically replaces `config.toml`
- OpenClaw: stages `mcp set` without credentials, merges env, validates offline,
  then atomically replaces `OPENCLAW_CONFIG_PATH` (or the default config)

For raw values or null deletions, use JSON stdin: `set-env.sh --target <target>
--input-json` or `set-env.ps1 -Target <target> -InputJson`. Have the user supply
this JSON locally from a private file or a masked input UI; never put raw secrets
in chat, a tool call, command arguments, or a shell history entry. Provider
references in the examples are non-secret paths or helper argv, never embedded
passwords or API keys. Setup checks that provider files are readable and non-empty
and provider executables exist; it does not read secrets, execute providers, or
contact the controller. Provider output and controller authentication are checked
only when the server starts.

### Recovery

On validation, dependency, registration, or write failure the previous file and
registration remain in place. Repair malformed configuration without discarding
unrelated settings, install the reported dependency, or correct the provider,
then rerun. `--dry-run` / `-DryRun` validates the patch without changing files and
omits values. Automatic OpenClaw setup requires strict JSON; JSON5 configurations
are refused unchanged and need the client editor. After a forced termination,
remove adjacent `.setup-lock` and `.unifi-setup-*` staging directories only after
confirming no setup process is running. Staging files are private and may contain
credentials; delete them without displaying their contents. An interruption at
publication leaves either the old configuration or the complete new one.

## Step 5: Final Message

For Claude Code, tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code or run `/reload-plugins`, then confirm the plugin is enabled with `/plugin`."

For Codex, tell the user:

"Codex MCP server `unifi-protect` configured. Restart Codex so the updated MCP server is loaded."

For OpenClaw, tell the user:

"OpenClaw MCP server `unifi-protect` configured. Restart the OpenClaw Gateway so the updated MCP server is loaded."
