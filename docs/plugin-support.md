# Plugin support matrix

This page states what the UniFi MCP plugin bundles need and what has been
verified. For install steps, see the [agent install guide](agent-install.md).

## Bundles

| Bundle | Claude Code marketplace | Codex marketplace | MCP package |
|---|---|---|---|
| `unifi-network` | Listed | Listed | `unifi-network-mcp` |
| `unifi-protect` | Listed | Listed | `unifi-protect-mcp` |
| `unifi-access` | Listed | Listed | `unifi-access-mcp` |
| `cross-product` | Not listed | Not listed | None (skills only) |

Each plugin has its own semantic version for everything it ships. For example,
plugin `1.0.0` can launch `unifi-network-mcp==0.37.0`; the plugin version and
server package pin are independent. The advertised plugins and unlisted
cross-product bundle start at `1.0.0` with this scheme.

A plugin release is a plugin version bump merged to `main`; there is no
separate publish step, and server packages keep their own tagged releases. Each
client reads the default branch unless you pinned a ref when adding the
marketplace:

- **Claude Code** installs a release when the plugin version changes and you
  update. Auto-update is off for this marketplace, so run
  `claude plugin marketplace update unifi-plugins`, then
  `claude plugin update <plugin>@unifi-plugins`, then `/reload-plugins`.
- **Codex** reinstalls only on a version change: run
  `codex plugin marketplace upgrade`, then re-run setup with `--refresh` (below).
- **OpenClaw** follows commits: run `openclaw plugins update <id>`.

Contributors: the version, pin and release rules are in
[CONTRIBUTING.md](../CONTRIBUTING.md#plugin-changes) and the
`monorepo-release-pipeline` skill (Procedure E).

Claude loads its bundled server on upgrade. **Codex setup creates a separate, version-pinned MCP entry
that takes precedence over the bundle. After every plugin upgrade, re-run setup
from the newly installed plugin before restarting Codex.** Setup pins the
package in the server entry's `args` and prints the package version on success.
It edits only that server's tables in `config.toml`, so the file's comments and
other servers stay as written; `codex mcp add` and `codex mcp remove` rewrite the
file and drop the comments inside every `[mcp_servers.*]` table. A pin may be a
PEP 440 development or local version, such as `0.37.1.dev83+g<sha>`, when a
candidate is tested before release. Preserve the saved environment with this
non-secret command:

```bash
bash <new-plugin-root>/scripts/set-env.sh --target codex --refresh
```

On PowerShell use `& <new-plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
Resolve `<new-plugin-root>` from the current installed plugin, not an older cache
path. Refresh preserves saved settings and provider references, validates them,
and atomically updates the pin; it does not collect credentials or contact a
controller. Run ordinary setup first if there is no saved MCP entry.

Codex uses `.mcp.codex.json`, which omits shell-style environment templates:
Codex 0.162.0 passes those templates literally. The Codex config therefore leaves
credential settings unset until setup supplies them. Published servers still
refuse startup until a controller host is configured; run setup before expecting
an MCP handshake. Optional `env_vars` forwarding carries
registration and safety controls from the launcher; application defaults apply
otherwise. Codex 0.162.0 ignores plugin-scoped environment settings, and a same-named
`[mcp_servers]` entry requires its own transport rather than merging the bundle's
command. Plugin-scoped settings can control tool policy, not supply setup env.

Claude Code reads the bundle's `.mcp.json`, which maps each server variable to a
plugin option (`${user_config.KEY}`). Claude Code prompts for these options when
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
  `set-env.sh --target claude --migrate` moves them into the options. When no
  other UniFi plugin's settings remain in the file, it also removes the shared
  `UNIFI_*` settings it read, so none stay visible to the project's sessions.

The `cross-product` skills can be installed as standalone skills (see the
[install guide](agent-install.md#standalone-skills-through-npm)), but their
`unifi_location_timeline` tool is provided only through the
[relay](../packages/unifi-mcp-relay/). Local stdio servers do not expose it.

## Client matrix

Each cell is labelled:

- `tested`: verified by installing the bundle in that real client.
- `unsupported`: known not to work, or not offered.
- `not tested`: expected from the packaging, but no real-client install evidence yet.

The repository checks manifests, paths, version pins and skill metadata
automatically (`tests/test_plugin_packaging.py`), and that every tool a plugin
names exists in the server release it pins (`scripts/plugin_tool_refs.py`).
Those checks do not count as `tested`.

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
| `cross-product` from a marketplace | `unsupported` | `unsupported` | `unsupported` |

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
- Codex and OpenClaw: the setup skill registers the server with the client's
  own MCP command (`codex mcp add`, `openclaw mcp set`), so that client's CLI
  must be on `PATH`.
