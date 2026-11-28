---
name: unifi-innerspace-setup
description: Configure the UniFi InnerSpace MCP server for a supported MCP client — set the console host, its certificate fingerprint and the console login (username and a password source). Also use when the unifi-innerspace server failed to start, offers only its setup-status tool, or its tools are missing
allowed-tools: Read, Bash, AskUserQuestion
---

# Set Up UniFi InnerSpace MCP Server

Walk the user through connecting the InnerSpace server to the UniFi console
that runs the InnerSpace application. Ask one question at a time and wait for
the answer before continuing.

InnerSpace uses the console's login session only: a local username and a
password. It never uses an API key. Never reuse or offer a console API key,
the shared `UNIFI_API_KEY`, or another plugin's credentials for InnerSpace.

## Interaction Rules

Use the client target that matches the current agent runtime:
- Claude Code: `claude`
- Codex: `codex`
- OpenClaw: `openclaw`

If the runtime is unclear, ask which client to configure. For questions, use
the platform's blocking question tool when available (`AskUserQuestion` in
Claude Code, `request_user_input` in Codex). If no blocking question tool is
available, ask in chat with numbered options and wait for the user's reply.

This skill may come from a complete UniFi plugin or a standalone `npx skills`
install. Before using a helper script, verify that the plugin's `scripts/`
directory exists. If it does not, do not guess a relative path: follow the
[canonical agent installation guide](https://github.com/sirkirby/unifi-mcp/blob/main/docs/agent-install.md)
for the client's native MCP registration path. A standalone skill install does
not install or register the MCP server by itself.

On macOS and Linux, resolve setup scripts relative to this skill file:
- `../../scripts/check-prereqs.sh`
- `../../scripts/set-env.sh`

When the host exposes a plugin-root variable such as `CLAUDE_PLUGIN_ROOT`,
using `$CLAUDE_PLUGIN_ROOT/scripts/...` is also valid. Do not assume the
current shell directory is the plugin root.

On Windows, use `../../scripts/set-env.ps1 -Target <claude|codex|openclaw>`
for every target, and the matching PowerShell prerequisite checker. Both
helpers require uv/uvx and the selected client's CLI (`claude`, `codex` or
`openclaw`). A working Python 3.11+ on PATH is used first; otherwise uv
supplies managed Python. Do not substitute direct client registration
commands, which can expose env values in process arguments.

## Step 0: Check Prerequisites

Before asking for anything else, run the prerequisite checker for the current OS.

On macOS/Linux:

```bash
bash <path-to-plugin>/scripts/check-prereqs.sh --target <claude|codex|openclaw> "unifi-innerspace"
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File <path-to-plugin>/scripts/check-prereqs.ps1 -Target <claude|codex|openclaw> -PluginName "unifi-innerspace"
```

If the script exits non-zero, stop and report the error. Do not proceed.

## Step 1: Console Host

Ask: "What is the IP address or hostname of the UniFi console that runs
InnerSpace?" Example: `192.168.1.1`. Ask for the console's HTTPS port only if
it is not the default `443`. Port 3005 is the MCP server's own HTTP port, not
the console's; never use it here.

## Step 2: Certificate Fingerprint

Pin the console's certificate before entering any password. Without
verification or a pin, anyone on the network path between this machine and
the console can read the password when the server logs in, because the
console's factory certificate is self-signed and is otherwise not checked.

Run this with the host and port from Step 1, and show the user the printed
fingerprint to confirm against the console:

```bash
openssl s_client -connect <host>:<port> </dev/null 2>/dev/null \
  | openssl x509 -noout -fingerprint -sha256
```

Save it as `UNIFI_INNERSPACE_SSL_FINGERPRINT` (the Claude Code option is
`ssl_fingerprint`). A pin takes precedence over SSL verification. The
connection fails after the console's certificate changes, for example after a
factory reset, until the pin is updated. If the console has a certificate a
system trust store accepts, `UNIFI_INNERSPACE_VERIFY_SSL=true` (option
`verify_ssl`) is the alternative. If the user declines both, say plainly that
the password can be read on the LAN, and continue only if they agree. Details:
https://github.com/sirkirby/unifi-mcp/blob/main/docs/tls-verification.md

## Step 3: Console Login

