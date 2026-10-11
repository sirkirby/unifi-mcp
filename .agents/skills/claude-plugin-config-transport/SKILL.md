---
name: myco:claude-plugin-config-transport
description: >-
  Activate when working on Claude plugin configuration, MCP transport behavior,
  or plugin release mechanics in unifi-mcp. Covers: keeping UNIFI_MCP_HTTP_FORCE
  at its safe default in apps/*/config/config.yaml for all three apps (network,
  protect, access); the stdio-primary transport pattern in transport.py and why
  asyncio.wait(FIRST_COMPLETED) must not be reintroduced; local development
  with claude --plugin-dir and its marketplace-cache blind spot; running
  check-prereqs.sh before plugin setup; writing Bash 3.2-compatible shell
  scripts for plugins/; multi-target plugin support for Claude, Codex, and
  OpenClaw targets; atomic version sync across plugin manifests; and issuing
  independent plugin bumps when shipped config, skills or scripts change. Apply even
  if the user doesn't explicitly mention transport races — activate whenever
  plugin behavior, MCP tool availability, or plugin-scoped shell scripts are
  being modified.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Claude Plugin Configuration and Transport Stability

This skill covers the full lifecycle of Claude MCP plugin integration in unifi-mcp: from configuring transport flags correctly, through understanding the asyncio transport architecture that keeps MCP tools available, to verifying plugin setup, writing portable shell scripts, and publishing plugin-only releases. The procedures share a common prerequisite — understanding the uvx launch context — because a wrong flag can trigger a transport race that silently drops all MCP tools with no visible error.

**Relevant files:**
- `apps/network/src/unifi_network_mcp/config/config.yaml`
- `apps/protect/src/unifi_protect_mcp/config/config.yaml`
- `apps/access/src/unifi_access_mcp/config/config.yaml`
- `plugins/unifi-network/scripts/set-env.sh`, `plugins/unifi-network/scripts/check-prereqs.sh`
- `plugins/unifi-protect/scripts/set-env.sh`, `plugins/unifi-protect/scripts/check-prereqs.sh`
- `plugins/unifi-access/scripts/set-env.sh`, `plugins/unifi-access/scripts/check-prereqs.sh`
- `packages/unifi-mcp-shared/src/unifi_mcp_shared/transport.py`
- `packages/unifi-mcp-shared/src/unifi_mcp_shared/strict_dispatch.py`
- `.agents/plugins/marketplace.json` (multi-target plugin registry: Claude, Codex, OpenClaw)
- `.codex-plugin/` (Codex-specific manifest directory, PR #246)
- `.agents/plugins/openclaw/` (OpenClaw-specific manifest directory, PR #248)

## Prerequisites

Before modifying any plugin configuration or transport code:

1. **Understand the uvx launch context.** When Claude launches a plugin via `uvx`, the plugin process is not PID 1. This distinction controls which transport path activates inside `transport.py` and whether HTTP transport will be enabled. The PID check is in `resolve_http_config()` in `transport.py`.
2. **Know all three app directories.** Transport and HTTP config changes almost always need to be reflected in `apps/network/`, `apps/protect/`, and `apps/access/` in parallel. Partial application leaves inconsistent behavior.
3. **Know all three plugin directories.** Script and setup changes apply to `plugins/unifi-network/`, `plugins/unifi-protect/`, and `plugins/unifi-access/`. Applying to only one or two creates inconsistent behavior that is nearly impossible for users to diagnose.
4. **Know the multi-target plugin registry and all three runtimes.** As of PR #246 (Codex) and PR #248 (OpenClaw), unifi-mcp supports three plugin targets: Claude, Codex, and OpenClaw. Plugin configuration, version sync, and release procedures must account for target-specific manifests and initialization paths.
5. **Distinguish plugin versions from server pins.** Bump the plugin for every shipped-file change; product tags move pins automatically (see Procedure F).
6. **Run `check-prereqs.sh` first** (see Procedure D) before activating any plugin setup change in a live environment.

---

## Procedure A: UNIFI_MCP_HTTP_FORCE — Keep It at the Safe Default

### Where the flag lives

`UNIFI_MCP_HTTP_FORCE` is an environment variable consumed by each app's `config.yaml`. It maps to the `http.force` config key:

```yaml
# apps/network/src/unifi_network_mcp/config/config.yaml  (same pattern in protect, access)
http:
  enabled: ${oc.env:UNIFI_MCP_HTTP_ENABLED,false}
  force: ${oc.env:UNIFI_MCP_HTTP_FORCE,false}
  transport: ${oc.env:UNIFI_MCP_HTTP_TRANSPORT,streamable-http}
```

**The safe default is `false` (or unset).** Never set `UNIFI_MCP_HTTP_FORCE=true` in a uvx-launched context (non-PID-1). Setting it to `true` forces an HTTP bind attempt that is unavailable in the uvx sandbox.

HTTP is separately opt-in through `UNIFI_MCP_HTTP_ENABLED=true` and binds to loopback by default. Remote access requires an authenticated TLS proxy or Cloud Relay; do not restore an enabled-by-default or wildcard listener in packaged configuration.

### Why `UNIFI_MCP_HTTP_FORCE=true` silently destroys all MCP tools

The failure chain when `UNIFI_MCP_HTTP_FORCE=true` in a uvx-launched (non-PID-1) context:

1. HTTP bind is unavailable in the uvx sandbox.
2. `run_http()` in `transport.py` catches the `SystemExit` from the failed bind and **returns normally** — no exception propagates.
3. The pre-fix `asyncio.wait(FIRST_COMPLETED)` implementation saw the HTTP task as "done" and interpreted normal return as success.
4. FIRST_COMPLETED cancelled the stdio task (the only transport Claude actually uses).
5. **All MCP tools disappeared silently.** Claude showed no error; the tools were simply gone.

This was the root cause of Issue #200, fixed in PR #202. The fix required changes in two places: the config flag handling AND the asyncio transport pattern (see Procedure B).

### Checklist when changing HTTP transport config

- [ ] Change applied in all three: `apps/network/`, `apps/protect/`, `apps/access/` config.yaml files
- [ ] `UNIFI_MCP_HTTP_FORCE` value is `false` (or the env var is unset) for all uvx-launched contexts
- [ ] No environment variable injection is setting it to `true` in the plugin setup path
- [ ] An independent plugin bump accompanies any shipped-file change (see Procedure F)

---

## Procedure B: Transport Stability — Maintaining the Stdio-Primary Pattern

### The current safe pattern in `transport.py`

The current implementation in `packages/unifi-mcp-shared/src/unifi_mcp_shared/transport.py` uses stdio as the **primary control flow** — it runs to completion. HTTP runs as a **cancellable background task**. An HTTP failure must never cancel stdio. This pattern extends to **all transport targets** including Codex (PR #246) and OpenClaw (PR #248).

```python
# SAFE — current implementation (run_transports function)
http_task = asyncio.create_task(run_http(), name="http")
await asyncio.sleep(0)  # yield so http_task can start
try:
    await run_stdio()  # blocks until stdio EOF / client disconnect
    logger.info("FastMCP stdio server exited.")
finally:
    if not http_task.done():
        http_task.cancel()
        try:
            await http_task
        except asyncio.CancelledError:
            pass
```

`run_http()` catches its own `SystemExit` internally (port-bind failures from uvicorn), so a failed HTTP transport returns normally rather than propagating. Stdio lifecycle is unaffected. This design assumes the transport target (Claude, Codex, OpenClaw) uses stdio as the primary transport and HTTP as optional.

### What NOT to do — the pre-fix anti-pattern

Do not replace the above pattern with `asyncio.wait(FIRST_COMPLETED)`:

```python
# UNSAFE — do not reintroduce this pattern
done, pending = await asyncio.wait(
    {stdio_task, http_task},
    return_when=asyncio.FIRST_COMPLETED,
)
for task in pending:
    task.cancel()  # cancels stdio if http_task "succeeds" silently
```

`asyncio.wait(FIRST_COMPLETED)` is unsafe when any task can "succeed" by swallowing its own error. A task that catches an exception internally and returns `None` looks identical to a task that completed successfully. This was the pre-#202 implementation — it is described in the docstring of `run_transports()` as "the previous implementation."

**Design rules for transport code:**
- Stdio EOF / client disconnect is the authoritative shutdown signal.
- Never use `FIRST_COMPLETED` across transport tasks where either task can swallow errors.
- Use explicit exception inspection or a sentinel flag to distinguish "HTTP successfully bound and serving" from "HTTP failed silently."
- HTTP errors must not propagate to the stdio lifecycle.

### Regression test strategy

Two-layer verification after any transport change:

1. **Mock race test** — unit test that forces `run_http()` to catch and swallow a `SystemExit`, then asserts that the stdio task was **not** cancelled and ran to completion.
2. **E2E repro** — bind a TCP listener on the HTTP port before launching the plugin so the HTTP bind fails, then verify MCP tools remain available throughout the stdio session.

---

## Procedure C: Local Plugin Development — `claude --plugin-dir` and the Marketplace Cache

### The canonical local-dev flag

```bash
claude --plugin-dir <path/to/plugins/unifi-network>
```

This loads the plugin directly from the local directory, bypassing the marketplace install step. It is the correct flag for iterating on plugin scripts or skills without publishing a release.

### The marketplace cache blind spot

`--plugin-dir` does **not** deactivate a marketplace-installed version of the same plugin. If a marketplace-installed version has a conflicting config cached, it may take precedence over the local-dir version, or the two configs may interfere with each other in unpredictable ways.

**To confirm the correct plugin is active:**

```bash
# 1. Check which binary Claude is actually running
ps aux | grep unifi-mcp

# 2. Diff local scripts against the marketplace-installed versions
ls plugins/unifi-network/scripts/
# Compare against marketplace cache (location varies by OS — check Claude's
# plugin data directory)

# 3. If behavior doesn't match local config, temporarily uninstall the
#    marketplace version and re-test with --plugin-dir alone
```

### What `--plugin-dir` does NOT substitute for

- A **marketplace install test** — always do a final end-to-end test through the marketplace path before shipping a release.
- The `check-prereqs.sh` pre-flight (Procedure D).
- Version verification — the plugin version shown in Claude may reflect the marketplace-installed version, not the local-dir version.

---

## Procedure D: Plugin Setup Verification — `check-prereqs.sh` Pre-flight

### What it does

`plugins/unifi-*/scripts/check-prereqs.sh` validates required environment variables and system state before plugin activation. It catches missing credentials and misconfigured endpoints before they produce cryptic user-facing failures. The scripts explicitly state Bash 3.2 compatibility. OpenClaw plugins have identical prerequisites to Claude and Codex — the check-prereqs.sh scripts are target-agnostic.

### When to run it

Run before activating any plugin setup change:

```bash
bash plugins/unifi-network/scripts/check-prereqs.sh
bash plugins/unifi-protect/scripts/check-prereqs.sh
bash plugins/unifi-access/scripts/check-prereqs.sh
```

On Windows, each plugin's `scripts/` directory also provides a PowerShell prereq companion script. Consult the plugin's runtime SKILL.md manifest for the exact invocation — it accepts a `-Target <claude|codex|openclaw>` parameter and `-PluginName` flag.

Run each plugin separately — the three plugins can have different prerequisite sets. A failure in `unifi-protect` does not imply a failure in `unifi-network`.

### Adding new prerequisites

When a plugin gains a new required environment variable or system dependency, add a check to both the `.sh` and the PowerShell companion script in the **same PR**:

```bash
# Pattern for a required variable with a helpful error message
if [ -z "${NEW_VAR:-}" ]; then
  echo "ERROR: NEW_VAR is not set. See README for setup instructions." >&2
  exit 1
