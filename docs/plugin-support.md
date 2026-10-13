# Plugin support matrix

This page states what the UniFi MCP plugin bundles need and what has been
verified. For install steps, see the [agent install guide](agent-install.md);
to update an existing install, see the [plugin upgrade guide](plugin-upgrade.md).

## Bundles

| Bundle | Claude Code marketplace | Codex marketplace | MCP package |
|---|---|---|---|
| `unifi-network` | Listed | Listed | `unifi-network-mcp` |
| `unifi-protect` | Listed | Listed | `unifi-protect-mcp` |
| `unifi-access` | Listed | Listed | `unifi-access-mcp` |
| `unifi-intelligence` | Listed | Listed | None (skills only) |

Each plugin has its own semantic version for everything it ships. For example,
plugin `1.0.0` can launch `unifi-network-mcp==0.37.0`; the plugin version and
server package pin are independent. Every plugin started at `1.0.0` with this
scheme; `unifi-intelligence`, which replaces the unlisted `cross-product`
bundle, starts there as a new plugin.

**Plugin dependencies.** `unifi-intelligence` requires the `unifi-network` and
`unifi-protect` plugins. Its Claude Code manifest declares them in
`dependencies`, so Claude Code installs and enables them with it, and
`claude plugin prune` removes them once nothing needs them. Codex and OpenClaw
have no plugin dependencies; there, the plugin's description says to install
both first.

A plugin release is a plugin version bump merged to `main`; there is no
separate publish step, and server packages keep their own tagged releases. Each
client reads the default branch unless you pinned a ref when adding the
marketplace:

- **Claude Code** installs a release when the plugin version changes and you
  update. Auto-update is off by default for this marketplace (you can turn it
  on under `/plugin`, then **Marketplaces**), so run
  `claude plugin marketplace update unifi-plugins`, then
  `claude plugin update <plugin>@unifi-plugins`, then start a new session.
- **Codex** upgrades its marketplaces at the start of every session and
  reinstalls a plugin when its version changes (`codex plugin marketplace
  upgrade` does the same on demand). Codex runs the plugin's own server, so the
  server follows the upgrade from the next session (below).
- **OpenClaw** follows commits and changes nothing until you run
  `openclaw plugins update <id>`, which asks you to accept the plugin's
  capabilities (`--accept-capabilities` in scripts). OpenClaw runs the plugin's
  own server, so the server follows the update from the next agent turn; a
  running Gateway applies it without a restart.

Upgrade notes for each release, including the 1.0.0 Claude Code settings
migration, are in the [plugin upgrade guide](plugin-upgrade.md).

