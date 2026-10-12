---
name: unifi-access-setup
description: Configure the UniFi Access MCP server for a supported MCP client — set controller host, credentials, API key, and permissions. Also use when the unifi-access server failed to start or its tools are missing, especially right after a plugin update, because in Claude Code the plugin no longer reads settings an earlier version saved in the project's .claude/settings.local.json, and this skill migrates them
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
require uv/uvx and the selected client's CLI (`claude`, `codex` or `openclaw`). A working
Python 3.11+ on PATH is used first; otherwise uv supplies managed Python
(with a possible first-run download). No separate Python installation is needed.
Do not substitute direct client registration commands, which can expose env
values in process arguments.

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

If another UniFi MCP server is already configured, ask whether Access is on the same controller. Inspect a sanitized summary of the existing host and variable names only. Do not print full settings or raw `mcp list/get/show` output: these can contain stored credentials.

## Step 2: Authentication

Access supports two auth paths:
- API key for the Access Developer API visitor family, including visitor reads,
  creation, and deletion, plus tool families that accept either credential
- Local proxy session with username and password for local-only management tool
  families and tool families that accept either credential

Ask whether the user wants API key only, username/password only, or both.
Recommend both for the widest Access tool coverage.

For username/password, ask only for the local username. Never ask the user to send
a password or API key in chat, and never place a raw secret in a tool call or
command argument. Ask for exactly one indirect provider per selected secret:
`UNIFI_ACCESS_PASSWORD_FILE=<absolute-path>` or
`UNIFI_ACCESS_PASSWORD_COMMAND=<absolute argv>`, and
`UNIFI_ACCESS_API_KEY_FILE=<absolute-path>` or
`UNIFI_ACCESS_API_KEY_COMMAND=<absolute argv>`. A command provider can call a
Keychain, `pass`, or 1Password helper; it is not run through a shell and must not
prompt. If no indirect provider already exists, explain how to create one outside
the chat transcript or use a client-native masked secret UI, then wait. In Claude
Code that UI is the plugin's options dialog (`/plugin`, then `unifi-access`, then
Configure options): its password and API key fields are masked and stored in
the system keychain.

All three servers apply the same precedence: non-empty `UNIFI_<PRODUCT>_*`
values override shared `UNIFI_*` values; empty values count as unset. This applies
to host, username and credentials even where bundled YAML defaults name different
variables. Shared providers are fallback only. Multiple non-empty spellings
(plain, `_FILE`, `_COMMAND`) at the selected level refuse startup.

The setup helper switches providers atomically: selecting one spelling removes
its saved siblings at the same level while preserving unrelated settings. To
remove an authentication path, pipe a JSON patch setting all three saved
spellings to `null` (for example `UNIFI_ACCESS_PASSWORD`,
`UNIFI_ACCESS_PASSWORD_FILE`, `UNIFI_ACCESS_PASSWORD_COMMAND`). Remove or
override shared fallback settings deliberately too; deleting product settings
alone can reactivate shared credentials. Inherited environment providers must
also be corrected in the launcher. Never delete a working provider in a separate
preparatory write.

Before changing or skipping API-key setup, remove obsolete
`UNIFI_ACCESS_API_KEY`, `UNIFI_ACCESS_API_KEY_FILE`, and
`UNIFI_ACCESS_API_KEY_COMMAND` spellings with null deletions in the same patch;
keep only the selected replacement, or delete all three when deselecting it.

At least one auth path is required.

## Step 3: Optional Settings

Ask whether to use defaults or customize:
- Defaults: controller port `443`, Access API port `12445`, SSL verification `false`, lazy tool loading
- Customize: ask for controller port (`UNIFI_ACCESS_PORT`), API port
  (`UNIFI_ACCESS_API_PORT`), SSL verification (`UNIFI_ACCESS_VERIFY_SSL`), and
  tool registration mode (`UNIFI_TOOL_REGISTRATION_MODE`: `lazy`, `eager` or
  `meta_only`; the Claude Code option is `registration_mode`)

## Step 4: Permission Configuration

Ask whether to enable write permissions. The guided setup explicitly disables all
Access mutations unless the user opts in.

For Codex and OpenClaw, offer:
- Read-only for now
- Enable visitor and credential management
- Enable door operations
- Enable all Access write permissions except delete operations
- Custom categories

For Claude Code, the plugin's options hold only the server-level gates. Offer:
read-only (the default), allow updates, allow creates and updates, or allow
creates, updates and deletes. Set `UNIFI_POLICY_ACCESS_CREATE`,
`UNIFI_POLICY_ACCESS_UPDATE` and `UNIFI_POLICY_ACCESS_DELETE` to `true` or `false`,
and keep `UNIFI_ACCESS_TOOL_PERMISSION_MODE=confirm` so every mutation is previewed
first. Per-category overrides (`UNIFI_POLICY_ACCESS_<CATEGORY>_<ACTION>`) are not
available for Claude Code and setup refuses them. A user who wants only some
categories writable can allow the action server-wide and decline the previews
they do not want, or keep the action off.

