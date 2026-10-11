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

Auto-update is off for this marketplace, so update yourself:

```bash
claude plugin marketplace update unifi-plugins
claude plugin update unifi-network@unifi-plugins
```

Repeat the second command for `unifi-protect@unifi-plugins` and
`unifi-access@unifi-plugins` if you have them. You can also use `/plugin`, then
**Installed**, then **Update now**. Running sessions keep the old server until
you run `/reload-plugins`.

#### Move your settings into plugin options

Plugin options are saved once for your user and apply in every project. A
password or API key entered as an option is stored in the system keychain;
everything else, including file and command provider paths, is stored in your
user `settings.json`.

If an earlier version configured this project, the first new session shows a
notice like this:

> UniFi Network plugin: this project's .claude/settings.local.json still holds
> UNIFI_NETWORK_* settings, which this plugin version no longer reads, so the
> UniFi Network server starts unconfigured. Ask Claude to run the
> unifi-network-setup migration (set-env.sh --target claude --migrate), then
> run /mcp reconnect plugin:unifi-network:unifi-network.

Until you migrate, the server either fails to start (`/mcp` shows
`plugin:unifi-network:unifi-network` as failed, because no controller host is
configured) or, when the project file also holds shared `UNIFI_HOST` settings,
connects with those shared settings, which may name a different controller.

To migrate, open Claude Code in that project and ask it to run the
`unifi-network-setup` migration, or run the plugin's script yourself from the
project directory:

```bash
bash <plugin-root>/scripts/set-env.sh --target claude --migrate
```

On Windows: `& <plugin-root>/scripts/set-env.ps1 -Target claude -Migrate`.
`<plugin-root>` is the installed plugin's directory; Claude Code keeps it under
`~/.claude/plugins/cache/unifi-plugins/<plugin>/<version>/`.

The migration copies this plugin's settings into its options, then removes only
this plugin's keys from `.claude/settings.local.json`. Its output names
variables only, never values:

- **Migrated:** settings now held as options.
- **Not migrated:** this plugin's settings that have no Claude Code option,
  such as per-category policy overrides. A leftover `UNIFI_AUTO_CONFIRM` is
  named too; it has no option, so use the permission mode instead.
- **Shared settings kept:** shared `UNIFI_*` keys stay in the project file,
  because setup cannot prove that another plugin or a standalone server no
  longer uses them. Remove them by hand once every consumer has moved.

Then run `/mcp reconnect plugin:unifi-network:unifi-network`, or start a new
session. After a failed start Claude Code can skip the server for up to 15
minutes, and `/reload-plugins` does not retry it; `/mcp reconnect` does. Repeat
the migration for each UniFi plugin you use.

Because options apply in every project, migrating a second project with
different settings replaces the first project's options. Plugin options cannot
name a different controller per project.

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

```bash
codex plugin marketplace upgrade
```

Codex reinstalls a plugin only when its version changes, which 1.0.0 does.
Setup created a separate, version-pinned MCP entry that takes precedence over
the plugin's bundled server, so refresh it from the newly installed plugin:

```bash
bash <new-plugin-root>/scripts/set-env.sh --target codex --refresh
```

On Windows: `& <new-plugin-root>/scripts/set-env.ps1 -Target codex -Refresh`.
You can also ask Codex to run the plugin's setup skill with `--refresh`. Refresh
keeps your saved settings and provider references, asks for no credentials and
prints the pinned package. Restart Codex afterwards. If there is no saved MCP
entry, run ordinary setup instead. Your saved Codex settings carry over,
including per-category policy overrides.

### OpenClaw

```bash
openclaw plugins update unifi-network
openclaw gateway restart
```

Use `openclaw plugins update --all` to update every plugin. OpenClaw follows
commits rather than versions, so it may already have the new files. The MCP
entry that setup writes pins the server package; 1.0.0 keeps the same server
versions, so that entry needs no change.

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

### Rollback and pinning

Each client reads the default branch unless you pinned a ref when you added the
marketplace. Plugin releases carry no tag, so to stay on the previous release,
pin a branch or tag (for example in a fork) that points at the last commit
before the 1.0.0 merge. In that commit the plugin versions equal the server
versions: Network 0.37.0, Protect 0.8.17, Access 0.6.12.

- **Claude Code:** add the marketplace as `<owner>/<repo>#<branch-or-tag>`.
  Claude Code cannot pin a commit SHA. The earlier plugin reads project
  settings, not plugin options.
- **Codex:** add the marketplace as `<owner>/<repo>@<ref>`. Codex will not
  re-add a marketplace from a different ref, so remove it first with
  `codex plugin marketplace remove`, add it at the ref, then reinstall with
  `codex plugin add <plugin>@unifi-plugins`. Re-run setup from that plugin with
  `--refresh`.
- **OpenClaw:** install with
  `openclaw plugins install git:<owner>/<repo>@<ref>`.

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
