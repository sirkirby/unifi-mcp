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
  no-op patch releases when only plugin config or scripts change. Apply even
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
- `.agents/plugins/marketplace.json` (multi-target plugin registry: Claude, Codex, OpenClaw)
- `.codex-plugin/` (Codex-specific manifest directory, PR #246)
- `.agents/plugins/openclaw/` (OpenClaw-specific manifest directory, PR #248)

## Prerequisites

Before modifying any plugin configuration or transport code:

1. **Understand the uvx launch context.** When Claude launches a plugin via `uvx`, the plugin process is not PID 1. This distinction controls which transport path activates inside `transport.py` and whether HTTP transport will be enabled. The PID check is in `resolve_http_config()` in `transport.py`.
2. **Know all three app directories.** Transport and HTTP config changes almost always need to be reflected in `apps/network/`, `apps/protect/`, and `apps/access/` in parallel. Partial application leaves inconsistent behavior.
3. **Know all three plugin directories.** Script and setup changes apply to `plugins/unifi-network/`, `plugins/unifi-protect/`, and `plugins/unifi-access/`. Applying to only one or two creates inconsistent behavior that is nearly impossible for users to diagnose.
4. **Know the multi-target plugin registry and all three runtimes.** As of PR #246 (Codex) and PR #248 (OpenClaw), unifi-mcp supports three plugin targets: Claude, Codex, and OpenClaw. Plugin configuration, version sync, and release procedures must account for target-specific manifests and initialization paths.
5. **Hold the current MCP shared package version.** Plugin versions are slaved to MCP package tags; know the current tag before planning a release (see Procedure F).
6. **Run `check-prereqs.sh` first** (see Procedure D) before activating any plugin setup change in a live environment.

---

## Procedure A: UNIFI_MCP_HTTP_FORCE — Keep It at the Safe Default

### Where the flag lives

`UNIFI_MCP_HTTP_FORCE` is an environment variable consumed by each app's `config.yaml`. It maps to the `http.force` config key:

```yaml
# apps/network/src/unifi_network_mcp/config/config.yaml  (same pattern in protect, access)
http:
  enabled: ${oc.env:UNIFI_MCP_HTTP_ENABLED,true}
  force: ${oc.env:UNIFI_MCP_HTTP_FORCE,false}
  transport: ${oc.env:UNIFI_MCP_HTTP_TRANSPORT,streamable-http}
```

**The safe default is `false` (or unset).** Never set `UNIFI_MCP_HTTP_FORCE=true` in a uvx-launched context (non-PID-1). Setting it to `true` forces an HTTP bind attempt that is unavailable in the uvx sandbox.

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
- [ ] A no-op patch release is planned if config is the only change (see Procedure F)

---

## Procedure B: Transport Stability — Maintaining the Stdio-Primary Pattern

### The current safe pattern in `transport.py`

The current implementation in `packages/unifi-mcp-shared/src/unifi_mcp_shared/transport.py` uses stdio as the **primary control flow** — it runs to completion. HTTP runs as a **cancellable background task**. An HTTP failure must never cancel stdio. This pattern extends to **all transport targets** including Codex (PR #246) and OpenClaw (PR #248).

```python
# SAFE — current implementation (run_transports function)
http_task = asyncio.create_task(run_http(), name="http")
await asyncio.sleep(0)  # yield so http_task can start
try:
    await run_stdio()           # blocks until stdio EOF / client disconnect
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

Run each separately — the three plugins can have different prerequisite sets. A failure in `unifi-protect` does not imply a failure in `unifi-network`.

### Adding new prerequisites

When a plugin gains a new required environment variable or system dependency, add a check to `check-prereqs.sh` in the **same PR**:

```bash
# Pattern for a required variable with a helpful error message
if [ -z "${MY_NEW_VAR:-}" ]; then
  echo "ERROR: MY_NEW_VAR is not set. See README for setup instructions." >&2
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

macOS ships `/bin/bash` at version **3.2** (circa 2007). Homebrew may install a newer `bash`, but users run plugin scripts without Homebrew in their PATH. Any script in `plugins/` must work against the system shell. This constraint is documented in each `check-prereqs.sh`: "Bash 3.2 compatible (works on stock macOS /bin/bash)."

**`declare -A` (associative arrays) is bash 4+ only.** Using it in any `plugins/*/scripts/*.sh` causes a silent no-op or `unbound variable` error on macOS. The `set-env.sh` scripts use sed-based manipulation instead of associative arrays for exactly this reason (fixed in PR #202).

### POSIX-compatible alternatives for new scripts

If a new script needs key→value mapping:

```bash
# FAILS on macOS /bin/bash 3.2 — do not use
declare -A env_map
env_map["NETWORK_HOST"]="192.168.1.1"
echo "${env_map[NETWORK_HOST]}"
```

Replace with:

```bash
# Option 1 — case/esac dispatch
get_default() {
  case "$1" in
    NETWORK_HOST) echo "192.168.1.1" ;;
    NETWORK_PORT) echo "443" ;;
    *)            echo "" ;;
  esac
}
NETWORK_HOST="${NETWORK_HOST:-$(get_default NETWORK_HOST)}"

# Option 2 — explicit variable pairs (simplest for small sets)
NETWORK_HOST="${NETWORK_HOST:-192.168.1.1}"
NETWORK_PORT="${NETWORK_PORT:-443}"
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

## Procedure F: Plugin Version Sync — No-Op Patch Releases and Multi-Target Registry

### The versioning contract

Plugin versions are **strictly slaved** to MCP package release tags. The version referenced in plugin config must match a tagged MCP package version published to PyPI. There is no independent plugin version number.

### Multi-target plugin registry (PR #246, PR #248)

As of PR #246 (Codex) and PR #248 (OpenClaw), unifi-mcp supports **three plugin targets: Claude, Codex, and OpenClaw**. The multi-target registry lives in `.agents/plugins/marketplace.json`:

```json
{
  "claude": {
    "plugins": [
      {"name": "unifi-network", "version": "1.2.3"},
      {"name": "unifi-protect", "version": "1.2.3"},
      {"name": "unifi-access", "version": "1.2.3"}
    ]
  },
  "codex": {
    "plugins": [
      {"name": "unifi-network", "version": "1.2.3"},
      {"name": "unifi-protect", "version": "1.2.3"},
      {"name": "unifi-access", "version": "1.2.3"}
    ]
  },
  "openclaw": {
    "plugins": [
      {"name": "unifi-network", "version": "1.2.3"},
      {"name": "unifi-protect", "version": "1.2.3"},
      {"name": "unifi-access", "version": "1.2.3"}
    ]
  }
}
```

When a version bump is released, **all target registries** in `.agents/plugins/marketplace.json` must be updated in the same commit. Codex-specific manifests are in `.codex-plugin/` and OpenClaw-specific manifests are in `.agents/plugins/openclaw/` — these must be synchronized with the main app configs and the root marketplace.json entry.

### When only plugin config or scripts change

If a PR modifies only plugin manifests or scripts (no Python code changes in `shared/`), the correct release mechanism is a **no-op patch release**:

1. Bump the patch version in `packages/unifi-mcp-shared/pyproject.toml` (e.g., `1.2.3` → `1.2.4`).
2. Commit, tag, and push:
   ```bash
   git tag v1.2.4
   git push origin v1.2.4
   ```
3. Wait for the release pipeline to publish the wheel to PyPI. The Python wheel is functionally identical to the prior version — the bump exists solely to create a version anchor the plugin can reference.
4. **Atomically update version fields** in all target registries and manifests:
   - `.agents/plugins/marketplace.json` — all three target sections (claude, codex, openclaw) for all three plugins (network, protect, access)
   - `.codex-plugin/plugin.json` — version field in the Codex-specific manifest
   - `.agents/plugins/openclaw/plugin.json` — version field in the OpenClaw-specific manifest
   - `apps/network/src/unifi_network_mcp/config/config.yaml` — version string
   - `apps/protect/src/unifi_protect_mcp/config/config.yaml` — version string
   - `apps/access/src/unifi_access_mcp/config/config.yaml` — version string

5. **Workflow automation:** The `bump-plugin-versions.yml` CI workflow should atomically cover all three locations (marketplace.json root, .codex-plugin/plugin.json, .agents/plugins/openclaw/plugin.json) in a single workflow commit — do not bump them separately. Version skew between registry entries causes marketplace distribution inconsistencies.
6. Do **not** update the plugin version before the PyPI step completes (PyPI ordering gate — see `monorepo-release-pipeline` skill).

**Never skip the release for plugin-only changes.** Without a new tag, the plugin version field cannot advance, the config change has no anchored release identity, and existing users stay pinned to the cached old config until a tagged release forces cache invalidation.

### Change-type reference

| Change type | Release needed? | Release type |
|---|---|---|
| Python code change in `shared/` | Yes | Functional patch / minor / major |
| HTTP transport config change only | Yes | No-op patch |
| `check-prereqs.sh` or `set-env.sh` change | Yes | No-op patch |
| Plugin skill SKILL.md change | Yes | No-op patch |
| Codex manifest or `.codex-plugin/` change | Yes | No-op patch |
| OpenClaw manifest or `.agents/plugins/openclaw/` change | Yes | No-op patch |
| Multi-target registry (.agents/plugins/marketplace.json) change | Yes | No-op patch |
| README / docs only | No | — |

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

### Version sync atomicity — Marketplace registry must stay consistent

The `.agents/plugins/marketplace.json` root registry, `.codex-plugin/plugin.json`, and `.agents/plugins/openclaw/plugin.json` must have matching version strings. If a release bumps only `.agents/plugins/marketplace.json` but forgets the target-specific manifests, the Codex and OpenClaw plugins will keep referencing the old version while the marketplace registry has advanced. This creates version skew that manifests as "tool unavailability for OpenClaw users while Codex works fine" — a confusing symptom that points to version mismatch, not transport issues. Always update all three registry locations atomically.

### Skill-dir naming collision — Manifest registration gotcha

The `.agents/skills/*/` directory structure can collide with plugin name patterns if not carefully scoped. Plugin skill manifests registered in `.agents/plugins/*/skills/*/` must use fully qualified names (e.g., `unifi-mcp:skill-name`) to avoid colliding with agent-owned skills. Always verify that a new plugin skill manifest's fully qualified name does not collide with existing agent or plugin skill names. Test on all three targets (Claude, Codex, OpenClaw) — skill resolution may differ by target.
