# Upgrading the UniFi plugins

This page tells existing plugin users what to do when a new plugin release
lands. Install steps are in the [agent install guide](agent-install.md);
prerequisites and verification status are in the
[plugin support matrix](plugin-support.md).

## 1.0.0

Every UniFi plugin (`unifi-network`, `unifi-protect`, `unifi-access` and the
unlisted `cross-product` bundle) moves to version 1.0.0. The plugins now start
newer server releases: `unifi-network-mcp` 0.37.1, `unifi-protect-mcp` 0.8.18
and `unifi-access-mcp` 0.6.13. They bring three things:

- **Access and Protect reconnect.** If the controller was down when the server
  started, or the first connection was rejected, the Access and Protect servers
  reconnect on their own before the next tool call instead of staying unusable
  until the client restarts the server.
- **A settings file for Codex and OpenClaw.** The servers read the private
  settings file that Codex and OpenClaw setup write, named by `UNIFI_SETTINGS_FILE`. Reading it is implemented
  in `unifi-mcp-shared` 0.6.28, and the 1.0.0 plugins pin server releases that
  require it.
- **Setup mode instead of a silent failure.** With no controller host
  configured, a server answers the client and offers only a read-only
  `unifi_setup_status`, `protect_setup_status` or `access_setup_status` tool that
  says how to configure it. Earlier releases exited, and the client showed only
  a failed server.