Ask only for the local username (`UNIFI_INNERSPACE_USERNAME`). Never ask the
user to send a password in chat, and never place a raw password in a tool
call or command argument. Ask for exactly one password source:
`UNIFI_INNERSPACE_PASSWORD_FILE=<absolute-path>` or
`UNIFI_INNERSPACE_PASSWORD_COMMAND=<absolute argv>`. A command source can call
a Keychain, `pass` or 1Password helper; it is not run through a shell and must
not prompt. If no source exists yet, explain how to create one outside the
chat transcript, or use a client-native masked secret UI, then wait. In Claude
Code that UI is the plugin's options dialog (`/plugin`, then
`unifi-innerspace`, then Configure options): its password field is masked and
stored in the system keychain.

InnerSpace settings use the `UNIFI_INNERSPACE_` prefix only. Setup refuses the
shared `UNIFI_HOST`, `UNIFI_USERNAME` and `UNIFI_PASSWORD` keys and any API key,
and it never counts a shared password as InnerSpace's. The server itself still
falls back, key by key, to a shared `UNIFI_HOST`, `UNIFI_USERNAME` or
`UNIFI_PASSWORD` (or its `_FILE` / `_COMMAND`) for each InnerSpace setting left
unset, but it uses the shared username and password only when no InnerSpace
host is set or when the InnerSpace host names the same console as
`UNIFI_HOST`. Claude Code starts the server with the environment it was
started in; Codex and OpenClaw pass only the variables the plugin lists. So if
that environment holds shared values, set every InnerSpace connection value
here rather than relying on them. Two spellings of the
password (plain, `_FILE`, `_COMMAND`) refuse startup; selecting one removes the
saved others. To remove the password, pipe a JSON patch setting all three to
`null`.

Claude Code 2.1.296 and earlier cannot clear a password held in the system
keychain. Setup then refuses, with nothing changed, any change that would
clear it, and names the choices: keep the saved password, or run
`claude plugin uninstall` and `claude plugin install` with the plugin id it
names (usually `unifi-innerspace@unifi-plugins`), then rerun setup.
Uninstalling clears every option of the plugin, so offer it and never run it
without the user's consent. On a newer release, change the password source in
a run of its own, then other settings in a second run.

## Step 4: Write Permissions

Ask whether to enable writes. The guided setup turns every InnerSpace write off
unless the user opts in; on Codex and OpenClaw the first setup run saves the
create, update and delete gates as `false` and the permission mode as
`confirm` unless the run sets them. Offer: read-only (the default), allow updates, allow
creates and updates, or allow creates, updates and deletes (removals and the
plan scale replacement are deletes). Set `UNIFI_POLICY_INNERSPACE_CREATE`,
`UNIFI_POLICY_INNERSPACE_UPDATE` and `UNIFI_POLICY_INNERSPACE_DELETE` to `true`
or `false` (Claude Code options `policy_create`, `policy_update` and
`policy_delete`), and keep `UNIFI_INNERSPACE_TOOL_PERMISSION_MODE=confirm`
(option `permission_mode`) so every write is previewed first. Setup also accepts
`bypass`, which runs writes without a preview; set it only when the user asks
for it.

For Codex and OpenClaw, setup also accepts the category gates
`UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>` (`true` or `false`) that the
server defines: `WALLS` (create, update, delete), `WALL_TYPES` (create,
update), `ATTENUATION` (create, update, delete), `FLOOR_PLANS` (update, delete)
and `PROJECT` (update). Claude Code has no option for them and setup refuses
them there. Before writing gate values, inspect the key names in
`~/.config/unifi-mcp/innerspace.env` and remove every existing category gate
with null deletions in the same JSON patch, because a category gate takes
precedence over the server-level ones; then add back only the category gates
the user selected.

For Codex and OpenClaw, setup also accepts `UNIFI_INNERSPACE_READ_ONLY` and
`UNIFI_INNERSPACE_REQUIRE_PREVIEW_TOKEN` (`true` or `false`); Claude Code has
no option for them. The saved InnerSpace permission mode wins over a global
`UNIFI_TOOL_PERMISSION_MODE` in the client's environment; without it, a global
`bypass` there runs InnerSpace writes without a preview.

## Step 5: Optional Settings

