---
name: myco:monorepo-release-pipeline
description: >-
  Covers the full release pipeline for the unifi-mcp monorepo: determining release scope by
  analyzing changed packages, scoping hatch-vcs version tag globs per Python package to prevent
  sibling-tag contamination, pushing tags in strict dependency order (unifi-core → unifi-mcp-shared
  → app servers → relay → worker when needed), configuring scripts/generate_release_notes.py
  path scoping per package, wiring per-package publish workflows for OIDC trusted publishing,
  coordinating cross-package version bumps in pyproject.toml, understanding app vs. library
  versioning and writeback behavior, validating releases post-tag, and verifying shared package
  architecture constraints (DI-only rule, scope gate, relay sync) before releasing shared packages.
  Apply when cutting any release, bumping unifi-core, or debugging a versioning failure.
  CRITICAL: All PRs require pin-alignment CI gate before merge (automated, cannot be skipped).
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Monorepo Release Pipeline

The unifi-mcp repo ships seven independently versioned Python packages plus the
Node/TypeScript worker app: `unifi-core`
and `unifi-mcp-shared` live under `packages/`; `unifi-network-mcp`, `unifi-protect-mcp`,
`unifi-access-mcp`, and `unifi-api-server` live under `apps/`; `unifi-mcp-relay` lives under `packages/`
alongside core and shared; `unifi-mcp-worker` lives under `apps/worker/` and publishes to npm.
Each has its own package identity, tag namespace, publish workflow, and release-notes scope. Getting the release sequence wrong leaves downstream
packages referencing non-existent PyPI versions or produces contaminated release notes
that bleed across package boundaries.

## Prerequisites

- All feature PRs for the release are merged to `main`.
- **All PRs targeting main must pass the pin-alignment CI gate (automated blocker).** This gate
  runs on every PR and blocks stale transitive dependency pins that would cause fresh
  installs to fail. See Procedure D, Step 0 for details.
- Working tree is clean: `git status` shows nothing staged or modified.
- Remote is current: `git fetch origin && git log origin/main..HEAD` shows nothing.
- PyPI credentials are **not** stored locally — publishing is handled entirely by
  GitHub Actions OIDC trusted publishing (no `TWINE_PASSWORD`, no `PYPI_TOKEN`).
- Decide which packages are changing and their new versions before pushing any tag.

## Package Map

| Package | Directory | PyPI Name | Tag namespace |
|---|---|---|---|
| `unifi-core` | `packages/unifi-core/` | `unifi-core` | `core/v*` |
| `unifi-mcp-shared` | `packages/unifi-mcp-shared/` | `unifi-mcp-shared` | `shared/v*` |
| `unifi-mcp-network` | `apps/network/` | `unifi-network-mcp` | `network/v*` |
| `unifi-mcp-protect` | `apps/protect/` | `unifi-protect-mcp` | `protect/v*` |
| `unifi-mcp-access` | `apps/access/` | `unifi-access-mcp` | `access/v*` |
| `unifi-api-server` | `apps/api/` | `unifi-api-server` | `api/v*` |
| `unifi-mcp-relay` | `packages/unifi-mcp-relay/` | `unifi-mcp-relay` | `relay/v*` |
| `unifi-mcp-worker` | `apps/worker/` | `unifi-mcp-worker` (npm, unscoped) | `worker/v*` |

**Critical:** PyPI package names differ from directory names. Always reference the PyPI name when
installing or checking versions. Example: `pip install unifi-network-mcp` (not `unifi-mcp-network`).
The worker's npm package name is also unscoped: `npm install -g unifi-mcp-worker` (not
`@unifi-mcp/worker`) — confirmed by `apps/worker/src/commands/upgrade.mjs`'s `npm view unifi-mcp-worker version` call.

When adding a new package, extend this table, update the release-notes path configuration,
and add a new `release-<package>.yml` workflow before pushing any tag.

---

## Procedure A: Determine Release Scope

