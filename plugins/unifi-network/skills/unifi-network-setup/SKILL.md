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

All three servers apply the same precedence: non-empty `UNIFI_<PRODUCT>_*`
values override shared `UNIFI_*` values; empty values count as unset. This applies
to host, username and credentials even where bundled YAML defaults name different
variables. Shared providers are fallback only. Multiple non-empty spellings
(plain, `_FILE`, `_COMMAND`) at the selected level refuse startup.

The setup helper switches providers atomically: selecting one spelling removes
its saved siblings at the same level while preserving unrelated settings. To
remove an authentication path, pipe a JSON patch setting all three saved
spellings to `null` (for example `UNIFI_NETWORK_PASSWORD`,
`UNIFI_NETWORK_PASSWORD_FILE`, `UNIFI_NETWORK_PASSWORD_COMMAND`). Remove or
override shared fallback settings deliberately too; deleting product settings
alone can reactivate shared credentials. Inherited environment providers must
also be corrected in the launcher. Never delete a working provider in a separate
preparatory write.

Before changing or skipping API-key setup, remove obsolete
`UNIFI_NETWORK_API_KEY`, `UNIFI_NETWORK_API_KEY_FILE`, and
`UNIFI_NETWORK_API_KEY_COMMAND` spellings with null deletions in the same patch;
keep only the selected replacement, or delete all three when deselecting it.

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

Before writing policy values, inspect a sanitized list of the selected client's
existing `unifi-network` MCP environment variable names.
Remove every existing category-specific
`UNIFI_POLICY_NETWORK_<CATEGORY>_<ACTION>` entry by including null deletions
in the same JSON patch, because those entries take precedence over server-level
defaults. Preserve unrelated variables. Set
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

### Codex upgrades

Codex setup pins a separate MCP entry that takes precedence over the plugin's
bundled server. After **every plugin upgrade**, resolve this newly installed
skill's plugin root and refresh the pin before restarting Codex:

```bash
bash <new-plugin-root>/scripts/set-env.sh --target codex --refresh
```

On Windows: `& <new-plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
This command needs no credential input and preserves the saved environment and
provider references. It validates providers, records the plugin and package
versions in `config.toml`, and prints the pinned package on success. Confirm that
version matches the new installed plugin. Use ordinary setup first if there is
no saved MCP entry; use the new plugin's scripts rather than an older cache path.

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

## Step 6: Final Message

For Claude Code, tell the user:

"Configuration saved to `.claude/settings.local.json`. Restart Claude Code or run `/reload-plugins`, then confirm the plugin is enabled with `/plugin`."

For Codex, tell the user:

"Codex MCP server `unifi-network` configured at the package version printed by setup. Restart Codex so the updated MCP server is loaded. After every plugin upgrade, re-run the new plugin’s setup with --target codex --refresh (PowerShell: -Target codex -Refresh)."

For OpenClaw, tell the user:

"OpenClaw MCP server `unifi-network` configured. Restart the OpenClaw Gateway so the updated MCP server is loaded."
