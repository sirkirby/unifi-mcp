# Changelog

User-visible changes to the UniFi MCP plugins (`unifi-network`, `unifi-protect`,
`unifi-access`, `unifi-sitemanager`, `unifi-drive` and `unifi-intelligence`), newest first. Each plugin has its own
version. A release that only moves a plugin's server pin links to that server's
release notes. Every server, the API, the relay and the worker publish their own
notes on [GitHub Releases](https://github.com/sirkirby/unifi-mcp/releases).

Read the [plugin upgrade guide](docs/plugin-upgrade.md) before updating an
existing install.

<!-- New entries go below this line, newest first; the release writeback inserts here. -->

## 2026-11-28 — unifi-network 1.14.8, unifi-access 1.5.4

- Pins `unifi-network-mcp` [0.50.4](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.50.4) and `unifi-access-mcp` [0.10.2](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.10.2).


## 2026-11-25 — unifi-network 1.14.7

- The network skill's tool reference explains how to reorder MAC ACL rules: order is each rule's `acl_index` (lower is evaluated first), changed with `unifi_update_acl_rule`.


## 2026-11-25 — unifi-drive 1.0.0

- New plugin for the UniFi Drive server on a UniFi NAS: storage pools, RAID state, disk SMART health and shared drives, plus preview-first writes that turn SMB, NFS or Time Machine on or off and add, change or remove NFS clients. It pins `unifi-drive-mcp` [0.1.0](https://github.com/sirkirby/unifi-mcp/releases/tag/drive/v0.1.0).
- Setup takes the NAS's own host, a local account on the NAS and one password source. It never reuses the gateway's host or shared console credentials, and every write stays off until you allow it.


## 2026-11-25 — unifi-network 1.14.6, unifi-protect 1.8.3, unifi-access 1.5.3, unifi-sitemanager 1.1.3

- Setup treats UniFi Drive settings found in an older project settings file as another plugin's settings. They are never copied into this plugin's settings or offered for migration. Nothing else about setup changes.


## 2026-11-24 — unifi-network 1.14.5, unifi-protect 1.8.2, unifi-access 1.5.2, unifi-sitemanager 1.1.2

- Pins `unifi-network-mcp` [0.50.3](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.50.3), `unifi-protect-mcp` [0.15.1](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.15.1), `unifi-access-mcp` [0.10.1](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.10.1) and `unifi-sitemanager-mcp` [0.2.1](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.2.1).


## 2026-11-22 — unifi-network 1.14.4

- Pins `unifi-network-mcp` [0.50.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.50.2).


## 2026-11-21 — unifi-network 1.14.3

- `unifi-network`: the firewall manager skill says a policy's `description` can now be changed (an empty string clears it), and that `unifi_update_firewall_policy` refuses unknown top-level fields by name instead of dropping them, as the pinned server does.

## 2026-11-21 — unifi-network 1.14.2

- Pins `unifi-network-mcp` [0.50.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.50.1).


## 2026-11-21 — unifi-network 1.14.1, unifi-protect 1.8.1, unifi-access 1.5.1, unifi-sitemanager 1.1.1

- The skills describe batches as the pinned servers run them: writes in a batch run one at a time in the order you submit them, reads run side by side up to a limit, and the new `*_batch_cancel` tool withdraws jobs that have not started. Batch status now shows `queued` (with the job's place in line) and `cancelled`.
- `unifi-network`: the firewall manager skill now covers reordering policies with a username and password (`unifi_get_firewall_policy_order` and `unifi_set_firewall_policy_order`), not only with an API key, and names `UNIFI_NETWORK_API_KEY` first. It also says that changing a policy's source or destination target clears the old IP, address-group and network selections, so they cannot come back if you switch the target back later. The skill explains that a call refused because the controller is busy changed nothing and can be retried.

## 2026-11-21 — unifi-network 1.14.0, unifi-protect 1.8.0, unifi-access 1.5.0, unifi-sitemanager 1.1.0

- Pins `unifi-network-mcp` [0.50.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.50.0), `unifi-protect-mcp` [0.15.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.15.0), `unifi-access-mcp` [0.10.0](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.10.0) and `unifi-sitemanager-mcp` [0.2.0](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.2.0).


## 2026-11-20 — unifi-network 1.13.2, unifi-protect 1.7.3, unifi-access 1.4.6

- Pins `unifi-network-mcp` [0.49.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.49.2), `unifi-protect-mcp` [0.14.2](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.14.2) and `unifi-access-mcp` [0.9.4](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.9.4).


## 2026-11-20 — unifi-network 1.13.1

- Pins `unifi-network-mcp` [0.49.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.49.1).


## 2026-11-20 — unifi-network 1.13.0

- Pins `unifi-network-mcp` [0.49.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.49.0).


## 2026-11-20 — unifi-network 1.12.4, unifi-protect 1.7.2, unifi-access 1.4.5, unifi-sitemanager 1.0.5

- Pins `unifi-network-mcp` [0.48.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.48.2), `unifi-protect-mcp` [0.14.1](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.14.1), `unifi-access-mcp` [0.9.3](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.9.3) and `unifi-sitemanager-mcp` [0.1.4](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.1.4).


## 2026-11-20 — unifi-network 1.12.3, unifi-protect 1.7.1, unifi-access 1.4.4, unifi-sitemanager 1.0.4

- The Network, Protect and Access setup skills say a server whose host is not the `UNIFI_HOST` console needs its own username and password (or API key): newer server releases ignore the shared ones there and log which variable they ignored. `--migrate` copies shared credentials from project settings only when the plugin's host after migration is the project's `UNIFI_HOST`, and names any it leaves behind.
- unifi-sitemanager ships the same setup helper; its setup is unchanged.


## 2026-11-20 — unifi-protect 1.7.0

- Pins `unifi-protect-mcp` [0.14.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.14.0).


## 2026-11-19 — unifi-network 1.12.2

- Pins `unifi-network-mcp` [0.48.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.48.1).


## 2026-11-19 — unifi-network 1.12.1

- The setup skill describes API-key-only Network access as verified reads (inventory, settings, system information and rule lists); mutations, events, statistics reports and full client details still need a username and password.


## 2026-11-17 — unifi-network 1.12.0

- Pins `unifi-network-mcp` [0.48.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.48.0).


## 2026-11-17 — unifi-network 1.11.1

- Pins `unifi-network-mcp` [0.47.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.47.1).


## 2026-11-17 — unifi-network 1.11.0, unifi-protect 1.6.3, unifi-access 1.4.3, unifi-sitemanager 1.0.3

- Pins `unifi-network-mcp` [0.47.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.47.0), `unifi-protect-mcp` [0.13.2](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.13.2), `unifi-access-mcp` [0.9.2](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.9.2) and `unifi-sitemanager-mcp` [0.1.3](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.1.3).


## 2026-11-15 — unifi-network 1.10.0

- Pins `unifi-network-mcp` [0.46.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.46.0).


## 2026-11-15 — unifi-network 1.9.6

- The firewall-manager skill looks up DPI category IDs with `unifi_list_dpi_categories`; `unifi_get_dpi_stats` returns restriction rules, not categories. The firewall-auditor skill and the tool reference describe `unifi_get_dpi_stats` the same way.


## 2026-11-14 — unifi-network 1.9.5, unifi-protect 1.6.2, unifi-access 1.4.2, unifi-sitemanager 1.0.2

- Pins `unifi-network-mcp` [0.45.2](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.45.2), `unifi-protect-mcp` [0.13.1](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.13.1), `unifi-access-mcp` [0.9.1](https://github.com/sirkirby/unifi-mcp/releases/tag/access/v0.9.1) and `unifi-sitemanager-mcp` [0.1.2](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.1.2).


## 2026-11-13 — unifi-sitemanager 1.0.1

- Pins `unifi-sitemanager-mcp` [0.1.1](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.1.1).


## 2026-11-13 — unifi-sitemanager 1.0.0

- New plugin for the read-only Site Manager server: hosts, sites, devices, ISP metrics and SD-WAN configurations across every console on a Ubiquiti account. It pins `unifi-sitemanager-mcp` [0.1.0](https://github.com/sirkirby/unifi-mcp/releases/tag/sitemanager/v0.1.0).
- Setup takes one Site Manager API key, or a file or command that provides it. It never asks for a console host, username or password, and it refuses to reuse a console API key.


## 2026-11-13 — unifi-network 1.9.4, unifi-protect 1.6.1, unifi-access 1.4.1

- Setup treats a Site Manager key found in an older project settings file as another plugin's setting. It is never copied into this plugin's settings or offered for migration. Nothing else about setup changes.


## 2026-11-12 — unifi-network 1.9.3

- Pins `unifi-network-mcp` [0.45.1](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.45.1).


## 2026-11-12 — unifi-protect 1.6.0

- Pins `unifi-protect-mcp` [0.13.0](https://github.com/sirkirby/unifi-mcp/releases/tag/protect/v0.13.0).


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