Before pushing any tag, identify exactly which packages changed. This decision gates everything downstream — wrong scope means tagging unnecessary packages, causing spurious releases, or forgetting a tag and leaving a gap in PyPI versions.

### List changes per package

For each package candidate, check whether code actually changed since the last tag:

```bash
# Check packages/unifi-core/:
git log --oneline core/v$(git tag -l 'core/v*' | sort -V | tail -1)..HEAD -- packages/unifi-core/

# Check apps/network/:
git log --oneline network/v$(git tag -l 'network/v*' | sort -V | tail -1)..HEAD -- apps/network/ packages/unifi-mcp-shared/
```

### Post-merge scope verification

After a PR is merged but before tagging, confirm which files actually landed:

```bash
# Replace <pre-merge-sha> with the commit SHA immediately before the merge commit
git diff <pre-merge-sha>..HEAD --name-only
```

This is the most reliable way to scope which packages need a release — PR descriptions
can lag or overstate changes.

### Apply scope rules

| What changed | Tags required |
|---|---|
| `packages/unifi-mcp-shared/` only | `shared/v*` → then `network/v*`, `protect/v*`, `access/v*`, `relay/v*` |
| `packages/unifi-core/` only | `core/v*` → then `shared/v*` → then all downstream packages, including `api/v*` |
| One app only (e.g., `apps/protect/`) | `protect/v*` only |
| Multiple apps | One tag per changed app, in dependency order |
| Plugin-only changes (manifest/config updates) | Patch release for cache invalidation (e.g., `network/v0.14.13` → `network/v0.14.14`) |
| Worker (`apps/worker/`) | `worker/v*` |

**Negative corollary (skip-unchanged rule):** Do NOT tag a package simply because an upstream dependency was bumped, if the package's own code did not change AND its existing `pyproject.toml` bounds already accommodate the new upstream version. Check the declared version range in `pyproject.toml` first — if the new upstream version already satisfies the existing bounds and the app code is unchanged, no new tag is required.

### Tagging Selectivity Framework

**Minimal (lowest risk):** Tag ONLY packages with code changes in their own directory.

**Standard (recommended):** Tag all packages with code changes PLUS all downstream dependents to ensure they pick up shared library bumps. Use for any bump to `unifi-core` or `unifi-mcp-shared`.

**Full (maximum redundancy):** Tag all seven packages every release. Use for scheduled releases or recovering from a prior broken release sequence.

**Decision rule:** Default to Minimal. Escalate to Standard when a shared library change requires every dependent to ship a new wheel. Use Full when recovering from a release failure.

### Plugin-only Release and Cache Invalidation

When only the plugin manifest changes with no code changes, a patch release must still be cut to invalidate the marketplace cache. Existing deployed users remain pinned to their cached version until a new tagged release appears.

### Shared package rule

Any change to `packages/unifi-mcp-shared/` underpins all server apps. Tag `shared` first, then all server apps — even if their own code didn't change.

### CVE / transitive dependency changes

Trace the dependency chain before tagging everything:

```bash
grep -ri "pillow" apps/*/pyproject.toml packages/*/pyproject.toml
```

Tag only the affected app(s). Unnecessary tags create spurious releases.

---

## Procedure A.5: Patch-Bump Lockstep Avoidance

When releasing multiple packages in one coordination, avoid bumping major versions for multiple packages simultaneously. This prevents accidental lockstep coupling.

**Strategy:** When releasing shared with core, release `core/v0.3.0` (major bump) and `shared/v0.4.9` (patch bump, staying within 0.4.x). Defer `shared/v0.5.0` to a future cycle. Downstream apps can adopt `core@0.3.0` while keeping `shared@0.4.x`, then adopt `shared@0.5.0` independently later.

**When to break the rule:** Only when breaking API changes are required in both packages with no feasible bridge, all downstream maintainers are coordinated, and you can support a temporary dual-version install guide.

---

## Procedure B: App vs. Library Versioning and Writeback Behavior

