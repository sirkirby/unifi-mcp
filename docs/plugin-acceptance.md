# Plugin acceptance procedure

This procedure produces real-client evidence for a cell of the
[plugin support matrix](plugin-support.md): a bundle installs from its
marketplace, is discovered, completes an MCP handshake, answers one harmless
authenticated read, and upgrades without losing its configuration. Run it with
the actual `claude` and `codex` binaries. Manifest checks, `--plugin-dir`,
direct `uvx` runs and stubs do not count.

Record results in the tracking issue, not in this repository. Never paste
credentials, hosts, MAC or IP addresses, hostnames, SSIDs, or camera, door or
device names into results; record tool names, success or failure, and the
response's top-level key names and counts only.

## Choose the refs

- **Prior version:** the commit of an earlier plugin-version sync. Record the
  plugin versions in `plugins/unifi-*/.claude-plugin/plugin.json` and the
  package pins in the inline `mcpServers` of `plugins/unifi-*/.claude-plugin/plugin.json`
  (Claude Code) and `plugins/unifi-*/.mcp.codex.json` (Codex and OpenClaw). A ref
  before 1.0.0 also ships a root `.mcp.json` with the Claude Code pin.
- **Candidate:** the branch or commit under test. Record its commit and pins.
- **Claude Code configuration model:** record whether each ref declares
  `userConfig` in `plugins/unifi-*/.claude-plugin/plugin.json`. Refs with
  `userConfig` keep Claude Code settings as plugin options; earlier refs write
  `UNIFI_*` variables into the project's `.claude/settings.local.json`.
- If a bundle's files change but its version does not, expect clients that
  compare versions to skip the upgrade, and record what each client installs.

## Isolate the clients

Never touch the real client configuration. Before starting, record
`shasum ~/.claude.json ~/.claude/settings.json ~/.codex/config.toml`; the same
command must print the same output at the end.

Create a scratch directory `ACC` that is deleted afterwards and never committed.

- **Claude Code:** run every `claude` command with `HOME=$ACC/claude-home`.
  Create `$ACC/claude-home/Library`, then symlink `~/Library/Keychains` to
  `$ACC/claude-home/Library/Keychains` so the existing sign-in is reused (if
  `~/Library/Preferences/com.apple.security.plist` exists, symlink it into
  `$ACC/claude-home/Library/Preferences/` too). Do not set `CLAUDE_CONFIG_DIR`.
  Unset inherited `CLAUDE*` variables when launching from inside another Claude
  session. Plugins synced from claude.ai still load in the isolated profile;
  ignore them. Never store a `sensitive` plugin option (`password`, `api_key`)
  from this profile: it would be written to the shared keychain. Configure the
  password and API key only through `_FILE` or `_COMMAND` provider references,
  which are saved as ordinary options.
- **Codex:** run every `codex` command with `CODEX_HOME=$ACC/codex-home` and
  `HOME=$ACC/home`, and symlink (never copy) `~/.codex/auth.json` into
  `CODEX_HOME`. Codex setup reads both: it writes the settings file under
  `$HOME/.config/unifi-mcp/`, which the bundled server reads from the same
  `HOME`, and converts entries in `$CODEX_HOME/config.toml`. Without them, setup
  writes your real `~/.config/unifi-mcp/` and edits `~/.codex/config.toml`.
- **Clean-environment wrappers:** a wrapper that clears the environment (`env -i`,
  or unsetting variables) must set `HOME`, `CLAUDE_CONFIG_DIR` where used, and
  `CODEX_HOME` after the clearing, and the same wrapper must launch setup and
  `--refresh` as well as the client. Check the wrapper by running setup with
  `--dry-run` first and confirming the configuration hash is unchanged.
- **Ambient credentials:** unset every inherited `UNIFI_*` variable before each
  client or setup command, so only the setup under test can configure a server.
- **Scratch project:** run sessions from a project directory under `ACC` that
  is its own Git root (`git init`). Inside a Git worktree, Claude Code also
  loads the main checkout's `.claude/settings.local.json`, which can supply
  credentials the setup never wrote.
- **Secrets:** write each password or API key to a `0600` file under `ACC` from
  a subshell that loads the credentials; pass only file or command provider
  references to setup. Pipe anything else secret as JSON on stdin where the
  setup script supports it.
