---
name: myco:claude-plugin-config
description: |
  Covers plugin configuration, transport stability, local development workflow,
  and release lifecycle for the three Claude MCP plugins in this repo
  (unifi-network, unifi-protect, unifi-access). Apply this skill when modifying
  plugin.json files, changing transport.py asyncio patterns, writing or auditing
  shell scripts in plugins/unifi-*/scripts/, verifying a local plugin load against
  the marketplace cache, or cutting a release for plugin-only config changes —
  even if the user does not explicitly ask about plugin stability or MCP transport
  architecture.
  Procedures: (1) set UNIFI_MCP_HTTP_FORCE correctly in plugin.json,
  (2) maintain the stdio-primary transport pattern in transport.py,
  (3) distinguish claude --plugin-dir from marketplace installs during local dev,
  (4) run check-prereqs.sh before plugin activation changes,
  (5) keep shell scripts Bash 3.2-compatible for macOS, and
  (6) issue no-op patch releases when only plugin.json changes.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Claude Plugin Configuration and Transport Stability

This skill covers the end-to-end lifecycle of the three Claude MCP plugins (`unifi-network`, `unifi-protect`, `unifi-access`) — from local development to production release. The plugin JSON manifests, transport asyncio patterns, setup scripts, and version sync rules are tightly coupled; changing one without understanding the others causes silent failures that are hard to diagnose.

Canonical plugin directories: `plugins/unifi-network/`, `plugins/unifi-protect/`, `plugins/unifi-access/`. Each contains `plugin.json` (gitignored — Claude Code plugin manifest), `scripts/set-env.sh`, and `scripts/check-prereqs.sh`. The shared transport lives at `packages/unifi-mcp-shared/src/unifi_mcp_shared/transport.py`.

## Prerequisites

Before any procedure in this domain:

1. **Understand the uvx launch context.** `uvx` launches the MCP server as a subprocess — it is not PID 1. Flags that change transport binding behavior behave differently here than in a direct `python` invocation. This matters for every procedure below.
2. **Touch all three plugins when changing shared flags.** `plugin.json` flags are duplicated across `unifi-network`, `unifi-protect`, and `unifi-access`. A bug introduced in one is almost always present in all three.
3. **Run `git fetch` before diagnosing.** Several issues in this area appeared as CI or config problems but were just stale local state.
4. **Release mechanics are in `monorepo-release-pipeline`.** This skill covers *when and why* a plugin release is needed; the other skill handles tag ordering and PyPI sequencing.

## Procedure 1: Set UNIFI_MCP_HTTP_FORCE in plugin.json

### The flag

Every `plugins/unifi-*/plugin.json` contains `UNIFI_MCP_HTTP_FORCE` in its environment variable section. This env var is read by the app server's `config.yaml` via `force: ${oc.env:UNIFI_MCP_HTTP_FORCE,false}` (e.g., `apps/network/src/unifi_network_mcp/config/config.yaml`). It controls whether the MCP server attempts to bind an HTTP transport alongside stdio.

**The correct value is `"false"` in all three plugin configs.**

```jsonc
// plugins/unifi-network/plugin.json  (same pattern in unifi-protect, unifi-access)
{
  "env": {
    "UNIFI_MCP_HTTP_FORCE": "false"
  }
}
```

### Why `"true"` causes silent tool loss

Setting `UNIFI_MCP_HTTP_FORCE=true` causes the server to call `run_http()` (defined in `transport.py`). In a uvx-launched context the HTTP bind fails. `run_http()` catches the resulting `SystemExit` and **returns normally** — no exception propagates.

The old transport implementation used `asyncio.wait(FIRST_COMPLETED)`, which saw the HTTP task complete and cancelled the still-running stdio task. The server appeared to start; all tools disappeared silently. No error was logged. This pattern has been replaced (see Procedure 2), but the root cause starts here: `UNIFI_MCP_HTTP_FORCE=true` in a uvx context triggers the failure chain.

### Verification

```bash
# All three should show "false"
grep -r "UNIFI_MCP_HTTP_FORCE" plugins/unifi-network/plugin.json plugins/unifi-protect/plugin.json plugins/unifi-access/plugin.json
```

If any shows `"true"`, fix it in all three and issue a plugin-only release (see Procedure 6).

## Procedure 2: Maintain the Stdio-Primary Transport Pattern

### The pattern

File: `packages/unifi-mcp-shared/src/unifi_mcp_shared/transport.py`

**Stdio is the primary control flow** — the server's lifecycle is tied to the stdio task running to completion. **HTTP runs as a cancellable background task.** An HTTP failure (bind error, port conflict) does not cancel stdio.

### Why `asyncio.wait(FIRST_COMPLETED)` is unsafe here