### Library packages (unifi-core, unifi-mcp-shared, relay, api)

Use `dynamic = ["version"]` with hatch-vcs. Version is derived from the git tag at build time — no `_version.py` is ever committed. When a library tag is pushed, `bump-plugin-versions.yml` outputs `No version changes to commit` — this is **correct and expected**.

**`unifi-api-server` is a library package**, not an app package. It publishes to PyPI only and has no plugin manifest assets. Expect no writeback on `api/v*` tags.

### App packages (network, protect, access)

These have writable manifest assets updated on tag:
- `plugins/unifi-network/.claude-plugin/plugin.json`
- `plugins/unifi-protect/.claude-plugin/plugin.json`
- `plugins/unifi-access/.claude-plugin/plugin.json`
- `apps/*/server.json`

**Rule:** Never expect writeback from a library package tag (core, shared, relay, api). Never accept a missing writeback from an app package tag (network, protect, access).

### Version bump selection

Use **patch** for bug fixes and backwards-compatible internal changes. Use **minor** when adding
new functionality that is additive but could affect downstream consumers — even if technically
backwards-compatible, a minor bump signals to dependents that review is warranted. Use **major**
for breaking API changes. Dependency bound updates for upstream packages must land on `main`
(and pass CI) **before** pushing the corresponding version tags.

---

## Procedure C: hatch-vcs Tag Glob Scoping

Without a per-package `git_describe_command --match` glob, any tag reachable in the repo can influence any package's version.

| Package | Match pattern |
|---|---|
| network | `network/v*` |
| protect | `protect/v*` |
| access | `access/v*` |
| relay | `relay/v*` |
| unifi-core | `core/v*` |
| unifi-mcp-shared | `shared/v*` |
| api | `api/v*` |

Each package must declare both `tag_regex` and `git_describe_command` scoped to its own prefix. Never share or widen the `--match` pattern across packages.

---

## Procedure D: Pin-Alignment CI Gate + Align Cross-Package Dependency Bounds Before Tagging

### Step 0: Pin-Alignment CI Gate (Automated Blocker)

The pin-alignment CI gate runs on every PR and **cannot be skipped**. It validates that every downstream package's dependency bounds permit the versions of upstream packages on main. If your PR fails: look at the CI output for the specific package and bound that failed, update the offending bounds in `pyproject.toml`, commit and push.

**CI gate gap — import-only PRs:** The pin-alignment gate fires only when `pyproject.toml` changes. A PR that adds code using a new cross-package API (new import from `unifi-core` or `unifi-mcp-shared`) without updating the floor bound in `pyproject.toml` passes CI even when the published upstream wheel's metadata would reject the resolved version at user install time. Manually verify dependency bounds for any PR that expands cross-package imports.

### Align Cross-Package Dependency Bounds Before Tagging

Before creating release tags, inspect every downstream `pyproject.toml` for packages being released together. Tag order only solves publication timing; the wheel metadata must also allow the newly published upstream version.

**Dependency-bound checklist:**
1. Identify upstream packages that changed (`unifi-core`, `unifi-mcp-shared`).
2. Identify downstream packages being tagged because they use that upstream code.
3. Update downstream dependency ranges in `apps/*/pyproject.toml` and `packages/unifi-mcp-relay/pyproject.toml`.
4. Verify with wheel-metadata check (see below). `uv lock --check` is insufficient — see below.
5. Commit dependency-bound changes before creating local tags.

### Why `uv lock --check` is not a sufficient gate

Workspace `[tool.uv.sources]` overrides take precedence over the version range during `uv sync`/`uv lock` — every CI job passes cleanly even when the published wheel's `requires_dist` will reject the just-released upstream package. The pin only fails when pip/uv resolves the published wheel against PyPI on a user's machine. Docker images also bypass the failure. This is a **PyPI-only** failure mode.

### Pre-tag wheel-metadata check