fi

# Pattern for a required command
if ! command -v my-tool >/dev/null 2>&1; then
  echo "ERROR: my-tool is not installed." >&2
  exit 1
fi
```

Do not rely on the plugin process itself to surface missing prerequisites — process-level errors are much harder to diagnose than a clean pre-flight failure with a human-readable message.

---

## Procedure E: Shell Script Portability — Bash 3.2 on macOS

### The constraint

macOS ships `/bin/bash` at version **3.2** (circa 2007). Homebrew may install a newer `bash`, but users run plugin scripts without Homebrew in their PATH. Any `.sh` script in `plugins/` must work against the system shell. This constraint is documented in each `check-prereqs.sh`: "Bash 3.2 compatible (works on stock macOS /bin/bash)."

**On Windows, use PowerShell (`.ps1`) — not `.sh`.** Each plugin's `scripts/` directory provides PowerShell equivalents for environment setup and prereq checking. Never add `.sh` scripts that assume a bash version higher than 3.2 and expect them to work on macOS.

**`declare -A` (associative arrays) is bash 4+ only.** Using it in any `plugins/*/scripts/*.sh` causes a silent no-op or `unbound variable` error on macOS. The `set-env.sh` scripts use sed-based manipulation instead of associative arrays for exactly this reason (fixed in PR #202).

### POSIX-compatible alternatives for new scripts

If a new script needs key→value mapping:

```bash
# Option 1 — case/esac dispatch
get_default() {
  case "$1" in
    FOO_HOST) echo "192.168.1.1" ;;
    FOO_PORT) echo "443" ;;
    *)        echo "" ;;
  esac
}
FOO_HOST="${FOO_HOST:-$(get_default FOO_HOST)}"

# Option 2 — explicit variable pairs (simplest for small sets)
FOO_HOST="${FOO_HOST:-192.168.1.1}"
FOO_PORT="${FOO_PORT:-443}"
```

### Verification rule for new plugin scripts

Every new shell script added to `plugins/` must be tested against the **system bash**, not Homebrew bash:

```bash
# Syntax check
/bin/bash -n plugins/unifi-network/scripts/my-new-script.sh

# Runtime check
/bin/bash plugins/unifi-network/scripts/my-new-script.sh
```

If CI runs on Linux, add a macOS job or test locally — Linux bash is almost always 4+, so CI will not catch 3.2 incompatibilities.

---

## Procedure F: Independent Plugin Versions and Pin Writebacks

Each plugin has an independent semantic version describing everything it ships,
separate from the server package pin. Set the same `version` in every existing
Claude and Codex manifest; require at least one manifest. The unlisted
`cross-product` bundle follows these rules with its Claude manifest only.
Keep `version` out of marketplace entries.

Bump every affected plugin in the same PR whenever any file under
`plugins/<name>/` changes, including skills, setup scripts, MCP configs and docs.
Use patch for plugin-only fixes or docs; minor for new skills/capabilities or a
minor server pin move; major for breaking setup/configuration or a major server
pin move. Patch server moves use patch. Before 1.0, breaking changes advance the
minor and additive changes advance the patch (SemVer 0.x). All four plugins start
at 1.0.0 when independent versioning is introduced.

`bump-plugin-versions.yml` automatically moves both client pins and bumps the
plugin by the size of a released server change, preserving the independent
plugin version line. It also updates an inline Claude pin when present and
regenerates `apps/<product>/server.json` with the **server** version. Core, Shared
and Relay triggers keep their existing behavior: coalesce any outstanding product
tags, otherwise produce no writeback. Plugin-only changes need a manifest bump
and merge; no Python package release is needed.

Run `make check-plugin-versions` before committing. It uses
`scripts/plugin_versions.py check --base origin/main`, also run by
`make pre-commit`; PR CI uses the PR base SHA's merge base. Fetch base history and
tags first. A missing base fails. Changed plugin versions must be valid SemVer,
agree across existing manifests and exceed the merge-base version. Client pins
must agree and name release tags; only the workflow's exact `--releasing` tag may
stand in for a tag not yet discovered locally. Version-only bumps are allowed.

---

## Cross-Cutting Gotchas

### Silent tool loss is the hardest failure mode to diagnose

When all MCP tools disappear after a plugin or transport change, the natural instinct is to check credentials or network connectivity. **Check `UNIFI_MCP_HTTP_FORCE` (is it set to `true` somewhere?) and the transport pattern in `transport.py` first.** The stdio cancellation failure surfaces no error to Claude or the user — tools simply stop appearing in the tool list.

### Both layers must be fixed together

The Issue #200 / PR #202 fix required changes in two places:
- `apps/*/config/config.yaml` — ensure `UNIFI_MCP_HTTP_FORCE` is not forced to `true` in non-PID-1 contexts
- `transport.py` — the stdio-primary pattern prevents a swallowed HTTP failure from cancelling stdio

If you are investigating a transport issue, always audit both the config flag injection path and the asyncio pattern before concluding the fix is complete.

### Three-app and three-plugin parity is non-negotiable

Config changes to HTTP transport behavior must be applied to all three apps (`network`, `protect`, `access`). Script changes must be applied to all three plugin directories (`unifi-network`, `unifi-protect`, `unifi-access`). Partial application produces inconsistent behavior depending on which app/plugin the user has installed.

### `--plugin-dir` local tests are necessary but not sufficient

A passing local test with `--plugin-dir` does not guarantee the marketplace-installed version behaves the same way. Always do a final marketplace-path test before shipping, especially after config or script changes.

### Three-runtime transport pattern — Claude, Codex, and OpenClaw

The three plugin targets (Claude, Codex, and OpenClaw) have identical transport initialization patterns. Changes to `transport.py` apply to all three; transport-specific gotchas that were previously labeled as Codex-only (PR #246) now apply equally to OpenClaw (PR #248). When debugging transport issues, test against all three runtime targets if possible — a transport bug may surface in one target before appearing in others due to timing or initialization order differences.

### Version and pin atomicity

Update existing Claude and Codex manifest versions together. The package pin in
`.mcp.json`, `.mcp.codex.json` and any inline Claude `mcpServers` stays identical
across clients, independent of the plugin version. Marketplace entries carry no
`version`. Re-run Codex setup with `--refresh` after a plugin upgrade to update
its separate saved MCP entry.

### Skill-dir naming collision — Manifest registration gotcha

The `.agents/skills/*/` directory structure can collide with plugin name patterns if not carefully scoped. Plugin skill manifests registered in `.agents/plugins/*/skills/*/` must use fully qualified names (e.g., `unifi-mcp:skill-name`) to avoid colliding with agent-owned skills. Always verify that a new plugin skill manifest's fully qualified name does not collide with existing agent or plugin skill names. Test on all three targets (Claude, Codex, OpenClaw) — skill resolution may differ by target.

### Redaction awareness — never echo `***REDACTED***` markers into mutation args (PR #350)

As of PR #350, all plugin tool responses redact sensitive fields by default — Wi-Fi passphrases, VPN private/preshared keys, SNMP community strings, and Access credential token/PIN values are replaced with `***REDACTED***` in read, list, and preview responses.

**When you need an unredacted value for a write operation:** Pass `include_sensitive=true` to the relevant read tool first to retrieve the real value, then use that value in the mutation call.

**Never feed a `***REDACTED***` string back into a mutation argument.** `StrictKwargFastMCP` (in `packages/unifi-mcp-shared/src/unifi_mcp_shared/strict_dispatch.py`) rejects `tools/call` requests that pass a redaction marker as an argument value. The rejection may not surface a clear diagnostic to the agent — the tool call fails without indicating that a redacted placeholder was the cause. This guard prevents accidental passthrough of masked values into real API writes.

**Affected workflows:** WLAN passphrase updates, VPN key rotation, SNMP community string changes, Access credential token/PIN mutations. Plugin skills that guide agents through these workflows must explicitly mention the `include_sensitive=true` pattern — agents that rely on a prior read response and pass the field value through verbatim will hit this guard.