- **Safety gates:** configure `UNIFI_POLICY_CREATE`, `UNIFI_POLICY_UPDATE` and
  `UNIFI_POLICY_DELETE` (and the product-scoped forms) as `false`,
  `UNIFI_TOOL_PERMISSION_MODE=confirm`. Leave `UNIFI_AUTO_CONFIRM` unset: it is
  deprecated, and any value makes the server log a deprecation notice. Allow the
  client to call only tools whose manifest annotation is `readOnlyHint: true`.
  In the default lazy registration mode a candidate lists its incident evidence
  tools directly, and they are read-only. Other controller reads, such as the
  harmless read in step 5, go through `*_execute`, which is not read-only, so
  select eager registration through the setup skill's optional settings for
  those steps.
- **Claude Code plugin options:** with a `userConfig` ref, `set-env.sh --target
  claude` accepts only the variables the plugin maps to options, so pass the
  product-scoped forms: `UNIFI_POLICY_<PRODUCT>_CREATE`, `_UPDATE` and `_DELETE`
  as `false`, `UNIFI_<PRODUCT>_TOOL_PERMISSION_MODE=confirm` and
  `UNIFI_TOOL_REGISTRATION_MODE=eager`; `UNIFI_AUTO_CONFIRM` has no option and
  is refused. Shared
  `UNIFI_POLICY_*` forms and per-category overrides are refused by design. The
  gates already default to `false` and the permission mode to `confirm`; set
  them explicitly anyway so the record shows them.

## Pin a marketplace ref