```bash
rm -rf /tmp/wheelcheck && mkdir -p /tmp/wheelcheck
for app in apps/network apps/protect apps/access packages/unifi-mcp-relay; do
  echo "=== $app ==="
  uv build --wheel "$app" --out-dir /tmp/wheelcheck/$(basename $app) 2>&1 | tail -2
  whl=$(ls /tmp/wheelcheck/$(basename $app)/*.whl | tail -1)
  python -m zipfile -e "$whl" /tmp/wheelcheck/extracted/$(basename $app)/
  grep -h 'Requires-Dist.*\(unifi-mcp-shared\|unifi-core\)' \
    /tmp/wheelcheck/extracted/$(basename $app)/*.dist-info/METADATA
done
```

---

## Procedure E: Manifest Bumper — args[2] vs args[0] Correction

The manifest bumper workflow (`bump-plugin-versions.yml`) must target `args[2]` (the version pin value), not `args[0]` (the flag name). The bumper must atomically update version fields in ALL plugin manifest copies — `plugin.json`, `server.json`, `.mcp.json` — in a single commit. Verify after a release that all manifest files show the updated version string.

---

## Procedure F: Dependency-Ordered Tag Pushing

**Critical rule:** Push each tag INDIVIDUALLY, one at a time. Wait for PyPI confirmation before pushing the next. Batch-pushing (`git push origin tag1 tag2`) causes GitHub Actions to silently skip all but the first workflow.

```bash
# Step 1 — upstream foundation
git tag core/v0.2.0
git push origin core/v0.2.0
# WAIT: confirm https://pypi.org/project/unifi-core/ shows 0.2.0 and CI is green

# Step 2 — shared layer
git tag shared/v0.4.0
git push origin shared/v0.4.0
# WAIT: confirm PyPI and CI green

# Step 3 — app servers (push individually, one per command)
git tag network/v0.14.13
git push origin network/v0.14.13
# WAIT and repeat for protect, access, api

# Step 4 — relay and worker last
git tag relay/v0.1.0
git push origin relay/v0.1.0
```

> **Floor-bump sequencing gotcha:** Open downstream `pyproject.toml` floor-bump PRs (raising the minimum version bound on an upstream package) **only after** the upstream tag is confirmed on PyPI. Committing the floor-bump PR before the upstream version exists on PyPI causes the pin-alignment CI gate on that PR to fail — the gate tries to resolve the declared lower bound but the version does not yet exist.

> **Floor-bump local staging:** While waiting for PyPI to confirm the upstream version, stage the floor-bump work locally — create the branch, update downstream `pyproject.toml` version floors, and commit locally. Hold `git push` and PR creation until PyPI confirms the version exists. This decouples preparation from the PyPI propagation gate and eliminates idle waiting between confirmation and branch push.

---

## Procedure G: generate_release_notes.py Path Configuration

Open `scripts/generate_release_notes.py` and locate `APP_CONFIGS`. Each entry is a `PackageConfig` with `path_groups` — a tuple of `PathGroup` objects that filter PRs to only those touching paths relevant to each package. Each entry should include the app directory, shared dependency directories (`packages/unifi-core/`, `packages/unifi-mcp-shared/`), and its own publish, test, and Docker build workflow paths.

**Known limitation:** `scripts/generate_release_notes.py` does not emit PR author information. Contributor credit must be added manually.

---

## Procedure H: Release Validation

After pushing a tag:

1. **Check CI:** Confirm the version check job goes green.
2. **Verify locally:** `cd apps/<app> && hatch version` — should print exactly the tagged version.
3. **Confirm PyPI:** `pip index versions unifi-network-mcp`.
4. **Install smoke test:** `pip install --upgrade unifi-network-mcp && python -c "import unifi_network_mcp; print(unifi_network_mcp.__version__)"`.
5. **Post-Release Live Smoke Verification** (must run via `uv`, not system `python3`):
   ```bash
   uv run python scripts/live_smoke.py --server network --phase safe
   uv run python scripts/live_smoke.py --server protect --phase safe
   uv run python scripts/live_smoke.py --server access --phase safe
   ```
   All three must exit 0 with zero failed/exception records. This is the final release validation gate.
   **Do not invoke with bare `python3 scripts/live_smoke.py`** — the system Python lacks the workspace dependencies and the harness will fail at import time.

