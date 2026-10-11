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

Contributors must bump each affected plugin whenever anything under its
`plugins/<name>/` directory changes, including docs, skills, setup scripts and
MCP config. Patch covers plugin-only fixes/docs and patch server moves; minor
covers new skills/capabilities or minor server moves; major covers breaking
setup/configuration or major server moves. Before 1.0, breaking changes advance
minor and additive changes advance patch (SemVer 0.x).

Set `version` only in existing plugin manifests, identical across Claude and
Codex when both exist, with at least one manifest per plugin. Cross-product keeps
only its Claude manifest and stays unlisted. Marketplace entries carry no
`version`. The server stays separately pinned in `.mcp.json` and
`.mcp.codex.json` (and inline Claude config when present), identically for both
clients. Each pin must have a package release tag.

The release workflow automatically moves pins and bumps the plugin by the size
of the server change, using the same tested module as the PR guard. Plugin-only
changes ship through a manifest bump and merge without a Python package release.
`make check-plugin-versions`, also run by `make pre-commit`, checks against the
merge base with `origin/main`; PR CI uses the PR base SHA. Fetch history and tags
first: a missing base fails. Changed plugins must have valid matching SemVer
strictly greater than at that merge base. Version-only bumps are allowed.

Claude loads its bundled server on upgrade. **Codex setup creates a separate, version-pinned MCP entry
that takes precedence over the bundle. After every plugin upgrade, re-run setup
from the newly installed plugin before restarting Codex.** Setup records the pin
in a comment in `config.toml` and prints the package version on success. Preserve
the saved environment with this non-secret command:

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
  server-level create, update and delete gates, permission mode, auto-confirm
  and registration mode. The gates default to off, permission mode to `confirm`
  and registration to `lazy`.
- **Dropped for Claude Code:** per-category policy overrides; setup refuses them.
  Allow the action server-wide and rely on confirm previews, or keep it off.
- **Upgrades:** options survive plugin upgrades.
- **Earlier plugin versions:** they wrote the project's
  `.claude/settings.local.json`, which this version no longer reads. A
  session-start notice names the leftover variables, and
  `set-env.sh --target claude --migrate` moves them into the options.

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
automatically (`tests/test_plugin_packaging.py`). Those checks do not count as
`tested`.

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
