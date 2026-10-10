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

Each listed plugin's version equals the exact PyPI package version it launches,
for example plugin `0.37.0` runs `uvx unifi-network-mcp==0.37.0`. The release
workflow updates both together. Upgrading the plugin is how you upgrade the
server.

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
- Network access to PyPI the first time a version is launched.
- A reachable UniFi controller for the product, with the credentials described
  in each plugin's setup skill (`unifi-network-setup`, `unifi-protect-setup`,
  `unifi-access-setup`).
- Codex and OpenClaw: the setup skill registers the server with the client's
  own MCP command (`codex mcp add`, `openclaw mcp set`), so that client's CLI
  must be on `PATH`. OpenClaw setup also needs `python3`.