---

## Procedure I: Dependabot Dependency Update Management

Dependabot updates the lockfile one package at a time. When multiple PRs fail CI with the same class of lockfile error, merge into a single maintainer branch:

```bash
git checkout -b deps/batch-dependabot main
# Apply dependency changes, then re-lock from combined state:
uv lock
# Run per-package tests before opening the PR:
cd apps/network && uv run pytest && cd ../..
cd apps/protect && uv run pytest && cd ../..
```

**Strategy A (Reactive):** Batch accumulated Dependabot PRs into a single maintainer branch, run `uv lock`, merge the combined PR.

**Strategy B (Proactive):** Don't wait for Dependabot PRs to accumulate. Periodically run `uv lock` yourself and open a single maintainer PR before the Dependabot queue grows. This prevents cascading CI failures from multiple simultaneous lockfile-touching PRs.

**Major-version bumps are invisible at the PR level** — the CI failure looks identical to a minor version conflict. Always inspect the actual version change in the PR diff.

**pyproject floor vs. lockfile drift:** After batching, verify each updated package's lower bound still permits the resolved version. Run the wheel-metadata check from Procedure D before merging.

**Second-wave cascading PRs gotcha:** After a batch Dependabot PR merges, Dependabot may open a fresh wave of new PRs for versions newly unlocked by the combined resolution. This is expected — the first merge freed resolution space for the next tier. Budget time for a second round of batching review.

---

## Procedure J: Shared Package Architecture Constraints

Before releasing `packages/unifi-mcp-shared/` or `packages/unifi-core/`, verify these three structural invariants were maintained during development.

### J-1: DI-Only Rule — No Reverse Imports in `unifi-mcp-shared`

Every entrypoint in `packages/unifi-mcp-shared/` must accept app-specific behavior as injected parameters. Direct imports from `unifi_network_mcp`, `unifi_protect_mcp`, or `unifi_access_mcp` inside the shared package create a circular import that breaks all three app servers simultaneously at import time — blast radius is total.

Verify before releasing any shared-package change:
```bash
grep -r "from unifi_network_mcp\|from unifi_protect_mcp\|from unifi_access_mcp" packages/unifi-mcp-shared/
```
Any match is a release blocker. Replace with an injected parameter or a typed Protocol interface defined within `packages/unifi-mcp-shared/`.

### J-2: Scope Gate — `unifi-core` vs. `unifi-mcp-shared`

Decision tree for placing new code:
- Talks directly to UniFi hardware or manages HTTP sessions? → `unifi-core`
- Coordinates MCP concerns (permissions, tool registration, confirmations)? → `unifi-mcp-shared`
- References MCP types (`FastMCP`, tool decorators)? → `unifi-mcp-shared`
- Would be useful in a non-MCP CLI calling the UniFi API? → `unifi-core`

Import direction must remain strictly left-to-right: `app servers → unifi-mcp-shared → unifi-core`. Verify:
```bash
grep -r "from unifi_mcp_shared\|import unifi_mcp_shared" packages/unifi-core/
grep -r "from unifi_network_mcp\|from unifi_protect_mcp\|from unifi_access_mcp" packages/unifi-mcp-shared/ packages/unifi-core/
```
Both commands must return nothing.

### J-3: Relay Protocol Sync (Required Before Shared-Package Release)

The two relay files `packages/unifi-mcp-relay/src/unifi_mcp_relay/discovery.py` and `packages/unifi-mcp-relay/src/unifi_mcp_relay/protocol.py` implement relay protocol logic that does **not** import from `unifi-mcp-shared`. When shared-package protocol changes (new message format, endpoint path, header), these files receive no automatic update — there is no import error, failing test, or CI gate. Drift fails silently at runtime.

