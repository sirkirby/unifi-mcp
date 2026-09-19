# Agent installation options

Research date: 2026-09-19

## Recommendation

UniFi MCP should support three separate installation layers:

1. Native host plugins where the host can install the MCP server and the product skills together.
2. Native MCP configuration plus product-scoped skills for hosts without a compatible plugin package.
3. A bounded README prompt that lets a user's agent choose the right path, show planned changes, protect credentials, and verify a read-only call.

For the newly reviewed clients:

| Client | Current status | Recommended UniFi path |
|---|---|---|
| Google Antigravity | Google's primary consumer agent platform after the Gemini CLI transition | Build and test an Antigravity plugin. Document manual MCP setup first. |
| Gemini CLI | Still released for enterprise customers and paid API-key users, but no longer serves individual accounts | Do not target it in the main install plan. Add compatibility guidance only if enterprise or API-key users request it. |
| Devin Local in Devin Desktop / Devin CLI | Devin Local is the primary Desktop agent and shares the Devin CLI harness and MCP configuration | Document the current `devin mcp` setup for Devin Local and CLI. |
| Cascade in Devin Desktop | Legacy Desktop agent with a separate MCP settings UI and raw configuration | Keep a separate manual compatibility path while Cascade remains available. |
| OpenCode | Native local and remote MCP support is sufficient for UniFi MCP | Document native MCP plus product skills. Do not build a wrapper plugin now. |

## Corrections to the earlier assessment

The earlier research note overclaimed or became stale in three places.

- Gemini CLI exists and still receives stable releases. However, Google moved free and Google AI Pro and Ultra consumer access to Antigravity in June 2026. Antigravity is the correct primary Google target for general users. Gemini CLI remains relevant to enterprise and paid API-key users.
- Windsurf is no longer the current desktop product name. Cognition renamed it Devin Desktop on June 2, 2026. Devin Local replaced Cascade as the primary local agent. Compatibility paths and the Windsurf JetBrains plugin remain, so "Windsurf disappeared" would also be wrong.
- OpenCode does not need a UniFi-specific JavaScript or npm plugin to connect to UniFi MCP. OpenCode v2 can start local stdio MCP servers directly. Its plugin system is useful only if UniFi needs host-specific behavior beyond MCP registration and skills.

## Google clients

### Antigravity is the primary target

Google's May 19, 2026 [transition announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/) made Antigravity CLI available to everyone and ended Gemini CLI service for free and Google AI Pro and Ultra users on June 18. Enterprise customers and users with paid Gemini or Gemini Enterprise Agent Platform API keys retained Gemini CLI access.

