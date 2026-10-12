# Upgrading the UniFi plugins

This page tells existing plugin users what to do when a new plugin release
lands. Install steps are in the [agent install guide](agent-install.md);
prerequisites and verification status are in the
[plugin support matrix](plugin-support.md).

## 1.0.0

Every UniFi plugin (`unifi-network`, `unifi-protect`, `unifi-access` and the
unlisted `cross-product` bundle) moves to version 1.0.0. The servers they start
do not change: `unifi-network-mcp` 0.37.0, `unifi-protect-mcp` 0.8.17 and
`unifi-access-mcp` 0.6.12.

What changes:

- **Plugin versions are independent of server versions.** Before 1.0.0 a
  plugin's version matched the server it pinned. From now on the plugin version
  describes what the plugin ships, and the server pin moves separately.
- **Claude Code reads settings from plugin options (breaking).** The plugin's
  servers no longer read `.claude/settings.local.json` in your project. Each
  plugin keeps its settings as plugin options instead. See
  [Claude Code](#claude-code).
- **Credentials stay out of chat and command arguments.** Setup no longer asks
  you to type a password or API key into the conversation, and the setup scripts
  refuse a raw password or API key as a command argument. See
  [Moving a raw secret to a provider](#moving-a-raw-secret-to-a-provider).
- **Codex setup follows plugin upgrades.** The MCP entry that Codex setup saves
  starts the server version the installed plugin pins, so you no longer refresh
  it after each upgrade. Convert an entry from an earlier version once; see
  [Codex](#codex).
- **Setup is transactional.** Setup validates every change before writing it and
  replaces the client configuration atomically. If anything fails, the previous
  configuration stays in place and usable.
- **Skills report their coverage.** Each skill states which servers it requires
  and which are optional, and its reports include a Coverage and Limitations
  section. A skill gives no all-clear from data that was unavailable, partial or
  capped, and it does not treat timing or similar names as proof of identity or
  cause. Stale tool names and parameters were corrected.

The setup helpers (`check-prereqs`, `set-env`) need Python 3.11 or newer on
`PATH`, or `uv`, which then supplies a managed Python.

### Claude Code

Auto-update is off by default for this marketplace. If you turned it on
(`/plugin`, then **Marketplaces**, then `unifi-plugins`, then **Enable
auto-update**), Claude Code installs 1.0.0 in the background a few minutes into
a session and shows `Plugins updated: … Run /reload-plugins to apply`. Start a
new session instead of reloading, so you see the notice below; if you already
reloaded, ask Claude to run the plugin's setup skill, which finds the old
settings and offers the migration. Otherwise, update yourself:

```bash
claude plugin marketplace update unifi-plugins
claude plugin update unifi-network@unifi-plugins
```

Repeat the second command for `unifi-protect@unifi-plugins` and
`unifi-access@unifi-plugins` if you have them. You can also use `/plugin`, then
**Installed**, then **Update now**.

Then start a new Claude Code session in the project. Don't use
`/reload-plugins` for this step: it moves a running session to the new version
without the notice, which appears only when a session starts, and the servers
then fail until you migrate.

#### Move your settings into plugin options

Plugin options are saved once for your user and apply in every project. A
password or API key entered as an option is stored in the system keychain;
everything else, including file and command provider paths, is stored in your
user `settings.json`.

> **More than one project?** A project's own settings are no longer read. Once
> you migrate one project, every other project uses those options, which may
> name a different controller. In any project that still holds its own
> `UNIFI_<PRODUCT>_*` keys, the session-start notice says so. There, either
> migrate with `--replace`, which makes that project's settings the options for
> every project, or remove the leftover keys to keep the saved options. Plugin
> options cannot name a different controller per project.

If an earlier version configured this project, the first new session shows a
notice like this:

> UniFi Network plugin: this project's .claude/settings.local.json still holds
> UNIFI_NETWORK_* settings, which this plugin version no longer reads, so the
> UniFi Network server starts unconfigured. Ask Claude to run the
> unifi-network-setup migration (set-env.sh --target claude --migrate), then run
> /reload-plugins, then /mcp reconnect plugin:unifi-network:unifi-network if
> /mcp still shows the server as failed.

Claude also offers to run the migration when you next ask about the plugin.
Until you migrate, the server either fails to start (`/mcp` shows
`plugin:unifi-network:unifi-network` as failed, because no controller host is
configured) or, when the project file also holds a shared `UNIFI_HOST`, connects
with the shared `UNIFI_*` settings, which may name a different controller. In
that case the port is the plugin option's default, 443, not a shared
`UNIFI_PORT`.

To migrate, ask Claude to run the `unifi-network-setup` migration, or run the
plugin's script yourself from the project directory:

```bash
bash <plugin-root>/scripts/set-env.sh --target claude --migrate
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target claude -Migrate`.
`<plugin-root>` is the installed plugin's directory; Claude Code keeps it under
`~/.claude/plugins/cache/unifi-plugins/<plugin>/<version>/`.

The migration copies this plugin's settings into its options, then removes only
this plugin's keys from `.claude/settings.local.json`. If options saved from
another project already hold a different host, username, port or site, it
refuses, names those variables and changes nothing; rerun with `--replace`
(`-Replace` on Windows) to make this project's settings the options for every
project. Its output names variables only, never values:

- **Migrated:** settings now held as options.
- **Not migrated:** this plugin's settings that have no Claude Code option,
  such as per-category policy overrides. A leftover `UNIFI_AUTO_CONFIRM` is
  named too; it has no option, so use the permission mode instead.
- **Shared settings kept:** shared `UNIFI_*` keys stay in the project file,
  because setup cannot prove that another plugin or a standalone server no
  longer uses them. Once no UniFi plugin keys remain, `check-prereqs` names the
  shared keys still there. Claude Code exports them into every process it
  starts in that project, shell commands and MCP servers included, so remove
  them by hand once nothing else needs them.

Then, in the session that was already open, run `/reload-plugins`, and run
`/mcp reconnect plugin:unifi-network:unifi-network` if `/mcp` still shows the
server as failed. A new session also loads the migrated options. Repeat the
migration for each UniFi plugin you use.

Claude Code skips a server that failed to start in the last 15 minutes while
its settings are unchanged: a new session and `/reload-plugins` both leave it
skipped (`/mcp` reports "recent failure cached"), and `/mcp reconnect` retries
it. With options unset, a failure in one project makes the server skip in your
other projects too. Saving new options, by migration or setup, counts as a
change, so `/reload-plugins` or a new session starts the server again.

If the project has no earlier settings, or you are configuring from scratch, run
the setup skill (`/unifi-network:unifi-network-setup`) or edit the options with
`/plugin`, then the plugin, then **Configure options**.

#### Per-category policy overrides

Besides the connection settings, Claude Code options hold only the server-level
create, update and delete gates, the permission mode and the tool registration
mode. Overrides such as
`UNIFI_POLICY_NETWORK_FIREWALL_POLICIES_UPDATE` have no option, and setup
refuses them. Instead, allow the action server-wide and keep the permission
mode at `confirm`, so every change is previewed and you can decline the ones
you do not want; or keep the action off. Codex and OpenClaw still accept
per-category overrides.

#### Confirm the result

```bash
claude mcp list
```

The plugin's server should be listed as connected. In a session, `/mcp` shows
the same, and the notice no longer appears.

### Codex

Codex upgrades its plugin marketplaces at the start of every session and
reinstalls any plugin whose version changed, so 1.0.0 arrives on its own. To
upgrade without starting a session, run:

```bash
codex plugin marketplace upgrade
```

Setup saved a separate MCP entry, holding your settings, that takes precedence
over the plugin's bundled server. From 1.0.0 that entry starts the server
version the installed plugin pins, so later plugin upgrades update the server
with no setup. Codex installs an upgrade in the background as a session starts;
that session keeps the server it already started, and the next one runs the new
version. An entry saved by an earlier plugin version pins its server
package instead, and keeps it through upgrades. 1.0.0 keeps the same server
versions, so nothing changes now; convert the entry once so it follows later
releases:

```bash
bash <plugin-root>/scripts/set-env.sh --target codex --refresh
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
`<plugin-root>` is the installed plugin, for example
`~/.codex/plugins/cache/unifi-plugins/unifi-network/1.0.0`. You can also ask
Codex to run the plugin's setup skill: its prerequisite check names a pinned
entry and the refresh that converts it. Refresh keeps your saved settings and
provider references, asks for no credentials, and prints the server package the
plugin pins. Restart Codex afterwards. You need it once per entry, not after
every upgrade. If there is no saved MCP entry, run ordinary setup instead. Your
saved Codex settings carry over, including per-category policy overrides.

The converted entry starts through `uv`, which is installed with `uvx`. If you
uninstall the plugin, the entry fails to start and names the missing
installation; reinstall the plugin and refresh again, or remove the entry with
`codex mcp remove unifi-network`.

### OpenClaw

```bash
openclaw plugins update unifi-network
openclaw gateway restart
```

OpenClaw asks you to accept the plugin's capabilities before it updates
(`Accept these capabilities and update "unifi-network"? [y/N]`). In a script,
or anywhere without a terminal, add `--accept-capabilities`; without it the
update is refused. Use `openclaw plugins update --all` to update every plugin.
OpenClaw tracks commits rather than versions, and changes nothing until you run
this command. The MCP entry that setup writes pins the server package; 1.0.0
keeps the same server versions, so that entry needs no change.

### Moving a raw secret to a provider

If you typed a password or API key into an earlier setup, or passed it as a
`KEY=VALUE` argument, switch to a provider. The scripts now refuse a raw
password or API key on the command line.

1. Outside the chat, put the secret in a file only you can read (`chmod 600`),
   or choose a command that prints it without prompting, such as a keychain,
   `pass` or 1Password helper. The [credential provider guide](credential-providers.md)
   has examples.
2. Ask the setup skill to use that provider, or run setup with the reference.
   A provider reference is a path or a command, not a secret:

   ```bash
   bash <plugin-root>/scripts/set-env.sh --target <claude|codex|openclaw> \
     'UNIFI_NETWORK_PASSWORD_FILE=/absolute/path/to/password-file'
   ```

   Use `UNIFI_NETWORK_PASSWORD_COMMAND`, `UNIFI_NETWORK_API_KEY_FILE` or
   `UNIFI_NETWORK_API_KEY_COMMAND` the same way, with the matching
   `UNIFI_PROTECT_*` or `UNIFI_ACCESS_*` names for the other plugins.

Selecting a spelling removes the other saved spellings of that secret, so the
old raw value is removed in the same change. In Claude Code a migrated raw
password or API key lands in the system keychain; the steps above replace it
with a provider. You can also enter it in the masked password or API key field
under `/plugin`, then the plugin, then **Configure options**, which keeps it in
the keychain.

To supply a raw value deliberately, pipe a JSON patch from a private file:
`set-env.sh --target <target> --input-json < private.json`
(`set-env.ps1 -Target <target> -InputJson` on Windows). Never put the secret in
chat, a command argument or your shell history.

### Holding off and rollback

What happens when a release lands, and how to stay on your current plugins:

- **Claude Code:** nothing, unless you turned on auto-update for this
  marketplace; then it installs the release in the background during a
  session. To hold off, leave auto-update off (turn it off under `/plugin`,
  then **Marketplaces**, if you enabled it) and don't run the update commands.
- **Codex:** installs the release at the start of your next session, together
  with the server version it pins. There is no switch to hold off. An entry
  saved by setup before 1.0.0 keeps its pinned server until you run `--refresh`
  once; see [Codex](#codex).
- **OpenClaw:** nothing until you run `openclaw plugins update`. To hold off,
  don't run it.

If a release breaks something for you, open an issue. A bad plugin release is
rolled back by publishing a higher version with the fix or the revert, which
you install with the same update commands as any other release.

Hermes Agent cannot load the current plugin layout and is not supported.

### Known limits

- The Claude Code session-start notice runs `sh` (Git Bash on Windows). Without
  it you see no notice; `check-prereqs` and setup still name leftover settings.
- If Claude Code reports a keychain write but does not keep it, setup restores
  the previous non-secret options and says so, but cannot restore the previous
  keychain value. Re-enter it, or switch to a file or command provider.
- The `cross-product` bundle stays unlisted in both marketplaces. Its
  merged-timeline workflows need the relay's `unifi_location_timeline` tool,
  which local servers do not provide. See
  [Cross-Product Capabilities](cross-product.md).