Before any shared-package protocol release:
1. Identify what changed (message schema, endpoint path, header, error envelope shape).
2. Open `packages/unifi-mcp-relay/src/unifi_mcp_relay/discovery.py` and `packages/unifi-mcp-relay/src/unifi_mcp_relay/protocol.py` and manually port the change.
3. Trace the message path end-to-end through both to confirm they agree.

PR checklist trigger: any PR modifying shared-package protocol must include a "relay sync" section confirming both relay files were reviewed.

---

## Cross-Cutting Gotchas

**Sibling tag contamination.** If `git_describe_command` `--match` is too broad (e.g., `v*`), hatch-vcs picks up a sibling package's tag and reports the wrong version. Fix: tighten the `--match` pattern and rebuild.

**PR merge is NOT the release trigger — the tag push is.** `hatch-vcs` reads git tags at build time. Merging a PR does NOT trigger a release. Always run Procedure H after tagging.

**Silent version freeze.** If a tag is missing, `hatch-vcs` falls back to `fallback_version = "0.0.0"`. There is no error at merge time. Always run Procedure H after tagging.

**Missing tag causes broken downstream install.** If `unifi-core` code is merged but the tag is never pushed, downstream packages requesting that version fail to install. Check PyPI before debugging code.

**Main-only merges are invisible to existing users.** Cache invalidation requires a tagged release. If a manifest change is urgent, cut a patch release immediately.

**Malformed git tag — missing 'v' prefix.** A tag like `protect/0.4.2` (no 'v') is syntactically wrong and ignored by hatch-vcs. Validate before pushing: `git tag -l | grep -E 'network|protect|access|relay|core|shared|api' | sort -V` — every line must contain `/v`.

**PyPI pin masked by workspace source — failure mode the entire CI matrix cannot detect.** Workspace `[tool.uv.sources]` overrides mean `uv lock --check` passes with a stale pin. The pin only fails when pip resolves against PyPI on a user's machine. Run the wheel-metadata check in Procedure D before pushing tags.

**Batch tag push silently skips releases.** `git push origin tag1 tag2 tag3` causes GitHub Actions to start only the first workflow. Push tags one at a time.

**Broken published wheels: remediation via PyPI yank (PEP 592).** Yank via the PyPI web UI — `twine` does not support the yank operation. Yanked versions are skipped during resolution but remain installable when explicitly pinned. Always follow a bulk yank with a corrected patch release.

**PyPI package names differ from directory names.** `unifi-network-mcp` ≠ `unifi-mcp-network`. See Package Map.

**Cross-package combined pytest run causes test configuration collision.** Running `uv run pytest packages/ apps/` causes pytest to load conflicting conftest files. Run per-package: `cd apps/network && uv run pytest`. CI workflows are already scoped this way.

**Shared-package import blast radius is total.** A single `from unifi_network_mcp` import inside `packages/unifi-mcp-shared/` breaks all three app servers simultaneously at import time. The `ImportError` traceback names the shared package, masking the root cause. Run the grep from Procedure J-1 before every shared-package release.

**Relay protocol drift is silent.** The relay implementation files (`packages/unifi-mcp-relay/src/unifi_mcp_relay/discovery.py` and `packages/unifi-mcp-relay/src/unifi_mcp_relay/protocol.py`) have no import from `unifi-mcp-shared` — protocol changes fail silently until a real client exercises the changed path. Manual review on every protocol-touching PR is the only protection (see Procedure J-3).

**Backwards-coupling enforcement.** Import direction must stay: app servers → `unifi-mcp-shared` → `unifi-core`. Direct imports from app packages inside shared or core break at import time but no test catches it until the import is exercised. Grep before committing.

**Diagnostics direct-import pattern.** When debugging shared-package behavior from an app server, write diagnostic logic in the app server's namespace — do not import shared internals directly for inline inspection. Direct imports of shared internals count for cycle-checking.