What else changes:

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
- **Codex runs the plugin's own server.** Codex setup now saves your settings in
  a private file that the plugin's bundled server reads, instead of a separate
  `config.toml` entry, so plugin upgrades upgrade the server. If you ran Codex
  setup before 1.0.0, run one command once; see [Codex](#codex).
- **OpenClaw runs the plugin's own server too.** OpenClaw setup writes the same
  settings file and no `openclaw.json` entry. If you ran OpenClaw setup before
  1.0.0, run one command once; see [OpenClaw](#openclaw).
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

**After the update, start a new session.** This applies whether you ran the
update or auto-update did. The migration notice below appears only when a
session starts. Claude Code's update banner suggests `/reload-plugins`, which
loads the new plugin without the notice, so the UniFi servers stay unconfigured
until your next session or until you ask Claude to run the plugin's setup
skill.

Auto-update is off by default for this marketplace. If you turned it on
(`/plugin`, then **Marketplaces**, then `unifi-plugins`, then **Enable
auto-update**), Claude Code installs 1.0.0 in the background during a session
and shows `Plugins updated: … Run /reload-plugins to apply`. Otherwise, update
yourself:

```bash
claude plugin marketplace update unifi-plugins
claude plugin update unifi-network@unifi-plugins
```

Repeat the second command for `unifi-protect@unifi-plugins` and
`unifi-access@unifi-plugins` if you have them. You can also use `/plugin`, then
**Installed**, then **Update now**.

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
> options cannot name a different controller per project. When the project's
> host, username, port and site equal the saved options, the notice says that
> nothing changes: remove the leftover keys, or run `--migrate` to tidy up.

If an earlier version configured this project, the first new session shows a
notice like this:

> UniFi Network plugin: this project's .claude/settings.local.json still holds
> UNIFI_NETWORK_* settings, which this plugin version no longer reads, so the
> UniFi Network server starts unconfigured. Ask Claude to run the
> unifi-network-setup migration (set-env.sh --target claude --migrate), then run
> /reload-plugins or start a new session (use /mcp reconnect
> plugin:unifi-network:unifi-network only if /mcp shows the server as failed).

Claude also offers to run the migration when you next ask about the plugin.
Until you migrate, the server either starts in setup mode (`/mcp` shows
`plugin:unifi-network:unifi-network` connected, but it offers only
`unifi_setup_status`, because no controller host is configured) or, when the
project file also holds a shared `UNIFI_HOST`, connects
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

Then, in the session that was already open, run `/reload-plugins`, or start a
new session. If you ran the migration in a terminal, Claude in that session may
still suggest migrating from the notice it saw at the start; a new session
clears it. Repeat the migration for each UniFi plugin you use.

`/mcp reconnect` alone keeps the options the session started with. It reports
success, but the server stays in setup mode, so use `/reload-plugins` or a new
session after setup or migration. Use
`/mcp reconnect plugin:unifi-network:unifi-network` only for a server that `/mcp`
shows as failed: Claude Code skips a server that failed to start in the last 15
minutes while its settings are unchanged, and a new session or
`/reload-plugins` leaves it skipped (`/mcp` reports "recent failure cached").
Saving new options counts as a change, so after setup or migration
`/reload-plugins` or a new session starts the server again.

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

In a session, run `/mcp` and select the plugin's server: it should offer more
than one tool. A server that offers only `unifi_setup_status`
(`protect_setup_status`, `access_setup_status`) is still unconfigured. `claude
mcp list` is not enough: it also shows an unconfigured server in setup mode as
connected. The migration notice no longer appears in new sessions.

### Codex

Codex upgrades its plugin marketplaces at the start of every session and
reinstalls any plugin whose version changed, so 1.0.0 arrives on its own. To
upgrade without starting a session, run:

```bash
codex plugin marketplace upgrade
```

#### One-time step if you ran Codex setup before 1.0.0

Earlier setup saved your settings in a `[mcp_servers.unifi-network]` entry
(or `unifi-protect`, `unifi-access`) in Codex's `config.toml`. That entry takes
precedence over the plugin's own server, so it keeps running the server version
it names, whatever the plugin installs. Once 1.0.0 is installed, run this once
for each plugin you set up, then restart Codex:

```bash
bash <plugin-root>/scripts/set-env.sh --target codex --refresh
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
`<plugin-root>` is the installed plugin, for example
`~/.codex/plugins/cache/unifi-plugins/unifi-network/1.0.0`. You can also ask
Codex to run the plugin's setup skill: its prerequisite check names the entry
and this command.

The command asks for no credentials. It moves the entry's settings, provider
references and per-category policy overrides included, into
`~/.config/unifi-mcp/<product>.env` (`%USERPROFILE%\.config\unifi-mcp\<product>.env`
on Windows), readable by you only, then removes the entry from `config.toml`.
Everything else in `config.toml` stays as written, and the previous file is kept
beside it as `config.toml.bak-unifi-<product>-<time>`. If the entry held anything
other than `UNIFI_` settings, the command names it (never its value); it stays
in the backup. Running the command again changes nothing.

#### After that

Codex runs the plugin's own server, which reads that file, so each plugin
upgrade brings the server version it pins with nothing to rerun. Codex installs
an upgrade in the background as a session starts, then restarts the plugin's
servers on the new version, typically 2 to 6 seconds in and before the first
request. Within that session, the skill files at the old version's cache path
are removed, so a skill that was already loaded may point at files that no
longer exist; start a new session to avoid this. To change a setting, run the
setup skill again. To remove the settings, delete the file.

### OpenClaw

```bash
openclaw plugins update unifi-network
```

A running Gateway applies the update without a restart. OpenClaw asks you to accept the plugin's capabilities before it updates
(`Accept these capabilities and update "unifi-network"? [y/N]`). In a script,
or anywhere without a terminal, add `--accept-capabilities`; without it the
update is refused. Use `openclaw plugins update --all` to update every plugin.
OpenClaw tracks commits rather than versions, and changes nothing until you run
this command.

#### One-time step if you ran OpenClaw setup before 1.0.0

Earlier setup saved your settings in an `mcp.servers.unifi-network` entry (or
`unifi-protect`, `unifi-access`) in `openclaw.json`. That entry replaces the
plugin's own server and pins the server version it names, so plugin updates
never reach the server. Updating the plugin leaves the entry as it is. Once 1.0.0
is installed, run this once for each plugin you set up:

```bash
bash <plugin-root>/scripts/set-env.sh --target openclaw --refresh
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target openclaw -Refresh`.
`<plugin-root>` is the installed plugin, for example
`~/.openclaw/extensions/unifi-network`. You can also ask OpenClaw to run the
plugin's setup skill: its prerequisite check names the entry and this command.

The command asks for no credentials. It moves the entry's settings, provider
references and per-category policy overrides included, into
`~/.config/unifi-mcp/<product>.env` (`%USERPROFILE%\.config\unifi-mcp\<product>.env`
on Windows), readable by you only. It saves the previous file beside it as
`openclaw.json.bak-unifi-<product>-<time>`, readable by you only, then removes
the entry with `openclaw mcp unset`. If the entry held anything other than
`UNIFI_` settings, the command names it (never its value); it stays in the
backup. Running the command again changes nothing. A running Gateway picks up
the change at the next agent turn; it needs no restart.

#### After that

OpenClaw runs the plugin's own server, which reads that file, so each
`openclaw plugins update` brings the server version the plugin pins, with
nothing to rerun. A running Gateway applies the update at the next agent turn.
To change a setting, run the setup skill again. To remove the settings, delete
the file.

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
  with the server version it pins. There is no switch to hold off. If you ran
  Codex setup before 1.0.0, your `config.toml` entry keeps its server until you
  run the [one-time step](#one-time-step-if-you-ran-codex-setup-before-100).
- **OpenClaw:** nothing until you run `openclaw plugins update`. To hold off,
  don't run it. If you ran OpenClaw setup before 1.0.0, your `openclaw.json`
  entry keeps its server until you run the
  [one-time step](#one-time-step-if-you-ran-openclaw-setup-before-100).

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