Ask whether to keep the defaults: port `443`, SSL verification off (with the
pin from Step 2), lazy tool loading. To customize, ask for the port
(`UNIFI_INNERSPACE_PORT`) and the tool registration mode
(`UNIFI_TOOL_REGISTRATION_MODE`: `lazy`, `eager` or `meta_only`; the Claude
Code option is `registration_mode`). For Codex and OpenClaw, setup also
accepts the operation-gate budgets `UNIFI_INNERSPACE_WRITE_HOLD_SECONDS` (10 to
3600), `UNIFI_INNERSPACE_CALL_WAIT_SECONDS` (1 to 3600) and
`UNIFI_INNERSPACE_READ_CONCURRENCY` (1 to 64), and
`UNIFI_INNERSPACE_MCP_CONTENT_MODE` (`adaptive`, `compat` or `compact`); offer
them only when the user asks, for example after repeated busy refusals. Setup
refuses everything else, including the MCP HTTP settings (the plugin runs the
server over stdio) and the redaction switch, and names the refused key.

## Step 6: Write Configuration

On macOS/Linux, run the setup script with only the values the user provided:

```bash
bash <path-to-plugin>/scripts/set-env.sh --target <claude|codex|openclaw> \
  UNIFI_INNERSPACE_HOST=<host> \
  UNIFI_INNERSPACE_SSL_FINGERPRINT=<fingerprint> \
  UNIFI_INNERSPACE_USERNAME=<username> \
  'UNIFI_INNERSPACE_PASSWORD_FILE=<absolute-path>' \
  UNIFI_INNERSPACE_TOOL_PERMISSION_MODE=confirm \
  UNIFI_POLICY_INNERSPACE_CREATE=false \
  UNIFI_POLICY_INNERSPACE_UPDATE=false \
  UNIFI_POLICY_INNERSPACE_DELETE=false
```

The script handles the client-specific write:
- Claude: validates every value, then saves the plugin's Claude Code options
  with `claude plugin configure --values-stdin` (values on stdin): non-secret
  options in user `settings.json`, a raw password in the system keychain. The
  options apply in every project
- Codex and OpenClaw: validates every value, then atomically writes the
  settings file `~/.config/unifi-mcp/innerspace.env`
  (`%USERPROFILE%\.config\unifi-mcp\innerspace.env` on Windows), readable by
  the user only. The plugin's own server reads it through
  `UNIFI_SETTINGS_FILE`; setup writes no MCP client entry. Codex setup also
  starts the server once so the first session finds it ready

For a raw password or null deletions, use JSON stdin: `set-env.sh --target
<target> --input-json` or `set-env.ps1 -Target <target> -InputJson`. Have the
user supply this JSON locally from a private file or a masked input UI; never
put the password in chat, a tool call, command arguments or shell history.
Setup checks that a password file is readable and non-empty and that a
password command's executable exists; it never reads the password, runs the
command, or contacts the console. The login is checked only when the server
starts. Setup output names variables, never their values: do not print a
password command either.

There is no earlier InnerSpace setup to migrate. Setup refuses `--migrate`,
and it refuses to run while a manual `unifi-innerspace` entry in Codex's
`config.toml` or `openclaw.json` shadows the plugin's server: remove that
entry with the client editor, then rerun.

On a failure the previous settings remain in place. `--dry-run` / `-DryRun`
validates without changing anything and omits values. After a forced
termination, remove adjacent `.setup-lock` and `.unifi-setup-*` staging
entries only after confirming no setup is running, without displaying them.

## Step 7: Final Message

For Claude Code, tell the user:

"Saved as the unifi-innerspace plugin's Claude Code options (a raw password goes to the system keychain). In this session, run `/reload-plugins` (a new session also loads the options); `/mcp reconnect` alone keeps the options the session started with, so the server would stay in setup mode. Then run `/mcp` and check that `plugin:unifi-innerspace:unifi-innerspace` offers more than one tool: a server offering only its setup-status tool is still unconfigured. Use `/mcp reconnect plugin:unifi-innerspace:unifi-innerspace` only if `/mcp` shows the server as failed."

For Codex, tell the user:

"Saved the settings for `unifi-innerspace` to `~/.config/unifi-mcp/innerspace.env`, readable by you only. The plugin's own server reads them and follows plugin upgrades on its own. Restart Codex so the server loads them."

For OpenClaw, tell the user:

"Saved the settings for `unifi-innerspace` to `~/.config/unifi-mcp/innerspace.env`, readable by you only. The plugin's own server reads them and follows plugin updates on its own. OpenClaw starts it with these settings in a new session or after `openclaw gateway restart`."

Then suggest `innerspace_get_status` as the first call: it says whether the
InnerSpace application is installed and running. Real-client acceptance of
this plugin is not yet measured.