Contributors: the version, pin and release rules are in
[CONTRIBUTING.md](../CONTRIBUTING.md#plugin-changes) and the
`monorepo-release-pipeline` skill (Procedure E).

Claude loads its bundled server on upgrade, and so does Codex. **Codex setup
saves the settings in a per-user file,** `~/.config/unifi-mcp/<product>.env`
(`%USERPROFILE%\.config\unifi-mcp\<product>.env` on Windows), created
readable by the user only. The bundled entry in `.mcp.codex.json` names it with
`UNIFI_SETTINGS_FILE`, and the server loads it at startup. The process
environment wins over the file. The file holds dotenv-style `KEY="value"`
lines, only `UNIFI_` keys, single-line values; setup writes no `config.toml`
entry. On POSIX the server ignores the file if another user owns it or others
can write to it, and warns if others can read it. On Windows there is no
permission check, so keep the file in your own profile. Server releases from
`unifi-network-mcp` 0.37.1, `unifi-protect-mcp` 0.8.18 and `unifi-access-mcp`
0.6.13 read the file; earlier releases ignore it. Those releases also start in
setup mode while no controller host is configured: the server answers, offers
only the read-only `unifi_setup_status`, `protect_setup_status` or
`access_setup_status` tool, and makes no controller connection, so a Codex user
who has not run setup sees how to configure it instead of a failed server.

Setup before plugin 1.0.0 saved a `[mcp_servers.<plugin>]` entry in Codex's
`config.toml`, which takes precedence over the bundled server and keeps the
server version it names. The prerequisite check names such an entry, and this
non-secret command converts it once:

```bash
bash <plugin-root>/scripts/set-env.sh --target codex --refresh
```

On PowerShell use `& <plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
Refresh moves the entry's `UNIFI_` settings, provider references included, into
the settings file, then removes only that entry's tables from `config.toml`
after saving a private `config.toml.bak-<plugin>-<time>` beside it; comments and
other servers stay as written. It names any other entry setting it did not move.
It does not collect credentials or contact a controller. If a settings file
already holds different settings, it changes nothing and says which to remove.
If `config.toml` lays out its MCP servers in a form setup cannot edit in place,
setup lets `codex mcp remove` rewrite it and says so; that drops the comments
inside every `[mcp_servers.*]` table. A pin may be a PEP 440 development or
local version, such as `0.37.1.dev83+g<sha>`, when a candidate is tested before
release.

Codex uses `.mcp.codex.json`, which omits shell-style environment templates:
Codex 0.162.0 passes those templates literally, and the server expands the `~`
in `UNIFI_SETTINGS_FILE` itself. Server releases before setup mode refuse to
start until a controller host is configured. Optional `env_vars` forwarding carries
registration and safety controls from the launcher; application defaults apply
otherwise. Codex 0.162.0 ignores plugin-scoped environment settings, and a same-named
`[mcp_servers]` entry requires its own transport rather than merging the bundle's
command. Plugin-scoped settings can control tool policy, not supply setup env.

OpenClaw treats these bundles as Codex bundles and runs the server in
`.mcp.codex.json`. It passes the entry's `env` as written, expanding only its own
plugin-root placeholders, and the server expands the `~` itself. OpenClaw would
also merge a root `.mcp.json` into that server, so the bundles ship none and
declare Claude Code's server inline. OpenClaw setup writes the same settings
file and no `openclaw.json` entry. Setup before plugin 1.0.0 saved an
`mcp.servers.<plugin>` entry in `openclaw.json`, which replaces the bundled
server and keeps the server version it names. The prerequisite check names
such an entry, and this non-secret command converts it once:

```bash
bash <plugin-root>/scripts/set-env.sh --target openclaw --refresh
```

On PowerShell use `& <plugin-root>/scripts/set-env.ps1 -Target openclaw -Refresh`.
Refresh moves the entry's `UNIFI_` settings into the settings file, saves a
private `openclaw.json.bak-<plugin>-<time>` beside `openclaw.json`, then removes
the entry with `openclaw mcp unset`. It names any other entry setting it did not
move, never asks for credentials and makes no controller connection. OpenClaw
loads the bundled server from its next agent turn; a running Gateway needs no
restart.

Claude Code reads the server declared inline in `.claude-plugin/plugin.json`,
which maps each server variable to a plugin option (`${user_config.KEY}`). Claude Code prompts for these options when
the plugin is enabled, and setup saves them with `claude plugin configure`.
- **Where they live:** non-secret options in user `settings.json`; a raw password
  or API key in the system keychain.
- **What they cover:** connection settings, password and API-key providers, the
  server-level create, update and delete gates, permission mode and
  registration mode. The gates default to off, permission mode to `confirm`
  and registration to `lazy`. The deprecated auto-confirm switch has no option
  and is never exported; use the permission mode.
- **Dropped for Claude Code:** per-category policy overrides; setup refuses them.
  Allow the action server-wide and rely on confirm previews, or keep it off.
- **Upgrades:** options survive plugin upgrades.
- **Earlier plugin versions:** they wrote the project's
  `.claude/settings.local.json`, which this version no longer reads. A
  session-start notice names the leftover variables, and
  `set-env.sh --target claude --migrate` moves this plugin's settings into its
  options and atomically removes only its keys from the project file. Options
  apply in every project: the notice also fires in a project whose own keys are
  unused because options from another project are set, and `--migrate` refuses
  to replace a different saved host, username, port or site unless you add
  `--replace`. Shared
  `UNIFI_*` keys are kept unless every possible consumer is proven migrated.
  Setup currently verifies only this plugin's options, so it keeps shared keys
  and names them with the reason: other consumers have not been verified as
  migrated. Values are omitted.

The `unifi-intelligence` skills can also be installed as standalone skills (see the
[install guide](agent-install.md#standalone-skills-through-npm)). Incident
Investigation uses the incident evidence tools of the local Network and Protect
servers and needs no relay. With the pinned servers (`unifi-network-mcp` 0.38.1,
`unifi-protect-mcp` 0.9.1), lazy mode also lists the read-only lookups it uses
to tie a camera to the incident device, `protect_get_camera` and
`unifi_get_client_details`; with an older server or in `meta_only` mode it asks
the user for that mapping instead. Security Patrol and Visitor Audit need the cloud
worker: they use `unifi_location_timeline`, which only the cloud worker
provides, through a connected [relay](../packages/unifi-mcp-relay/); local stdio
servers do not expose it. The timeline reports Access as unsupported, so those
skills read Access events separately.

## Codex: tools on the first turn

Codex 0.162.0 waits `mcp_optional_startup_grace_ms` (default 1000 ms) for
plugin MCP servers when it builds a session's first tool list. A server still
starting is left out of that model request and is added from a later request,
once it is ready.

- **Warm `uv` cache:** the servers answer in about 0.5 s in lazy mode and 0.9 s
  in eager mode, and are in the first request.
- **First launch of a server version** (after install or a plugin upgrade, or
  with an empty cache): `uvx` creates a new environment, Python compiles every
  module it imports, and Protect loads PyAV's native libraries for the first
  time. This takes about 2 s for Network and 4.5 s for Protect when the
  dependencies are already cached, and 3 to 10 s with an empty cache. The
  first request of that session then has no UniFi tools. Later launches of the
  same version are warm.

Codex setup, and setup with `--refresh`, start the server once the way Codex
starts it, then stop it as soon as it answers. The server gets none of its
settings, so it reads no credentials and contacts no controller. The first
session after setup then finds the server warm. Setup waits up to 60 s; if the
server does not answer in time, setup says so and keeps the saved settings.

A plugin upgrade that moves the server pin is still a first launch. Codex
installs the upgrade in the background as a session starts, and the next
session starts the new server version for the first time. Running setup with
`--refresh` from the upgraded plugin starts that version ahead of time.

`codex exec` sends its prompt at once, so a one-step task can answer without
the UniFi tools. A short `codex exec` run can also end before a first launch
finishes, so the next run may start slowly too. In an interactive session the
servers usually finish starting while you type the first message.

To make the first request wait for the servers, use either of these:

- Set `mcp_optional_startup_grace_ms = 15000` at the top level of
  `~/.codex/config.toml`, or pass `-c mcp_optional_startup_grace_ms=15000` to
  `codex exec`. This applies to every optional MCP server, and only to the
  first tool list of a session. `0` waits up to each server's own start-up
  timeout instead.
- Name the plugin in the prompt, for example
  `[@unifi-network](plugin://unifi-network@unifi-plugins)`. Codex then waits
  for that plugin's server for that turn.

The plugins cannot set this for you. Codex reads the grace only from
`config.toml`. The per-server key that would make Codex wait, `required`,
also fails every Codex session in which the server cannot start.

## Client matrix

Each cell is labelled:

- `tested`: verified by installing the bundle in that real client.
- `unsupported`: known not to work, or not offered.
- `not tested`: expected from the packaging, but no real-client install evidence yet.

The repository checks manifests, paths, version pins and skill metadata
automatically (`tests/test_plugin_packaging.py`), and that every tool a plugin
names exists in the server release it pins (`scripts/plugin_tool_refs.py`).
Those checks do not count as `tested`. To produce `tested` evidence, follow the [plugin acceptance procedure](plugin-acceptance.md).

| | Claude Code | Codex | OpenClaw |
|---|---|---|---|
| macOS, bash/zsh | `not tested` | `not tested` | `not tested` |
| Linux, bash | `not tested` | `not tested` | `not tested` |
| Windows, PowerShell | `not tested` | `not tested` | `not tested` |
| Python 3.13 or newer through `uv`/`uvx` | `not tested` | `not tested` | `not tested` |
| Python older than 3.13 | `unsupported` | `unsupported` | `unsupported` |
| Install from the marketplace at the current plugin version | `not tested` | `not tested` | `not tested` |
| Upgrade between plugin versions | `not tested` | `not tested` | `not tested` |
| Transport: local stdio | `not tested` | `not tested` | `not tested` |
| Transport: remote HTTP from the plugin | `unsupported` | `unsupported` | `unsupported` |
| Connection: one UniFi product controller per plugin | `not tested` | `not tested` | `not tested` |
| Connection: relay | Not required by product plugins | Not required by product plugins | Not required by product plugins |
| `unifi-intelligence` from a marketplace | `tested` | `tested` | `tested` |
| Required plugins installed with `unifi-intelligence` | `tested` | `unsupported` | `unsupported` |
| Network and Protect plugins already installed are kept as they are | `tested` | Not applicable | Not applicable |
| Removing `unifi-intelligence` prunes only the plugins it installed | `tested` | Not applicable | Not applicable |
| `unifi-intelligence` skills with a real model | `not tested` | `not tested` | `not tested` |

The `unifi-intelligence` rows come from installing a release candidate in each
real client from a local mirror of this marketplace: Claude Code 2.1.296,
Codex 0.162.0 and OpenClaw 2026.9.9. In Claude Code, installing it on a clean
profile installed Network and Protect as dependencies, which `claude plugin
prune` later removed; for a user who already had both, it reinstalled nothing
and pruned nothing. Codex and OpenClaw installed it alone, as documented. The
same run exercised the skills, which then changed to stop for confirmation and
to make no read the user has not agreed to, so the skills row stays
`not tested`. Security Patrol and Visitor Audit were not run in Codex, and
OpenClaw ran only with a stub model, never a real one.

No minimum client version has been established for any client.

## Prerequisites

- `uv`, which provides `uvx`. Each plugin starts its server with
  `uvx --python-preference system <package>==<version>`.
- Python 3.13 or newer. `uv` prefers a system Python and can fall back to a
  Python it manages.
- For the setup helpers (`check-prereqs`, `set-env`), with any client: a
  Python 3.11 or newer on `PATH`, or `uv`, which then supplies a managed
  Python (possibly downloading it on first use). No separate Python install is
  needed when `uv` is installed.
- Network access to PyPI the first time a version is launched.
- A reachable UniFi controller for the product, with the credentials described
  in each plugin's setup skill (`unifi-network-setup`, `unifi-protect-setup`,
  `unifi-access-setup`).
- Claude Code: setup saves the plugin's options with `claude plugin configure`,
  so the `claude` CLI must be on `PATH`. Its session-start notice runs `sh`
  (Git Bash on Windows).
- Codex: setup writes the settings file itself and needs the `codex` CLI on
  `PATH` only to remove a pre-1.0.0 entry from a `config.toml` layout it cannot
  edit in place; the prerequisite check still requires it.
- OpenClaw: setup writes the settings file itself and needs the `openclaw` CLI
  on `PATH` only to remove a pre-1.0.0 entry with `openclaw mcp unset`; the
  prerequisite check still requires it. Setup reads `openclaw.json` as strict
  JSON and refuses a JSON5 file unchanged.