`FIRST_COMPLETED` cannot distinguish "HTTP finished its job" from "HTTP swallowed an error and returned." Because `run_http()` catches `SystemExit` internally and converts it to a clean return, `asyncio.wait` treats a bind failure as task success — then cancels stdio. All tools disappear.

The fix replaced `asyncio.wait(FIRST_COMPLETED)` with an explicit stdio-primary flow. The current implementation at lines 165–168 of `transport.py` is:

```python
# Correct: stdio drives lifecycle; HTTP is a cancellable background task
http_task = asyncio.create_task(run_http(), name="http")
await asyncio.sleep(0)   # yield so http_task starts
try:
    await run_stdio()    # primary — runs to completion
finally:
    http_task.cancel()
    ...
```

Do **not** revert to `asyncio.wait(FIRST_COMPLETED)` when one task can "succeed" by swallowing an exception.

### Regression test targets

When modifying `transport.py`:
1. **Mock race test** — mock `run_http()` to raise `SystemExit`; verify stdio keeps running.
2. **E2E repro** — bind a TCP listener on the HTTP port before starting the server; confirm MCP tools remain accessible via stdio after the HTTP bind fails.

### Adding a new transport type

If adding a third transport (e.g., SSE):
- Treat it as a cancellable background task, same as HTTP.
- Never add it to the primary `await` path.
- Add a mock race test for it.
- Inspect task exceptions explicitly; do not rely on `FIRST_COMPLETED` to detect failure.

## Procedure 3: Local Plugin Development — `--plugin-dir` vs. Marketplace Cache

### The local dev flag

```bash
claude --plugin-dir plugins/unifi-network
```

`--plugin-dir <path>` loads a plugin from a local directory, bypassing marketplace publishing. It is the canonical flag for iterating on `plugin.json` changes.

### The marketplace cache blind spot

`--plugin-dir` bypasses marketplace publishing, but it does **not** guarantee the local version takes precedence if Claude has a marketplace-installed version of the same plugin cached. Both can coexist, and the marketplace-installed config may win.

A `plugin.json` change that looks correct under `--plugin-dir` may not reflect what a marketplace-installed user experiences.

### Verification steps

1. Load with `--plugin-dir` and confirm the expected behavior.
2. Check whether a conflicting marketplace-installed version is cached:
   ```bash
   # macOS example — path varies by platform
   find ~/Library/Application\ Support/Claude -name "plugin.json" 2>/dev/null
   ```
3. If a cached marketplace version exists with conflicting flags, remove the cache entry or test a full publish-and-install cycle on a branch.
4. Before shipping: always validate behavior via a full marketplace install, not just `--plugin-dir`.

### What `--plugin-dir` does and does not substitute for

| Does | Does not |
|---|---|
| Loads local plugin.json | Replace a marketplace install test |
| Skips marketplace publish wait | Override a cached marketplace config |
| Fast iteration on manifest changes | Validate the uvx invocation path end-to-end |

## Procedure 4: Plugin Setup Verification — `check-prereqs.sh`

### Purpose

`plugins/unifi-*/scripts/check-prereqs.sh` validates system state before plugin activation. It catches the most common silent setup failures before they produce user-facing errors:

1. **uvx availability** — the MCP server is launched via uvx; if it's missing, tools never appear
2. **Settings JSON validity** — validates `.claude/settings.local.json` before set-env.sh modifies it
3. **macOS Python entitlement** — uv's managed Python builds lack `com.apple.security.network.client`; an entitlement-less interpreter starts the server cleanly but silently fails every controller call with errno 65

### When to run it

Run the relevant `check-prereqs.sh` before:
- Activating a modified plugin
- Troubleshooting "plugin loads but tools fail" reports
- Merging changes to plugin setup scripts or environment variable handling

```bash
bash plugins/unifi-network/scripts/check-prereqs.sh
```

### Extending it

When a new plugin procedure introduces a new prerequisite (new required binary, new system state check, new endpoint):

1. Add a check to `check-prereqs.sh` in the relevant plugin(s).
2. Write clear, actionable error messages — not just exit codes.
3. Verify the failure message by simulating the failure condition and running the script.
4. If the prerequisite applies to all three plugins, add it to all three files.

```bash
# Pattern for a new required binary
if ! command -v some-tool >/dev/null 2>&1; then
  echo "  [FAIL] some-tool not found on PATH" >&2
  echo "         Install with: brew install some-tool" >&2
  errors=$((errors + 1))
fi
```

Keep checks minimal and specific. Do not add checks for conditions that Claude or uvx will surface with their own errors.

## Procedure 5: Shell Script Portability — Bash 3.2 on macOS

### The constraint

macOS ships `/bin/bash` at version **3.2** (circa 2007). This is the shell that runs `plugins/unifi-*/scripts/*.sh` on most developer machines. **Bash 4+ features are unavailable.**

The most common failure:

```bash
# BROKEN on macOS /bin/bash — bash 4+ only:
declare -A my_map
my_map["key"]="value"
# Result: "unbound variable" or silent no-op — no clear error
```

### POSIX-compatible alternatives

**`case/esac` for lookup tables:**
```bash
get_endpoint() {
  case "$1" in
    unifi-network) echo "https://${UNIFI_HOST}/proxy/network" ;;
    unifi-protect) echo "https://${UNIFI_HOST}/proxy/protect" ;;
    unifi-access)  echo "https://${UNIFI_HOST}/proxy/access"  ;;
    *) echo "unknown" ;;
  esac
}
```

**Hardcoded variable pairs** when the map is small and static:
```bash
NETWORK_ENDPOINT="https://${UNIFI_HOST}/proxy/network"
PROTECT_ENDPOINT="https://${UNIFI_HOST}/proxy/protect"
ACCESS_ENDPOINT="https://${UNIFI_HOST}/proxy/access"
```

### Verification rule

Test every new script in `plugins/` against `/bin/bash` explicitly:

```bash
/bin/bash plugins/unifi-network/scripts/set-env.sh
/bin/bash plugins/unifi-protect/scripts/check-prereqs.sh
```

Do not use `bash` from Homebrew for this test — it is 5.x and will not catch 3.2 incompatibilities even if `#!/usr/bin/env bash` points to it.

```bash
/bin/bash --version   # 3.2.x on stock macOS
bash --version        # may be 5.x if Homebrew bash is on PATH
```

### Audit shortcut

When reviewing any new shell script:

```bash
# Grep for common bash 4+ patterns
grep -n 'declare -A\|declare -a\|mapfile\|readarray' plugins/unifi-*/scripts/*.sh
```

Zero results is the goal.

## Procedure 6: Plugin Version Sync — No-Op Patch Releases

### The rule

Plugin versions are **strictly slaved to the MCP package release tags**. The `plugin.json` version field must match the tagged MCP package version on PyPI.

When **only** `plugin.json` changes (no Python code changes in `packages/`), issue a **no-op patch release**:

1. Bump the version in the relevant `pyproject.toml` (patch increment only).
2. The Python wheel is functionally identical to the prior release.
3. Tag and publish via the normal pipeline (see `monorepo-release-pipeline`).
4. Update the `plugin.json` version field to match the new tag.

**Never skip the release.** Without a version bump, users with the old plugin version have no signal that a reconfiguration is available.

### When this applies

Issue a no-op patch release when changing:
- Flag values in `plugin.json` (e.g., `UNIFI_MCP_HTTP_FORCE`)
- Environment variable defaults or names in `plugin.json`
- Plugin capability declarations in `plugin.json`

It does **not** apply to `plugins/unifi-*/scripts/` changes — those are local setup helpers, not packaged artifacts.

### Step-by-step

```bash
# 1. Make the plugin.json change across all affected plugins
# 2. Bump pyproject.toml version (patch increment, e.g., 0.4.2 → 0.4.3)
# 3. Commit both together
git add plugins/unifi-network/plugin.json packages/unifi-mcp-network/pyproject.toml
git commit -m "chore: bump plugin version to 0.4.3 (fix UNIFI_MCP_HTTP_FORCE)"
# 4. Follow monorepo-release-pipeline for tag ordering and PyPI publish
```

The PyPI ordering gate (shared package published before consumers) applies even for no-op releases. Re-tagging an existing release is not an option — PyPI releases are immutable.

### Why not re-use the current tag?

A no-op patch release is cheap, auditable, and unambiguous. The wheel content is identical; what changes is the signal to plugin consumers that a manifest update has occurred. Re-using a tag would break reproducibility and violate PyPI immutability.

## Cross-Cutting Gotchas

**Silent tool disappearance is the common failure mode.** When MCP tools vanish after a plugin change, check in order:
1. `UNIFI_MCP_HTTP_FORCE` in all three `plugin.json` files — must be `"false"`
2. `transport.py` for `asyncio.wait(FIRST_COMPLETED)` — replace with stdio-primary pattern
3. Whether `--plugin-dir` is loading the right version vs. a cached marketplace config

**All three plugins share the same flags.** Fix all three when any flag value is wrong; grep all of them before closing a bug.

**Bash 3.2 failures are silent.** A script that fails due to `declare -A` on macOS may not error loudly — it silently omits the intended configuration. `/bin/bash` testing is non-negotiable.

**No-op releases follow the full pipeline.** The tag ordering and PyPI sequencing constraints from `monorepo-release-pipeline` apply even when the Python wheel is unchanged. Don't shortcut the release process.

**macOS Python entitlement is a silent killer.** A server that starts cleanly and registers all tools but returns "Not connected to controller" on every call is the entitlement symptom — `check-prereqs.sh` catches this before user-facing failure.