- **Codex:** `codex plugin marketplace add <owner>/<repo> --ref <branch-tag-or-sha>`.
- **Claude Code:** `claude plugin marketplace add <owner>/<repo>#<branch-or-tag>`.
  It cannot pin a commit SHA. To install a commit that no branch or tag names,
  make a bare clone of the repository under `ACC`, create a local branch at the
  commit, serve it read-only on loopback with `git http-backend` (smart HTTP;
  Claude's shallow clone fails over dumb HTTP), and add
  `http://127.0.0.1:<port>/<repo>.git#<branch>`. Record that you did so.

## Steps for each client and bundle

1. **Install the prior version.** Add the marketplace, install the plugin, and
   keep the command output.
2. **Discovery.** `claude plugin list` and `claude plugin details <plugin>`, or
   `codex plugin list`, show the plugin installed and enabled with its skills
   and MCP server. Ask an in-session prompt to list the plugin's skills.
   Before setup, start one session and confirm the unconfigured server
   answers `initialize` in setup mode, offers only its read-only
   `<prefix>_setup_status` tool (`unifi_`, `protect_` or `access_`), and logs no
   credential or registration-mode errors. (Server releases before setup mode
   exit with "No controller host configured — refusing to start."; expect that
   only from a prior version that pins one.) Other tool calls are only
   required after configuration. With a `userConfig` ref, also record that
   `claude plugin install` reports the plugin's options as not yet set, and that
   a fresh project shows no session-start notice from the plugin.
3. **Configure** with that version's documented setup script for the client
   target (`scripts/set-env.sh --target claude|codex`). With a `userConfig` ref,
   Claude Code setup saves plugin options through `claude plugin configure`:
   confirm it created no `.claude/settings.local.json` in the scratch project
   and added no `env` to `$ACC/claude-home/.claude/settings.json`, and record
   only the option key names listed under `pluginConfigs` there.
4. **Handshake.** In a session, call the product's `*_tool_index` tool and
   confirm the server's tools are listed. Record the server version: the
   package pin from `claude mcp list` or `codex mcp list` (which lists only the
   `config.toml` entry while one shadows the plugin's server), and for Codex the
   `serverInfo` version visible with `RUST_LOG=rmcp=info`. With Claude Code
   plugin options, `claude mcp list` must also report the server as connected;
   that alone does not prove configuration, because a server in setup mode is
   connected too.
5. **Harmless read.** In a session, have the model call
   `unifi_get_system_info`, `protect_get_system_info` or
   `access_get_system_info`, and confirm `success: true`. For Claude Code with
   plugin options, repeat steps 4 and 5 in at least five consecutive fresh
   sessions for one bundle. In one of them, confirm the server's environment
   shape with `ps -E -ww` (record each `UNIFI_*` name as set or empty, never a
   value; on macOS it shows other processes' environments only with `-ax` or
   `-p <pid>`): the unset password and API-key spellings are empty. In another, have
   the model run `env | grep -c '^UNIFI_'` through the Bash tool, in the
   configured project and in an unrelated one; both must print `0`.
6. **Upgrade.** Claude Code: move the marketplace to the candidate, then
   `claude plugin marketplace update <marketplace>` and
   `claude plugin update <plugin>@<marketplace>`. Codex: it refuses to re-add a
   marketplace from a different ref, so `codex plugin marketplace remove`, add
   it at the candidate ref, then `codex plugin add <plugin>@<marketplace>` again.
   From 1.0.0 Codex setup writes no `config.toml` entry: it saves the settings in
   `$HOME/.config/unifi-mcp/<product>.env` (mode 600), which the bundled entry in
   `.mcp.codex.json` names with `UNIFI_SETTINGS_FILE`, so the upgrade needs no
   action. Record that the settings file and `config.toml` are byte-identical
   afterwards. A prior ref before 1.0.0 wrote a `[mcp_servers.<plugin>]` entry
   that shadows the bundled server and pins its package. Run the new plugin's
   `scripts/check-prereqs.sh --target codex` and record that it names the entry
   and the refresh. Then run `scripts/set-env.sh --target codex --refresh`
   (PowerShell: `scripts/set-env.ps1 -Target codex -Refresh`) once. Record that
   it asks for no credentials, that the settings file holds the entry's `UNIFI_`
   key names (names only) with mode 600, that `config.toml` differs from the
   saved `config.toml.bak-<plugin>-<time>` only by the entry's tables, and that a
   second refresh reports nothing to convert. When Codex installs the upgrade
   itself at a session start, it then restarts the plugin's servers on the new
   version, typically 2 to 6 seconds in and before the first request; record the
   `serverInfo` that session's first request sees. Skill files at the old
   version's cache path are removed during that session, so read skills from a
   new session.
   Confirm the new plugin version is installed, the saved environment is
   unchanged, the running server is the candidate's package version (for Codex,
   from `serverInfo`), and repeat steps 4 and 5.

   **Claude Code, from project settings to plugin options.** When the prior ref
   configured Claude Code through `.claude/settings.local.json` and the
   candidate declares `userConfig`:
   1. **Banner path.** In an interactive session that was open before the
      update, run `/reload-plugins` as Claude Code's banner suggests, then ask
      for something that needs the server. `/reload-plugins` runs no
      SessionStart hook of an updated plugin, with any matcher, so no notice
      appears. Record whether `/mcp` shows the server connected or failed, which
      UniFi tools Claude sees, what it suggests, and whether it offers the setup
      skill. If it does, the setup skill's prerequisite check names the leftover
      settings. A server pinned to a release with setup mode connects and offers
      only its `<prefix>_setup_status` tool, which says how to configure it. A
      pinned release before setup mode exits instead: `/mcp` shows it as failed
      with no reason, Claude sees only `CONNECTION_CLOSED` and no UniFi tools,
      and the server's own refusal ("No controller host configured — refusing to
      start.") reaches only the debug log.
   2. Start the first session after the update. Record the plugin's session-start notice: a `hook_response` event whose `systemMessage` names
      `set-env.sh --target claude --migrate`. Also record that the server
      says what the server will do. With no shared `UNIFI_HOST` in the project
      file it says the server starts unconfigured: record that `ps -E -ww`
      shows the product-scoped variables empty although the project file still
      holds them. With shared `UNIFI_HOST` / `UNIFI_USERNAME` / credential
      provider keys it says the server will use the shared `UNIFI_*` settings,
      which may name a different controller, until migration: record which
      controller the server contacts, and keep that controller read-only
      or non-production.
   3. Run the new plugin's `scripts/check-prereqs.sh --target claude` from the
      scratch project. Record that it names the leftover variables (names only).
   4. Run the new plugin's `scripts/set-env.sh --target claude --migrate`
      (PowerShell: `scripts/set-env.ps1 -Target claude -Migrate`). Record the
      variable names it reports as migrated, not migrated and kept as shared
      settings. Confirm the project file now holds only the shared settings
      and unrelated keys, and that a second `--migrate` refuses with nothing to
      migrate. Migrating every UniFi plugin still keeps the shared settings,
      because setup cannot prove that no other consumer (an older plugin or a
      standalone server) relies on them; confirm the output says so, that
      `check-prereqs` names the remaining shared keys once no plugin keys are
      left, and remove them by hand only after checking each consumer.
   5. In an interactive session that was open before the migration, record that
      `/mcp reconnect` alone reports success but leaves the server in setup
      mode (only `<prefix>_setup_status`), and that `/reload-plugins` brings the
      server up with its full tool list. Repeat steps 4 and 5 in fresh sessions.
      Confirm the notice no longer appears.
   6. **Second project.** Configure another scratch project the prior way, with
      a different host for one product (an unroutable loopback port), after the
      first project is migrated. Record that its first session shows the
      other-project notice (the server is using options saved from another
      project), that `--migrate` refuses and names the differing variables, and
      that `--migrate --replace` replaces the options for every project. In a
      third scratch project whose legacy host, username, port and site equal the
      saved options, record that the first session shows the gentler notice
      (nothing changes; remove the leftover keys or run `--migrate`) and no
      other-project notice.
7. **Failure recovery.** Run the candidate's setup with an invalid provider
   path, a missing provider command and an invalid key. Each must exit non-zero
   with a fixed message, leave the configuration byte-identical and leave no
   lock or staging directory; then repeat step 5. With Claude Code plugin
   options, also try a per-category override such as
   `UNIFI_POLICY_<PRODUCT>_<CATEGORY>_UPDATE=true`, which must be refused. The
   configuration is `$ACC/claude-home/.claude/settings.json`, together with the
   inputs `claude plugin configure <plugin>@<marketplace> --json` prints; both
   must be unchanged.

Codex reads `plugins/unifi-*/.mcp.codex.json` through its manifest's
`mcpServers` path. Codex does not expand `${VAR:-default}` in an MCP `env`
block, so that file must contain no interpolation templates. Claude Code reads
the server declared inline in `.claude-plugin/plugin.json`, which maps each server variable to a plugin option with
`${user_config.KEY}` when the ref declares `userConfig`. If either file changes,
check the running server's environment with `ps -E -ww` against what the client
was given.

## Running sessions

- **Claude Code:** `claude -p --model sonnet --allowedTools "<exact tool names>"
  --output-format stream-json --verbose`, from the scratch project. Plugin tools
  are named `mcp__plugin_<plugin>_<server>__<tool>`. A failed server start is
  cached for about 15 minutes, keyed by the server name and its expanded
  configuration, so a later session with the same configuration skips the
  server ("recent failure cached"). With the configuration unchanged, neither a
  new session nor `/reload-plugins` retries it; users recover with an
  interactive `/mcp reconnect plugin:<plugin>:<server>`, and `-p` sessions
  cannot reconnect. A session that was open when plugin options changed keeps
  its old copy: there `/mcp reconnect` restarts the server with the old options
  (a server pinned to a release with setup mode reports success but stays in
  setup mode) until `/reload-plugins` loads the new options. In the isolated
  profile only, remove that
  server's entry from `$ACC/claude-home/.claude/mcp-needs-auth-cache.json`
  before retrying, and record that you did. Saving plugin options changes the
  expanded configuration, so a session after setup is not skipped by a failure
  cached before setup. `claude mcp list` ignores environment from project
  settings, so with a ref that configures Claude Code through
  `.claude/settings.local.json` it reports the server as failed and writes a
  failure entry itself; do not run it between that kind of setup and a session.
  With plugin options it applies the same configuration as a session. Claude
  blocks a standalone `sleep` in Bash, and it auto-allows read-only `jq` and
  Read on its own saved tool results even when `--allowedTools` omits them; plan
  for both when reading large results. Interactive Claude defaults to the auto
  permission mode: launch the interactive reconnect test with `--permission-mode
  default` so every tool call prompts as it would for a user.
- **Claude Code auto-update:** each session makes one background auto-update
  pass, after a random delay of up to ten minutes, and only for marketplaces
  whose auto-update was already on when the session started. Turning it on
  mid-session updates nothing until the next session, and the pass may come
  well after the delay (one run took 18 minutes). Launch with `--debug-file
  <path>` to see `Plugin autoupdate: updated …`, the server's stderr, and each
  hook run with its exit status and duration.
- **Claude Code cache:** installed plugins are cached by version, and
  `claude plugin uninstall` keeps the cache. Before installing a different
  candidate commit that carries the same version, delete
  `$ACC/claude-home/.claude/plugins/cache/<marketplace>/<plugin>/<version>`;
  otherwise the earlier copy is installed again.
- **Codex:** `codex exec -m <model> -s read-only --json "<prompt>" </dev/null`.
  Without stdin closed it waits for input. MCP servers finish starting after the
  first step's tools are built, so have the model run `sleep 20` before its MCP
  calls.
- Space sessions that log in to a controller about 20 seconds apart;
  back-to-back logins can hit the controller's authentication rate limit, and
  such a run does not count as a pass or a failure of the plugin.
- Codex upgrades configured Git marketplaces at the start of every session, and
  `codex plugin marketplace upgrade` does the same on demand at the same ref; a
  different ref still needs remove and re-add. Record plugin versions before
  starting a Codex session if the step needs the prior version installed.
- Read results from the transcript, not the model's summary. Reduce each tool
  result to its top-level keys and counts before recording it.

## Test unreleased candidates

A candidate's server packages are not on PyPI, and its plugin pins name releases
that do not exist yet. Test them without publishing anything:

1. From a clean clone at the candidate commit, build wheels with
   `uv build --package <package> --wheel --out-dir $ACC/wheels` for each package
   the servers need (the shared and core libraries, the product servers, and the
   relay when the relay is under test). Record each wheel's `sha256`.
2. Point `uv` at them with `UV_FIND_LINKS=$ACC/wheels`. Wheels built from a
   development checkout carry a `.devN` version, which does not satisfy the
   candidate's own floors (a floor such as `unifi-core>=0.4.69` excludes
   `0.4.69.devN`). Write an override file with one exact requirement per built
   wheel and set `UV_OVERRIDE` to it. Name the extras the servers install:
   `unifi-core[network,protect]==<built version>`. Without `[protect]` the
   Protect server fails with `ModuleNotFoundError: uiprotect`; Network survives
   only because it pins `aiounifi` directly.
