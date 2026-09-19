# Install UniFi MCP with an agent

Last reviewed: 2026-09-19

This guide is written for both people and coding agents. It separates three
things that are easy to confuse:

1. A **plugin** can install the MCP server definition and its skills together.
2. A **skill install** adds guidance for the agent, but does not register or run
   an MCP server.
3. A **manual MCP install** registers a published UniFi MCP package with a
   client that already supports MCP.

Install only the UniFi products the user needs. Network, Protect, and Access
are separate servers; loading all three adds tools and context that may not be
useful for a particular deployment.

## Instructions for the installing agent

Before changing anything:

1. Identify the user's operating system and agent client.
2. Ask whether they need Network, Protect, Access, or more than one product.
3. Check that `uvx` is available. If it is missing, explain the official
   [uv installation options](https://docs.astral.sh/uv/getting-started/installation/)
   and wait before installing software globally.
4. Show the exact commands and configuration files you intend to change, then
   wait for confirmation.

During setup:

- When session authentication is selected, use a dedicated local UniFi account,
  not a Ubiquiti cloud SSO account. API-key-only setup does not require that
  account.
- Do not ask the user to paste a password or API key into the chat. Prefer a
  `*_PASSWORD_FILE`, `*_PASSWORD_COMMAND`, `*_API_KEY_FILE`, or
  `*_API_KEY_COMMAND` setting where the selected server supports it. Otherwise,
  direct the user to the client's own sensitive-value prompt or configuration
  UI.
- Explicitly set the selected server's permission mode to `confirm`. Before
  applying policy defaults to an existing configuration, remove its
  product-scoped category overrides (`UNIFI_POLICY_<SERVER>_<CATEGORY>_<ACTION>`),
  because those take precedence over server-level gates. Unless the user
  separately requests write access, set the server's `CREATE`, `UPDATE`, and
  `DELETE` gates to `false`; then add back only the category/action overrides
  the user selected.
- Do not disable TLS verification without explaining the tradeoff. Many local
  UniFi consoles use a self-signed certificate, but a trusted certificate is
  preferred.
- Do not edit shell startup files or machine-wide settings unless the user
  explicitly approves that separate change.

After setup, reload the client, confirm that the MCP server connects, and list
its tools. With session credentials, run one harmless read-only
system-information or health request. For Network API-key-only setup, use a
supported inventory request such as listing devices, clients, networks, or
WLANs instead. If any step is unavailable or differs from the client's current
documentation, stop and explain the mismatch instead of guessing.

## Choose an installation path

| Client | Recommended path | Status |
|---|---|---|
| Claude Code | Repository plugin marketplace | Supported |
| Codex | Repository plugin marketplace | Supported |
| GitHub Copilot CLI | Repository plugin marketplace | Plugin installation verified; MCP connection validation pending |
| OpenClaw | Repository plugin marketplace | Supported |
| OpenCode | Native `opencode mcp add`; optional standalone skills or plugin | Native MCP support verified; plugin packaging is a later convenience option |
| Antigravity CLI / IDE | Native MCP configuration, Agent Skills, or plugin | Native formats verified; UniFi packaging under validation |
| Cursor | Native MCP configuration; marketplace packaging planned | Manual setup under validation |
| Devin Local in Devin Desktop / Devin CLI | Native `devin mcp add`; optional standalone skills or plugin | Shared harness and MCP config verified; UniFi packaging under validation |
| Cascade in Devin Desktop | Devin Settings > Cascade > MCP Servers | Separate legacy Desktop path; manual setup only |

Gemini CLI is not a recommended individual-user path. Google has moved that
terminal experience to Antigravity CLI. Devin Desktop is the current name for
Windsurf, so new documentation should use Devin terminology even where legacy
configuration paths remain during migration.

## Native plugin marketplaces

### Claude Code

In Claude Code:

```text
/plugin marketplace add sirkirby/unifi-mcp
/plugin install unifi-network@unifi-plugins
/unifi-network:unifi-network-setup
```

Replace `unifi-network` with `unifi-protect` or `unifi-access` as needed.
The setup skill checks prerequisites and guides credential and permission
configuration.

Rollback: use Claude Code's `/plugin` interface to uninstall only the UniFi
plugin that was added, then remove the matching UniFi values from the project
configuration if the user no longer needs them.

### Codex

Register the marketplace once:

```bash
codex plugin marketplace add sirkirby/unifi-mcp
```

Open Codex, run `/plugins`, install the chosen UniFi product, then ask:

```text
Use the unifi-network-setup skill to configure this for Codex.
```

The setup skill registers the server through `codex mcp add`. Restart Codex
after configuration. Roll back by uninstalling the selected plugin and removing
only its matching MCP entry with the current `codex mcp` command.

### GitHub Copilot CLI

The existing marketplace can be discovered and installed by Copilot CLI:

```bash
copilot plugin marketplace add sirkirby/unifi-mcp
copilot plugin install unifi-network@unifi-plugins
```

Plugin discovery and installation have been verified in a clean profile. Treat
the MCP connection as provisional until the installed plugin completes an
end-to-end launch and handshake test. Use `copilot plugin` help for the current
uninstall command rather than deleting profile directories manually.

### OpenClaw

```bash
openclaw plugins install unifi-network \
  --marketplace https://github.com/sirkirby/unifi-mcp
openclaw gateway restart
```

Run the matching setup skill after restart. Repeat only for other UniFi
products the user selected.

## Standalone skills through npm

The open [skills CLI](https://skills.sh/docs/cli) runs through `npx`; UniFi MCP
does not need a separate npm package. Use a product subtree so the installer
does not discover contributor-only skills from the repository root:

```bash
npx skills add https://github.com/sirkirby/unifi-mcp/tree/main/plugins/unifi-network
npx skills add https://github.com/sirkirby/unifi-mcp/tree/main/plugins/unifi-protect
npx skills add https://github.com/sirkirby/unifi-mcp/tree/main/plugins/unifi-access
npx skills add https://github.com/sirkirby/unifi-mcp/tree/main/plugins/cross-product
```

Choose only the relevant command. The installer prompts for the destination
agent and skills. These commands install instructions, not the MCP process. The
agent must still register the corresponding PyPI package through a native
plugin or the client's MCP configuration.

Do not use `npx skills add sirkirby/unifi-mcp` at the repository root. That
scope also discovers maintainer workflow skills that are not part of the user
product.

## Native OpenCode MCP setup

OpenCode supports local MCP servers directly; a UniFi-specific OpenCode plugin
is not required to launch the server. Its npm plugin API can also register MCP
servers and skills, so a plugin could provide a useful one-install experience,
guided setup, and UniFi-specific safety guidance. It should be treated as a
convenience layer over native MCP rather than a transport requirement.

From the project that should use UniFi Network, register a local server using a
credential file rather than putting the password itself on the command line:

```bash
opencode mcp add unifi-network \
  --env UNIFI_NETWORK_HOST=controller.example.local \
  --env UNIFI_NETWORK_USERNAME=unifi-mcp \
  --env 'UNIFI_NETWORK_PASSWORD_FILE=/absolute/path/to/password-file' \
  --env UNIFI_NETWORK_TOOL_PERMISSION_MODE=confirm \
  --env UNIFI_POLICY_NETWORK_CREATE=false \
  --env UNIFI_POLICY_NETWORK_UPDATE=false \
  --env UNIFI_POLICY_NETWORK_DELETE=false \
  -- uvx --python-preference system unifi-network-mcp@latest

opencode mcp list
```

`opencode mcp add` writes to OpenCode's user-level configuration, so this server
will be available across projects. There is no `--global` switch. If the user
wants project-only access, add the equivalent local MCP entry to that project's
`opencode.json` instead. Substitute `unifi-protect-mcp` and
`UNIFI_PROTECT_*`, or `unifi-access-mcp` and `UNIFI_ACCESS_*`, for the other
products. OpenCode's [current MCP documentation](https://opencode.ai/v2/docs/mcp-servers)
is the source of truth for its configuration schema and rollback commands.

An OpenCode npm plugin is worth a small packaging prototype after the native
flow is proven. Keep it only if it reduces setup steps while preserving secure
credential entry, product selection, and the normal OpenCode MCP lifecycle.

## Antigravity

Antigravity CLI and IDE support MCP servers, Agent Skills, and plugins. A plugin
can package the MCP definition and existing skills together, making it a better
long-term fit than the retired Gemini extension path. Antigravity discovers
workspace skills from `.agents/skills/` and stores workspace MCP servers in
`.agents/mcp_config.json`.

The current UniFi plugin bundles are not Antigravity plugins yet. Until a clean
install validates its secret-entry and plugin-root behavior, use Antigravity's
MCP management UI or current configuration documentation to add a local stdio
server with the `uvx` command and the selected package from the table below.

## Devin Local in Devin Desktop and Devin CLI

Devin Desktop is the current name for Windsurf. Its primary Devin Local agent
shares the Devin CLI harness and MCP configuration, so the `devin mcp` flow
below configures both Devin Local and Devin CLI. Cascade remains available as a
separate legacy agent and does not use this registration path.

Register the server first, without putting credentials on the command line:

```bash
devin mcp add unifi-network -- \
  uvx --python-preference system unifi-network-mcp@latest
```

Then add product variables to `.devin/mcp_config.local.json`, which Devin keeps
local and gitignored. Prefer a UniFi `*_PASSWORD_FILE` or `*_PASSWORD_COMMAND`
provider, and set the product's server-level `CREATE`, `UPDATE`, and `DELETE`
policy gates to `false` unless the user opted into writes. Verify with
`devin mcp list`; roll back with `devin mcp remove unifi-network`.

See Devin's [current MCP configuration](https://docs.devin.ai/cli/extensibility/mcp/configuration).

If the user explicitly uses Cascade, open **Devin Settings > Cascade > MCP
Servers** and add the local stdio server there, or edit Cascade's raw
`mcp_config.json`. Follow the separate [Cascade MCP guide](https://docs.devin.ai/desktop/cascade/mcp)
instead of running the Devin Local/CLI commands above.

## Cursor and other native MCP clients

Cursor has native MCP support, but its current secret-entry flow and planned
marketplace packaging need a clean-profile validation before this project
publishes copy-and-paste configuration. For now:

1. Open the client's current MCP management UI or official MCP documentation.
2. Add a local stdio server whose command is `uvx`.
3. Use arguments `--python-preference`, `system`, and the selected package name
   ending in `@latest`.
4. Add the product-specific host, username, and indirect credential variables
   through the client's secure configuration flow.
5. Set the product's server-level `CREATE`, `UPDATE`, and `DELETE` policy gates
   to `false` unless the user opted into writes.
6. Reload the client and perform the authentication-appropriate read-only
   verification described above.

Current first-party references:

- [Antigravity plugins](https://antigravity.google/docs/plugins)
- [Migrating Gemini CLI configuration to Antigravity](https://antigravity.google/docs/cli/gcli-migration/)
- [Cursor MCP documentation](https://docs.cursor.com/context/model-context-protocol)

## Server names and variables

| Product | MCP name | Package | Minimum connection variables |
|---|---|---|---|
| Network | `unifi-network` | `unifi-network-mcp@latest` | `UNIFI_NETWORK_HOST`, plus an API-key provider for limited inventory or username and a password provider for session tools |
| Protect | `unifi-protect` | `unifi-protect-mcp@latest` | `UNIFI_PROTECT_HOST`, `UNIFI_PROTECT_USERNAME`, one `UNIFI_PROTECT_PASSWORD*` provider |
| Access | `unifi-access` | `unifi-access-mcp@latest` | `UNIFI_ACCESS_HOST`, plus a supported local credential or API-key provider |

See each product's configuration documentation for ports, sites, API-key
limitations, TLS verification, and policy gates:

- [Network configuration](../apps/network/docs/configuration.md)
- [Protect configuration](../apps/protect/docs/configuration.md)
- [Access configuration](../apps/access/docs/configuration.md)

## Verification checklist

An installation is complete only when all applicable checks pass:

- The selected client reports the MCP server as connected.
- Tool discovery shows the chosen UniFi product and no unwanted products.
- A read-only request supported by the configured authentication path succeeds.
  For Network API-key-only setup, use device, client, network, or WLAN inventory;
  use system information or health when session credentials are available.
- With the default read-only gates, a mutation request is denied by policy. If
  the user opted into that action, it produces a preview and asks for
  confirmation by default.
- No secret was printed in a command log, chat transcript, or committed file.
