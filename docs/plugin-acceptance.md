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
  package pins in `plugins/unifi-*/.mcp.json` (Claude Code) and
  `plugins/unifi-*/.mcp.codex.json` (Codex).
- **Candidate:** the branch or commit under test. Record its commit and pins.
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
  ignore them. Never store a `sensitive` plugin option from this profile: it
  would be written to the shared keychain.
- **Codex:** run every `codex` command with `CODEX_HOME=$ACC/codex-home`, and
  symlink (never copy) `~/.codex/auth.json` into it.
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
  `UNIFI_TOOL_PERMISSION_MODE=confirm` and `UNIFI_AUTO_CONFIRM=false`. Allow the
  client to call only tools whose manifest annotation is `readOnlyHint: true`.
  In the default lazy registration mode the only route to a controller read is
  `*_execute`, which is not read-only, so select eager registration through the
  setup skill's optional settings.

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
   Before setup, start one session and confirm the unconfigured server exits
   with "No controller host configured — refusing to start." and no
   credential or registration-mode errors. The handshake and tool calls are
   only required after configuration.
3. **Configure** with that version's documented setup script for the client
   target (`scripts/set-env.sh --target claude|codex`).
4. **Handshake.** In a session, call the product's `*_tool_index` tool and
   confirm the server's tools are listed. Record the server version: the
   package pin from `claude mcp list` or `codex mcp list`, and for Codex the
   `serverInfo` version visible with `RUST_LOG=rmcp=info`.
5. **Harmless read.** In a session, have the model call
   `unifi_get_system_info`, `protect_get_system_info` or
   `access_get_system_info`, and confirm `success: true`.
6. **Upgrade.** Claude Code: move the marketplace to the candidate, then
   `claude plugin marketplace update <marketplace>` and
   `claude plugin update <plugin>@<marketplace>`. Codex: it refuses to re-add a
   marketplace from a different ref, so `codex plugin marketplace remove`, add
   it at the candidate ref, then `codex plugin add <plugin>@<marketplace>` again.
   Codex setup writes a user MCP registration that shadows the plugin's server
   and pins its package, so after the upgrade run the new plugin's
   `scripts/set-env.sh --target codex --refresh` (PowerShell:
   `scripts/set-env.ps1 -Target codex -Refresh`). It reuses the saved
   environment without asking for credentials and prints the new pin.
   Confirm the new plugin version is installed, the saved environment is
   unchanged, the running server is the candidate's package version (for Codex,
   from `serverInfo`), and repeat steps 4 and 5.
7. **Failure recovery.** Run the candidate's setup with an invalid provider
   path, a missing provider command and an invalid key. Each must exit non-zero
   with a fixed message, leave the configuration byte-identical and leave no
   lock or staging directory; then repeat step 5.

Codex reads `plugins/unifi-*/.mcp.codex.json` through its manifest's
`mcpServers` path. Codex does not expand `${VAR:-default}` in an MCP `env`
block, so that file must contain no interpolation templates; Claude Code keeps
`.mcp.json`. If either file changes, check the running server's environment
with `ps -E -ww` against what the client was given.

## Running sessions

- **Claude Code:** `claude -p --model sonnet --allowedTools "<exact tool names>"
  --output-format stream-json --verbose`, from the scratch project. Plugin tools
  are named `mcp__plugin_<plugin>_<server>__<tool>`. A failed server start is
  cached for about 15 minutes, keyed by the server name and its expanded
  configuration, so a later session with the same configuration skips the
  server ("recent failure cached"). Users recover with an interactive
  `/mcp reconnect plugin:<plugin>:<server>`; `/reload-plugins` does not retry,
  and `-p` sessions cannot reconnect. In the isolated profile only, remove that
  server's entry from `$ACC/claude-home/.claude/mcp-needs-auth-cache.json`
  before retrying, and record that you did. `claude mcp list` ignores
  environment from project settings, reports such a server as failed and writes
  a failure entry itself, so do not run it between setup and a session.
- **Codex:** `codex exec -m <model> -s read-only --json "<prompt>" </dev/null`.
  Without stdin closed it waits for input. MCP servers finish starting after the
  first step's tools are built, so have the model run `sleep 20` before its MCP
  calls.
- Space sessions that log in to a controller about 20 seconds apart;
  back-to-back logins can hit the controller's authentication rate limit, and
  such a run does not count as a pass or a failure of the plugin.
- Codex `codex plugin marketplace upgrade` refreshes a marketplace at the same
  ref; a different ref still needs remove and re-add.
- Read results from the transcript, not the model's summary. Reduce each tool
  result to its top-level keys and counts before recording it.

## What counts as a pass

A cell passes only when the quoted command output or transcript shows the
result for that client, bundle and step. If the step could not run, record it
as `blocked` or `not tested` with the reason. A step that needed a workaround
passes only if the report states the workaround; record the underlying defect
separately.

## Clean up

Stop the loopback server, delete `ACC`, check `git status` shows no scratch
files, and compare the `shasum` output with the value recorded at the start.
