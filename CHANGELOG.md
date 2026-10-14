# Changelog

User-visible changes to the UniFi MCP plugins (`unifi-network`, `unifi-protect`,
`unifi-access` and `unifi-intelligence`), newest first. Each plugin has its own
version. A release that only moves a plugin's server pin links to that server's
release notes. Every server, the API, the relay and the worker publish their own
notes on [GitHub Releases](https://github.com/sirkirby/unifi-mcp/releases).

Read the [plugin upgrade guide](docs/plugin-upgrade.md) before updating an
existing install.

<!-- New entries go below this line, newest first; the release writeback inserts here. -->

## 2026-10-13 — unifi-network 1.1.3, unifi-protect 1.1.3, unifi-access 1.0.2

- **Codex has the UniFi tools in its first session after setup.** Codex setup and
  `--refresh` start the plugin's server once, in setup mode with no credentials, so
  Codex doesn't hit a server's slow first launch. A failed warm-up prints a notice
  and never fails setup.

## 2026-10-13 — unifi-intelligence 1.0.0

- **A new plugin, listed in the Claude Code and Codex marketplaces.** It ships
  skills only: Incident Investigation, Security Patrol and Visitor Audit. It
  replaces the unlisted `cross-product` bundle.
- **It needs the Network and Protect plugins.** Claude Code installs
  `unifi-network` and `unifi-protect` with it; on Codex and OpenClaw, install and
  set up those two first.
- **Incident Investigation runs locally.** It investigates one Network device
  incident with Protect camera context from the servers' read-only incident
  evidence tools, and cites every claim.
- **Security Patrol and Visitor Audit need the cloud worker**, which provides the
  merged location timeline through a connected relay.

## 2026-10-13 — unifi-network 1.1.2, unifi-protect 1.1.2

- Pins `unifi-network-mcp` [0.38.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.1)
  and `unifi-protect-mcp` [0.9.1](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.9.1),
  which list the camera mapping lookups directly in lazy mode.

## 2026-10-13 — unifi-network 1.1.1, unifi-protect 1.1.1

- The skill references list the incident evidence tools. In 1.1.0 they gave the
  new tool counts without listing those tools.

## 2026-10-13 — unifi-network 1.1.0, unifi-protect 1.1.0

- Pins `unifi-network-mcp` [0.38.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.0)
  and `unifi-protect-mcp` [0.9.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.9.0),
  which add the bounded read-only incident evidence tools.

## 2026-10-12 — unifi-network 1.0.1, unifi-protect 1.0.1, unifi-access 1.0.1

- **A down controller no longer fails the plugin.** The servers answer the client
  before the controller connects. While it is unreachable, tools say the server is
  still connecting or cannot reach the controller, and recover on their own once it
  is back.
- **Connection errors name the real cause.** A network failure says the controller
  is unreachable instead of asking you to check your credentials.
- **Claude Code setup protects a keychain-held secret.** Claude Code cannot clear a
  password or API key it holds in the system keychain, so setup refuses, before
  writing, a change that would clear one. It says how to switch: uninstall and
  reinstall the plugin, then run setup with the provider and the options it lists.
- Pins `unifi-network-mcp` 0.37.2, `unifi-protect-mcp` 0.8.19 and
  `unifi-access-mcp` 0.6.14.

## 2026-10-12 — unifi-network 1.0.0, unifi-protect 1.0.0, unifi-access 1.0.0

- **Claude Code keeps settings as plugin options.** The plugins no longer read the
  project's `.claude/settings.local.json`; passwords and API keys entered as options
  go to the system keychain. Existing users run the setup migration once per plugin
  (`set-env.sh --target claude --migrate`). Options apply in every project, so a
  project's own settings stop being used once another project is migrated; the
  upgrade guide covers several projects.
- **No secrets in chat or command arguments.** Setup uses a password or API-key
  file or command provider, and every configuration write is validated and atomic.
- **Plugin versions are independent of server versions.** Before 1.0.0, each
  plugin's version followed its server's.
- **Server improvements.** The pinned servers (`unifi-network-mcp` 0.37.1,
  `unifi-protect-mcp` 0.8.18, `unifi-access-mcp` 0.6.13) reconnect Access and
  Protect after a failed start, read Codex's settings file, and start in setup mode
  with a read-only `*_setup_status` tool instead of exiting when unconfigured.
- **Skills report their coverage** and give no all-clear from missing, partial or
  capped data.