3. On the loopback marketplace mirror only, add one commit that changes nothing
   but the package pins in each plugin's `plugin.json` and
   `.mcp.codex.json` to the built versions, and install from that commit. Never
   push it, and do not run `make check-plugin-versions` on it: the pins have no
   release tag by design. Codex setup does not read the pin, so it needs no
   hand-written registration.
4. Export `UV_FIND_LINKS` and `UV_OVERRIDE` in the environment that launches the
   client, so the client's server processes inherit them. Prove the servers ran
   the candidate: each server's own interpreter reports the package under the
   `uv` cache inside `ACC`, the installed files match the wheel hashes, `serverInfo`
   or `claude mcp list` reports the built version, and nothing is an editable or
   workspace install.

   Codex does not pass `UV_FIND_LINKS` or `UV_OVERRIDE` to plugin servers, and
   uvx ignores `override-dependencies` in a user `uv.toml`, so the servers fail
   with "there is no version of unifi-<product>-mcp==<built version>". In the
   same mirror-only commit, add `"UV_FIND_LINKS"`, `"UV_OVERRIDE"` and
   `"UV_CACHE_DIR"` to each server's `env_vars` in `.mcp.codex.json`. Record it
   as a workaround.

## What counts as a pass

A cell passes only when the quoted command output or transcript shows the
result for that client, bundle and step. If the step could not run, record it
as `blocked` or `not tested` with the reason. A step that needed a workaround
passes only if the report states the workaround; record the underlying defect
separately.

## Clean up

Stop the loopback server, delete `ACC`, check `git status` shows no scratch
files, and compare the `shasum` output with the value recorded at the start.