Antigravity is not merely another name for Gemini CLI. It has its own CLI, desktop application, IDE, configuration paths, and plugin format. Its [MCP documentation](https://antigravity.google/docs/mcp) supports local stdio and remote MCP servers in Antigravity CLI, Antigravity IDE, and Antigravity 2.0. The CLI uses `~/.gemini/config/mcp_config.json` globally and `.agents/mcp_config.json` per workspace.

Antigravity is a good packaging target for this repository. Its [plugin documentation](https://antigravity.google/docs/plugins) defines a bundle with:

- `plugin.json` as the required marker;
- `mcp_config.json` for MCP servers;
- `skills/`, `agents/`, `rules/`, and `hooks.json` as optional components.

That structure matches the existing UniFi product bundles in purpose, but not in exact filenames or environment syntax. Build one Antigravity plugin per UniFi product. Test `uvx`, environment substitution, credential-file and credential-command settings, plugin upgrade, uninstall, and the MCP handshake before advertising one-command installation.

### Gemini CLI still exists, but it is secondary

Gemini CLI published [stable v0.60.0 on September 15, 2026](https://geminicli.com/docs/changelogs/latest/), four months after Google's transition announcement. Its current [MCP guide](https://geminicli.com/docs/tools/mcp-server/) supports local and remote servers, and its [extension reference](https://geminicli.com/docs/extensions/reference/) can bundle MCP definitions, settings, skills, hooks, and commands.

These facts do not make Gemini CLI a target for this project's user-facing install plan. The project's individual-user workflow has moved to Antigravity, matching Google's consumer transition. The README and agent install guide should document Antigravity only. This research note should retain the distinction so maintainers do not incorrectly claim that Gemini CLI no longer exists.

If enterprise or paid API-key users later request Gemini CLI support, add it as a clearly labeled compatibility path rather than placing it beside Antigravity in the normal installation choices.

Do not describe Gemini extensions as npm plugins. Gemini installs extensions from a Git repository or local path. Antigravity calls its bundles plugins and provides an [`agy plugin import gemini` migration](https://antigravity.google/docs/cli/gcli-migration/) that converts Gemini extensions and changes MCP and skills paths.

## Devin Desktop, formerly Windsurf

Cognition acquired Windsurf in July 2025, then announced [Windsurf is now Devin Desktop](https://devin.ai/blog/windsurf-is-now-devin-desktop) on June 2, 2026. Devin Desktop is the current desktop client. The same announcement names Devin Local as Cascade's successor, and the [current Devin Local documentation](https://docs.devin.ai/desktop/devin-local) calls it the primary local agent.

The README should use the label "Devin Desktop, formerly Windsurf." It should not present Windsurf, Devin Desktop, and Devin Local as three independent hosts:

- Devin Desktop is the application and editor.
- Devin Local is its primary local agent.
- Cascade is a legacy agent retained for migration, not the current default.

The current [Devin Local documentation](https://docs.devin.ai/desktop/devin-local)
says that Devin Local inside Devin Desktop shares the Devin CLI agent harness
and config-file mechanism. The [Devin MCP configuration guide](https://docs.devin.ai/cli/extensibility/mcp/configuration)
is therefore the installation source of truth for Devin Local and Devin CLI. It
supports local stdio servers with:

```text
devin mcp add <name> -- <command> [args...]
```

Current configuration files are `~/.config/devin/mcp_config.json` for the user, `.devin/mcp_config.json` for a shared project entry, and `.devin/mcp_config.local.json` for a gitignored local entry. The guide recommends the local file for secrets. This supersedes a README recipe centered on `~/.codeium/windsurf/mcp_config.json`, though the [migration FAQ](https://docs.devin.ai/desktop/devin-desktop-faq) documents legacy compatibility paths.

Document the current `devin mcp` route for Devin Local and Devin CLI. Cascade
uses a separate Desktop configuration: **Devin Settings > Cascade > MCP
Servers**, or its raw `mcp_config.json`, as documented in Cognition's
[Cascade MCP guide](https://docs.devin.ai/desktop/cascade/mcp). Do not send a
Cascade user through the Devin Local/CLI command, and do not create a separate
Windsurf marketplace plan.

## OpenCode

OpenCode v2 has complete native MCP support. Its [MCP server guide](https://opencode.ai/v2/docs/mcp-servers) supports local stdio commands, remote Streamable HTTP, environment substitution, OAuth, permission rules, and connection management through `opencode mcp` and `/mcps`.

For UniFi MCP, the direct path is enough:

```text
opencode mcp add unifi-network -- uvx --python-preference system unifi-network-mcp==<version>
opencode mcp list
```

Credentials should come from the user's environment or an uncommitted local configuration. OpenCode's JSON syntax uses `{env:NAME}` rather than shell-style `${NAME}` substitution. Product skills can be installed separately after the standalone-skill packaging issues are fixed.

OpenCode's [plugin system](https://opencode.ai/v2/docs/plugins) is real and broader than the earlier note implied. It loads JavaScript or TypeScript from local plugin directories, npm packages, scoped packages, and npm-compatible Git sources. The [plugin API](https://opencode.ai/v2/docs/build/plugins) can add tools, hooks, commands, skills, agents, integrations, and MCP configuration.

A UniFi OpenCode plugin would add value only if it delivered host-specific behavior that native MCP and standalone skills cannot provide. Examples include a tested credential wizard, OpenCode-specific permission defaults, or commands that coordinate several UniFi products. A package that only adds the same `uvx` MCP entry would add another release artifact, execute JavaScript inside OpenCode, and duplicate native configuration. Skip it unless a concrete OpenCode-only requirement appears.

## Changes to the broader install plan

### Implement now

1. Add current manual recipes for Antigravity, Devin Desktop, and OpenCode. Keep each client's configuration syntax separate.
2. Make Antigravity the only Google entry in the main install guide. Do not restore Gemini-specific project instructions or a Gemini installation path.
3. Rename the Windsurf entry to "Devin Desktop, formerly Windsurf" and use `devin mcp` plus current `.devin` paths.
4. Use OpenCode's native MCP support. Keep MCP registration and skills installation as separate steps.
5. Add clean-profile tests for `uvx` startup, environment handling, the MCP handshake, tool discovery, a harmless read-only call, upgrade, and uninstall.

### Package next

1. Build one Antigravity plugin per UniFi product after validating its manifest and environment rules.
2. Consider Gemini CLI compatibility documentation or an extension only after an explicit enterprise or paid API-key user request.
3. Evaluate a Devin team marketplace entry after the manual Devin Desktop path works and the marketplace accepts local stdio servers with LAN credentials.

### Skip for now

1. A UniFi OpenCode npm plugin that only registers the MCP server.
2. New documentation that treats Windsurf or Cascade as the current default client.
3. A combined Google package presented as compatible with both Gemini CLI and Antigravity without conversion and separate tests.

## Agent-directed README block

The README can offer a pasteable prompt, but the prompt should point to one versioned guide instead of duplicating host commands:

```text
Install UniFi MCP for me using the official instructions in:
https://github.com/sirkirby/unifi-mcp/blob/main/docs/agent-install.md

First identify my client and operating system. Ask whether I need Network,
Protect, Access, or more than one. Show the exact commands and files you will
change, then wait for confirmation.

Use the current client name and its native MCP or plugin path. For Google,
distinguish Antigravity from Gemini CLI. Treat Devin Desktop as the current
name for Windsurf and use Devin Local rather than legacy Cascade instructions.

Do not ask me to paste credentials into chat. Prefer a credential file,
credential command, environment reference, gitignored local configuration,
or a client-native secret prompt. Keep mutation confirmation enabled.

After setup, reload the client, verify the MCP handshake, list the UniFi tools,
and run one harmless read-only system-information check. Stop and explain the
problem if a prerequisite or safe secret-entry method is unavailable.
```

## Unknowns that require live tests

- Whether Antigravity plugin installation can prompt for every UniFi setting without storing secrets in a shared manifest.
- Whether the Antigravity plugin loader accepts this repository's monorepo layout or needs per-product release archives.
- Whether Devin Desktop's team marketplace accepts a local `uvx` stdio server that connects to a private LAN address.
- Whether OpenCode's default Code Mode handles the current UniFi tool count well enough without product-category tuning.
- Whether explicit enterprise or paid API-key demand ever justifies reopening Gemini CLI support.

## Primary sources

| Source | Finding |
|---|---|
| [Google transition announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/) | Antigravity is Google's consumer successor; Gemini CLI remains for enterprise and paid API-key users. |
| [Antigravity MCP](https://antigravity.google/docs/mcp) | Current MCP support and configuration paths across Antigravity clients. |
| [Antigravity plugins](https://antigravity.google/docs/plugins) | Plugin bundle layout for MCP, skills, agents, rules, and hooks. |
| [Gemini-to-Antigravity migration](https://antigravity.google/docs/cli/gcli-migration/) | Different config paths and extension-to-plugin conversion. |
| [Gemini CLI stable release](https://geminicli.com/docs/changelogs/latest/) | Gemini CLI still ships current releases. |
| [Gemini CLI MCP guide](https://geminicli.com/docs/tools/mcp-server/) | Native Gemini MCP configuration. |
| [Gemini CLI extension reference](https://geminicli.com/docs/extensions/reference/) | Git and local extension installation and bundle contents. |
| [Windsurf is now Devin Desktop](https://devin.ai/blog/windsurf-is-now-devin-desktop) | Current product name and Cascade-to-Devin Local transition. |
| [Devin Desktop FAQ](https://docs.devin.ai/desktop/devin-desktop-faq) | Migration dates, compatibility paths, and remaining Windsurf support. |
| [Devin MCP configuration](https://docs.devin.ai/cli/extensibility/mcp/configuration) | Current CLI commands, config paths, transports, and secret guidance. |
| [OpenCode v2 MCP servers](https://opencode.ai/v2/docs/mcp-servers) | Native local and remote MCP support. |
| [OpenCode v2 plugins](https://opencode.ai/v2/docs/plugins) | JavaScript, TypeScript, npm, and Git plugin installation. |
| [Build an OpenCode plugin](https://opencode.ai/v2/docs/build/plugins) | Plugin capabilities beyond MCP registration. |