For Codex and OpenClaw, before writing policy values, inspect a sanitized list of the selected client's
existing `unifi-access` MCP environment variable names (for Codex and OpenClaw, the key names in
`~/.config/unifi-mcp/access.env`).
Remove every existing category-specific
`UNIFI_POLICY_ACCESS_<CATEGORY>_<ACTION>` entry by including null deletions
in the same JSON patch, because those entries take precedence over server-level
defaults. Preserve unrelated variables. Set
`UNIFI_ACCESS_TOOL_PERMISSION_MODE=confirm`, then add back only the
category/action overrides the user selected.

For read-only setup, explicitly configure `UNIFI_POLICY_ACCESS_CREATE=false`,
`UNIFI_POLICY_ACCESS_UPDATE=false`, and `UNIFI_POLICY_ACCESS_DELETE=false`. For
requested writes on Codex or OpenClaw, keep those server-level defaults and add
only selected category/action overrides using the existing
`UNIFI_POLICY_ACCESS_<CATEGORY>_<ACTION>=true` format.

## Step 5: Write Configuration

On macOS/Linux, run the target-aware setup script with only values the user provided or selected:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_ACCESS_HOST=<host> \
  'UNIFI_ACCESS_API_KEY_FILE=<absolute-path>' \
  UNIFI_ACCESS_USERNAME=<username> \
  'UNIFI_ACCESS_PASSWORD_FILE=<absolute-path>' \
  UNIFI_ACCESS_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_ACCESS_CREATE=false \
  UNIFI_POLICY_ACCESS_UPDATE=false \
  UNIFI_POLICY_ACCESS_DELETE=false
```

Add optional values and policy variables to the same command. Per-category
overrides apply to Codex and OpenClaw only, for example:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <codex|openclaw> \
  UNIFI_ACCESS_HOST=<host> \
  'UNIFI_ACCESS_API_KEY_COMMAND=<absolute-argv>' \
  UNIFI_ACCESS_USERNAME=<username> \
  'UNIFI_ACCESS_PASSWORD_COMMAND=<absolute-argv>' \
  UNIFI_ACCESS_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_ACCESS_CREATE=false \
  UNIFI_POLICY_ACCESS_UPDATE=false \
  UNIFI_POLICY_ACCESS_DELETE=false \
  UNIFI_ACCESS_API_PORT=12445 \
  UNIFI_POLICY_ACCESS_VISITORS_CREATE=true
```

The script handles the client-specific write:
- Claude: validates every value, then saves the plugin's Claude Code options
  with `claude plugin configure --values-stdin` (values on stdin): non-secret
  options in user `settings.json` (`pluginConfigs`), a raw password or API key
  in the system keychain. The options apply in every project
- Codex: validates every value, then atomically writes the settings file
  `~/.config/unifi-mcp/access.env` (`%USERPROFILE%\.config\unifi-mcp\access.env`
  on Windows), readable by the user only. The plugin's own server reads it through
  `UNIFI_SETTINGS_FILE`; setup writes no `config.toml` entry. Env never enters argv
- OpenClaw: writes the same settings file as Codex,
  `~/.config/unifi-mcp/access.env`, readable by the user only. The plugin's own
  server reads it through `UNIFI_SETTINGS_FILE`; setup writes no `openclaw.json`
  entry

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

The plugin's own MCP server is the one Codex runs, and it reads the settings
file setup wrote, so a plugin upgrade upgrades the server with nothing to rerun.
Codex installs an upgrade in the background as a session starts; the next
session runs the new server.

Setup before plugin 1.0.0 saved a `[mcp_servers.unifi-access]` entry in Codex's
`config.toml` instead. That entry takes precedence over the plugin's server and
keeps an old server version. Step 0 then prints a notice naming the entry and
`--refresh`. Relay it and, once the user agrees, run refresh from this skill's
plugin root, then restart Codex:

```bash
bash <plugin-root>/scripts/set-env.sh --target codex --refresh
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
Refresh needs no credential input. It moves the entry's `UNIFI_` settings,
provider references included, into the settings file, removes the entry from
`config.toml` after saving a private backup beside it, and names any other entry
settings it did not move. Ordinary setup does the same when it finds the entry.
It is needed once. If a settings file already exists and holds different
settings, refresh changes nothing and says which to remove.

Setup edits only that entry's tables in `config.toml`, so every other setting and
comment stays as written. If the file lays out its MCP servers in a form setup
cannot edit in place (dotted or inline `mcp_servers` keys), setup lets Codex
remove the entry, which drops the comments inside every `[mcp_servers.*]`
table, and says so in its output.

### OpenClaw upgrades

OpenClaw runs the plugin's own MCP server, which reads the settings file setup
wrote, so `openclaw plugins update` upgrades the server with nothing to rerun.
A running Gateway applies the update at the next agent turn.

Setup before plugin 1.0.0 saved an `mcp.servers.unifi-access` entry in
`openclaw.json` instead. That entry replaces the plugin's server and keeps an
old server version. Step 0 then prints a notice naming the entry and
`--refresh`. Relay it and, once the user agrees, run refresh from this skill's
plugin root:

```bash
bash <plugin-root>/scripts/set-env.sh --target openclaw --refresh
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target openclaw -Refresh`.
Refresh needs no credential input. It moves the entry's `UNIFI_` settings,
provider references included, into the settings file, saves a private backup of
`openclaw.json` beside it, then removes the entry with `openclaw mcp unset` and
names any other entry settings it did not move. Ordinary setup does the same
when it finds the entry. It is needed once. If a settings file already exists
and holds different settings, refresh changes nothing and says which to remove.

### Claude Code projects set up by an earlier plugin version

Earlier versions saved Claude Code settings in the project's
`.claude/settings.local.json`. This version no longer reads them; setup, the
prerequisite check and a session-start notice name the leftover variables. From
that project, run:

```bash
bash <plugin-root>/scripts/set-env.sh --target claude --migrate
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target claude -Migrate`. It
copies this plugin's settings into its options, then removes only this plugin's
keys from the project file atomically. Shared `UNIFI_*` keys are kept unless
every possible consumer is proven migrated; setup currently verifies only this
plugin's options. It names the retained shared keys and explains that other
consumers have not been verified as migrated. Output includes only variable
names, including what it moved and what has no Claude Code option (per-category
policy overrides). A missing provider file stops it with nothing changed.

Plugin options apply in every project. If options saved from another project
already hold a different host, username, port or site, `--migrate` refuses
and names those variables without values. Ask the user which settings every
project should use: rerun with `--replace` (`-Replace`) to make this project's
settings the options for every project, or remove this plugin's leftover
`UNIFI_ACCESS_*` keys from the project file to keep the saved options. A
session-start notice also fires in a project that still holds its own
`UNIFI_ACCESS_*` keys while options from another project are in use; offer the
same choice there. When the project's host, username and port equal the saved
options, the notice says nothing changes instead; offer to remove the leftover
keys, or to tidy up with `--migrate`, which also copies the project's other
settings, such as its credential source, into the options.

After the migration, in a session that was already open, run `/reload-plugins`
or start a new session. `/mcp reconnect` alone keeps the options the session
started with: it reports success, but the server stays in setup mode. Use
`/mcp reconnect plugin:unifi-access:unifi-access` only if `/mcp` shows the server as
failed. Once no UniFi plugin keys remain in the project file, the prerequisite
check names any shared `UNIFI_*` keys still there: Claude Code exports them into
every process in that project, so suggest removing them once nothing else needs
them.

### Recovery

On validation, dependency, registration, or write failure the previous file and
registration remain in place. Repair malformed configuration without discarding
unrelated settings, install the reported dependency, or correct the provider,
then rerun. `--dry-run` / `-DryRun` validates the patch without changing files and
omits values. OpenClaw setup reads `openclaw.json` as strict JSON; a JSON5
configuration is refused unchanged. After a forced termination,
remove adjacent `.setup-lock` and `.unifi-setup-*` staging directories only after
confirming no setup process is running. Staging files are private and may contain
credentials; delete them without displaying their contents. An interruption at
publication leaves either the old configuration or the complete new one.

## Step 6: Final Message

For Claude Code, tell the user:

"Saved as the unifi-access plugin's Claude Code options (a raw password or API key goes to the system keychain). In this session, run `/reload-plugins` (a new session also loads the options); `/mcp reconnect` alone keeps the options the session started with, so the server would stay in setup mode. Then run `/mcp` and check that `plugin:unifi-access:unifi-access` offers more than one tool: a server offering only its setup-status tool is still unconfigured. Use `/mcp reconnect plugin:unifi-access:unifi-access` only if `/mcp` shows the server as failed. Review or change the options with `/plugin`, then `unifi-access`, then Configure options."

For Codex, tell the user:

"Saved the settings for `unifi-access` to `~/.config/unifi-mcp/access.env`, readable by you only. The plugin's own server reads them and follows plugin upgrades on its own. Restart Codex so the server loads them."

For OpenClaw, tell the user:

"Saved the settings for `unifi-access` to `~/.config/unifi-mcp/access.env`, readable by you only. The plugin's own server reads them and follows plugin updates on its own. OpenClaw starts it with these settings in a new session or after `openclaw gateway restart`; a session that is already open keeps the unconfigured server until then."
