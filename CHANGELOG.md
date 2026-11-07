# Changelog

User-visible changes to the UniFi MCP plugins (`unifi-network`, `unifi-protect`,
`unifi-access` and `unifi-intelligence`), newest first. Each plugin has its own
version. A release that only moves a plugin's server pin links to that server's
release notes. Every server, the API, the relay and the worker publish their own
notes on [GitHub Releases](https://github.com/sirkirby/unifi-mcp/releases).

Read the [plugin upgrade guide](docs/plugin-upgrade.md) before updating an
existing install.

<!-- New entries go below this line, newest first; the release writeback inserts here. -->

## 2026-11-06 — unifi-network 1.9.2

- `firewall-auditor` can be installed by agents that scan skills before installing. The audit-history step no longer pipes JSON into an interpreter, and the DNS-redirect test uses named placeholders (`UNUSED_IP` for a documentation-range address nothing answers, `SYNTHETIC_A_RECORD` for the synthetic answer) instead of literal addresses.
- The same step no longer interpolates the score JSON into an inline Python program. That removes a quoting hazard the scanner classifies as obfuscation; a history file that exists but cannot be parsed still fails loudly instead of being silently replaced.


## 2026-11-05 — unifi-network 1.9.1

- The Network skill now says port override tools merge by port: send only the ports to change, and clear a port's override with `remove_port_idxs`. It no longer tells agents to send the full array.
- It also explains that fixed IP reservations land on the network that holds the address (or `network_id`), and how to release a fixed IP while a local DNS record is on.


## 2026-11-06 — unifi-network 1.9.0

- Pins `unifi-network-mcp` [0.45.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.45.0).


## 2026-11-05 — unifi-network 1.8.1

- Pins `unifi-network-mcp` [0.44.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.44.1).


## 2026-11-05 — unifi-network 1.8.0, unifi-protect 1.5.0, unifi-access 1.4.0

- Claude Code: a new **Certificate fingerprint** option pins the console's certificate, so the server checks the console's identity even on its factory self-signed certificate. Access adds **API port certificate fingerprint** for the API key port, which presents a different certificate. A pin also stops the startup warning about unchecked connections. See [TLS verification](docs/tls-verification.md).
- Setup, in every client, now offers to read and set the fingerprint.
- Claude Code: if you set `UNIFI_<PRODUCT>_SSL_FINGERPRINT` in Claude Code's environment, the plugin's option now takes its place, and an empty option leaves the certificate unchecked. A session-start notice names the variable until you save it as the option.


## 2026-11-03 — unifi-network 1.7.0, unifi-protect 1.4.0, unifi-access 1.3.0

- Pins `unifi-network-mcp` [0.44.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.44.0), `unifi-protect-mcp` [0.12.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.12.0) and `unifi-access-mcp` [0.9.0](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.9.0).


## 2026-11-02 — unifi-network 1.6.2

- Pins `unifi-network-mcp` [0.43.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.43.2).


## 2026-10-30 — unifi-network 1.6.1

- Pins `unifi-network-mcp` [0.43.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.43.1).


## 2026-10-30 — unifi-network 1.6.0

- Pins `unifi-network-mcp` [0.43.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.43.0).


## 2026-10-29 — unifi-access 1.2.0

- Pins `unifi-access-mcp` [0.8.0](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.8.0).


## 2026-10-29 — unifi-network 1.5.0, unifi-protect 1.3.0

- Pins `unifi-network-mcp` [0.42.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.42.0) and `unifi-protect-mcp` [0.11.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.11.0).


## 2026-10-28 — unifi-access 1.1.0

- Pins `unifi-access-mcp` [0.7.0](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.7.0).


## 2026-10-28 — unifi-network 1.4.0, unifi-protect 1.2.0

- Pins `unifi-network-mcp` [0.41.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.41.0) and `unifi-protect-mcp` [0.10.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.10.0).


## 2026-10-24 — unifi-network 1.3.0

- Pins `unifi-network-mcp` [0.40.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.40.0).


## 2026-10-23 — unifi-network 1.2.6, unifi-protect 1.1.10, unifi-access 1.0.8, unifi-intelligence 1.0.1

- Each plugin now ships its own icon, which Codex shows in its plugin list and composer and Anthropic's plugin directory uses for a listing. Nothing else changes.


## 2026-10-22 — unifi-network 1.2.5, unifi-protect 1.1.9, unifi-access 1.0.7

- Claude Code setup no longer risks losing a password or API key held in the system keychain when you switch it to a `_FILE` or `_COMMAND` provider on a newer Claude Code release. Setup now saves and verifies the new provider before it clears the secret, rolls back if Claude Code keeps the secret, and keeps a saved credential if a step fails or is interrupted; rerunning setup finishes the switch. On those releases, switch one credential per setup run.


## 2026-10-22 — unifi-access 1.0.6

- Pins `unifi-access-mcp` [0.6.17](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.6.17).


## 2026-10-22 — unifi-protect 1.1.8

- Pins `unifi-protect-mcp` [0.9.5](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.9.5).


## 2026-10-22 — unifi-network 1.2.4

- Pins `unifi-network-mcp` [0.39.3](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.39.3).


## 2026-10-22 — unifi-network 1.2.3

- Pins `unifi-network-mcp` [0.39.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.39.2).


## 2026-10-22 — unifi-network 1.2.2, unifi-protect 1.1.7, unifi-access 1.0.5

- The Claude Code prerequisite check no longer fails when the project's `.claude/settings.local.json` has no `env` block, for example when it holds only permissions. It used to report a generic uv or CLI problem.

## 2026-10-20 — unifi-network 1.2.1

- Pins `unifi-network-mcp` [0.39.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.39.1).


## 2026-10-18 — unifi-network 1.2.0

- Pins `unifi-network-mcp` [0.39.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.39.0).


## 2026-10-18 — unifi-network 1.1.9

- The firewall auditor no longer reports a predefined UniFi system policy as shadowed (HYG-05) when a user policy deliberately overrides it, such as blocking guest DNS to internal resolvers. It lists those overrides in the report without changing the score.

## 2026-10-18 — unifi-network 1.1.8

- Pins `unifi-network-mcp` [0.38.6](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.6).


## 2026-10-17 — unifi-access 1.0.4

- Pins `unifi-access-mcp` [0.6.16](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.6.16).


## 2026-10-17 — unifi-protect 1.1.6

- Pins `unifi-protect-mcp` [0.9.4](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.9.4).


## 2026-10-17 — unifi-network 1.1.7

- Pins `unifi-network-mcp` [0.38.5](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.5).


## 2026-10-17 — unifi-network 1.1.6

- Pins `unifi-network-mcp` [0.38.4](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.4).


## 2026-10-15 — unifi-protect 1.1.5

- Pins `unifi-protect-mcp` [0.9.3](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.9.3).


## 2026-10-15 — unifi-network 1.1.5

- Pins `unifi-network-mcp` [0.38.3](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.3).


## 2026-10-14 — unifi-network 1.1.4, unifi-protect 1.1.4, unifi-access 1.0.3

- Pins `unifi-network-mcp` [0.38.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.38.2), `unifi-protect-mcp` [0.9.2](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.9.2) and `unifi-access-mcp` [0.6.15](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.6.15).


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
