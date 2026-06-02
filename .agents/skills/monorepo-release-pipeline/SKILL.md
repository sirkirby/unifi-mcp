---
name: myco:monorepo-release-pipeline
description: >-
  Covers the full release pipeline for the unifi-mcp monorepo: determining release scope by
  analyzing changed packages, scoping hatch-vcs version tag globs per Python package to prevent
  sibling-tag contamination, pushing tags in strict dependency order (unifi-core → unifi-mcp-shared
  → app servers → relay → worker when needed), configuring scripts/generate_release_notes.py
  path scoping per package, wiring per-package publish workflows for OIDC trusted publishing,
  coordinating cross-package version bumps in pyproject.toml, understanding app vs. library
  versioning and writeback behavior, and validating releases post-tag. Apply this skill when
  cutting any release, adding a new package, bumping unifi-core, or debugging a versioning or
  publish-workflow failure — even if the user does not explicitly ask about tag ordering or
  release notes. CRITICAL: All PRs require pin-alignment CI gate before merge (automated,
  cannot be skipped).
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
| `unifi-mcp-worker` | `apps/worker/` | `@unifi-mcp/worker` (npm) | `worker/v*` |

**Critical:** PyPI package names differ from directory names. Always reference the PyPI name when
installing or checking versions. Example: `pip install unifi-network-mcp` (not `unifi-mcp-network`).

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

### Apply scope rules

| What changed | Tags required |
|---|---|
| `packages/unifi-mcp-shared/` only | `shared/v*` → then `network/v*`, `protect/v*`, `access/v*`, `relay/v*` |
| `packages/unifi-core/` only | `core/v*` → then `shared/v*` → then all downstream packages, including `api/v*` |
| One app only (e.g., `apps/protect/`) | `protect/v*` only |
| Multiple apps | One tag per changed app, in dependency order |
| Plugin-only changes (manifest/config updates) | Patch release for cache invalidation (e.g., `network/v0.14.13` → `network/v0.14.14`) |
| Worker (`apps/worker/`) | `worker/v*` |

### Tagging Selectivity Framework

Depending on the scope and confidence of the release, choose one of three tagging strategies:

**Minimal (lowest risk, most conservative):**
- Tag ONLY packages with code changes in their own directory.
- Do not auto-tag downstream packages unless they explicitly changed.
- Use case: Security patch in a transitive dependency (e.g., Pillow) that affects only one app.
- Risk: Manual tag selection can miss packages. Confidence: high only if you've audited the
  dependency chain and know exactly which app uses the patched library.
- Example: `git tag protect/v0.3.5` (Access unchanged, Network unchanged — only Protect uses
  the patched Pillow version)

**Standard (recommended, balanced):**
- Tag all packages with code changes PLUS all downstream dependents (even if they didn't
  change code) to ensure they pick up shared library bumps.
- Use case: Any bump to `unifi-core` or `unifi-mcp-shared`; new resource in any app.
- Risk: Creates spurious patch releases for apps that only changed transitively. Builds
  redundancy into the release (some wheel metadata will be stale). Confidence: high.
- Example: Shared gains new validators → tag `shared/v*`, then `network/v*`, `protect/v*`,
  `access/v*`, `relay/v*` (even if Network, Protect, Access, Relay only changed their
  dependency bounds, not their code).

**Full (maximum redundancy, CI safeguard):**
- Tag all seven packages every release.
- Use case: Scheduled releases, coordinated team releases, recovering from a prior broken
  release sequence.
- Risk: Creates unnecessary artifact churn; every package publishes even if unchanged.
- Benefit: Rebuilds all wheels, catches stale pinning across the board, guaranteed CI runs
  all workflows.
- Example: `for p in core shared network protect access api relay; do git tag $p/v<version>; done`

**Decision rule:** Start with Standard (accounts for the shared library rule and downstream
dependency bumps). Use Minimal only if you've verified the transitive dependency chain and
are confident of your scope. Use Full when recovering from a release failure or for
scheduled releases.

### Plugin-only Release and Cache Invalidation

When only the plugin manifest (e.g., `plugins/*/plugin.json`) changes with no code changes, a patch release must still be cut — not as code update, but to invalidate the marketplace cache and force existing users to pick up the new manifest.

**The mechanism:** Plugin users cache the manifest JSON locally. Existing deployed users remain pinned to their cached version until the server publishes a **new tagged release**. A main-only merge (no tag) is invisible to existing users — they see no update available.

**When this arises:** Security policy updates, feature flag toggles, or capability declaration changes that don't touch code.

**Example:**
```bash
# manifests/plugin.json was updated (policy change); no code changes
git tag network/v0.14.14  # patch bump despite no code changes
git push origin network/v0.14.14
# All existing deployed instances will now see v0.14.14 as available and pick up the new manifest
```

### Shared package rule

Any change to `packages/unifi-mcp-shared/` underpins all server apps. Tag `shared` first, then all server apps — even if their own code didn't change — so the next build picks up the shared bump.

### CVE / transitive dependency changes

A security patch in a transitive dependency may only affect one app. Trace the dependency chain before tagging everything:

```bash
# Identify the patched package from CVE advisory (e.g., Pillow)
grep -ri "pillow" apps/*/pyproject.toml packages/*/pyproject.toml

# Trace: if only apps/protect/ imports uiprotect (which depends on Pillow),
# then only protect/v* needs a new tag
```

Confirm with tests before tagging:
```bash
cd apps/protect && pytest --tb=short
```

Tag only the affected app(s). Unnecessary tags create spurious releases.

---

## Procedure A.5: Patch-Bump Lockstep Avoidance

**Critical strategy:** When releasing multiple packages in one coordination, avoid bumping major versions for multiple packages simultaneously. This prevents accidental lockstep coupling and allows downstream users to consume updates independently.

### The Problem

If you bump `unifi-core` from 0.2.x to 0.3.0 AND `unifi-mcp-shared` from 0.4.x to 0.5.0 in the same release cycle, then every downstream app (`unifi-network-mcp`, `unifi-protect-mcp`, etc.) must update its dependency bounds **simultaneously**, creating a forced global coordination burden. Users cannot adopt the new core without also adopting the new shared, even if they only need the core.

### The Strategy

**When releasing shared with core:**
1. Release `core/v0.3.0` (major bump)
2. Release `shared/v0.4.9` (patch bump, staying within 0.4.x)
3. Defer the `shared/v0.5.0` major bump to a future, separate release cycle

Downstream apps can then:
- Adopt `core@0.3.0` while keeping `shared@0.4.x`
- Later (next cycle), adopt `shared@0.5.0` independently

**Pin ranges remain simple:**
- `unifi-core>=0.3.0,<0.4` (stays locked to major version 0.3)
- `unifi-mcp-shared>=0.4.9,<0.5` (stays within major version 0.4 until the next planned cycle)

**Risk mitigation:**
- Version #283 breakage (2026-05-17) was caused by stale pins when multiple majors shipped together
- Coordinating multiple major bumps requires manual dependency audits and high confidence
- Patch bumps stay within major.minor and can be released independently without forcing downstream updates

### When to Break the Rule

Use simultaneous major bumps ONLY when:
1. Breaking API changes are required in both packages
2. There is NO feasible way to bridge the versions with shims
3. You have explicitly coordinated with all downstream package maintainers
4. You are prepared to support a temporary "dual-version" install guide if adoption is slow

---

## Procedure B: App vs. Library Versioning and Writeback Behavior

Understanding the difference between library and app package versioning is essential because writeback behavior differs, and missing writeback from an app package is a bug — while missing writeback from a library package is correct.

### Library packages (unifi-core, unifi-mcp-shared, relay)

These packages use `dynamic = ["version"]` in `pyproject.toml` with hatch-vcs. Version is derived from the git tag **at build time** — no `_version.py` is ever committed to the repo. When a library tag is pushed:

- The publish workflow builds and publishes the tagged commit as-is
- `bump-plugin-versions.yml` runs and outputs: `No version changes to commit`
- This is **correct and expected** — not a bug or a missed step
- There is no manifest file to update (no plugin.json or server.json)

### App packages (network, protect, access, api)

These packages have writable manifest assets that get updated on tag:

- `plugins/unifi-network/.claude-plugin/plugin.json`
- `plugins/unifi-protect/.claude-plugin/plugin.json`
- `plugins/unifi-access/.claude-plugin/plugin.json`
- `apps/*/server.json`

When an app tag is pushed, the workflow commits a version writeback to these files.
If the writeback commit is missing, the manifests will be stale and users will see
the wrong version reported by the tool.

**Rule:** Never expect writeback from a library package tag. Never accept a
missing writeback from an app package tag.

---

## Procedure C: hatch-vcs Tag Glob Scoping

hatch-vcs derives each package's version from git tags at build time. Without a
per-package `git_describe_command --match` glob, any tag reachable in the repo can
influence any package's version — a `network/v0.14.13` tag will contaminate
`protect`'s version if `protect`'s `git_describe_command` matches all tags.

### Correct tag patterns per package

| Package | Match pattern |
|---|---|
| network | `network/v*` |
| protect | `protect/v*` |
| access | `access/v*` |
| relay | `relay/v*` |
| unifi-core | `core/v*` |
| unifi-mcp-shared | `shared/v*` |
| api | `api/v*` |

### pyproject.toml configuration

Each package must declare both a `tag_regex` (to extract the version number) and a
`git_describe_command` scoped to its own prefix:

```toml
# packages/unifi-core/pyproject.toml
[tool.hatch.version]
source = "vcs"
raw-options.root = "../.."
raw-options.tag_regex = "^core/v(?P<version>\\d+(?:\\.\\d+)*)(?:\\S*)$"
raw-options.git_describe_command = ["git", "describe", "--dirty", "--tags", "--long", "--match", "core/v*"]
raw-options.fallback_version = "0.0.0"

# apps/network/pyproject.toml
[tool.hatch.version]
source = "vcs"
raw-options.root = "../.."
raw-options.tag_regex = "^(?:network/v|v)(?P<version>\\d+(?:\\.\\d+)*)(?:\\S*)$"
raw-options.git_describe_command = ["git", "describe", "--dirty", "--tags", "--long", "--match", "network/v*"]
raw-options.fallback_version = "0.0.0"
```

Each package's `--match` pattern must be scoped to its own tag prefix from the
Package Map. Never share or widen the `--match` pattern across packages.

---

## Procedure D: Pin-Alignment CI Gate + Align Cross-Package Dependency Bounds Before Tagging

### Step 0: Pin-Alignment CI Gate (Automated Blocker)

**Critical:** The pin-alignment CI gate (PR #286) runs on every PR targeting `main` and
**cannot be skipped**. This gate prevents the stale-pin incident (#283, 2026-05-17) from
recurring. It automatically validates that every downstream package's dependency bounds
in `pyproject.toml` permit the versions of upstream packages (`unifi-core`,
`unifi-mcp-shared`) that exist on main.

**How it works:**
- On every PR, the gate builds all wheels and extracts their `Requires-Dist` metadata.
- For each declared upstream dependency (e.g., `unifi-mcp-shared>=0.4.5,<0.5`), the gate
  validates that the bound permits the actual version currently in use by the workspace.
- If bounds are too narrow (e.g., `<0.5` when shared is actually 0.5.0 on main), the gate
  **fails the PR** and you must fix the pins before merge.

**Your action:** The gate blocks PRs automatically. If your PR fails the pin-alignment gate:
1. Look at the CI job output for the specific package and bound that failed.
2. Update the offending bounds in `pyproject.toml` (e.g., change `<0.5` to `<0.6`).
3. Commit and push the fix.
4. The gate re-runs automatically on push and must pass before merge is allowed.

This is **not optional** and there is no override. The gate exists to prevent broken
releases from landing on main.

### Align Cross-Package Dependency Bounds Before Tagging

Before creating release tags, inspect every downstream `pyproject.toml` dependency
range for packages being released together. Tag order only solves publication timing;
the wheel metadata must also allow the newly published upstream version.

**Rule:** If a downstream package requires code that is only present in the new
`unifi-core` or `unifi-mcp-shared` release, update its dependency range before
placing tags. Do not assume pip installs the newest upstream release. It installs
the newest version permitted by the downstream wheel metadata.

Examples:

```toml
# New Protect/API code needs unifi-core 0.3.x models and managers.
"unifi-core[protect]>=0.3,<0.4"
"unifi-core[network,protect,access]>=0.3,<0.4"

# New app code needs unifi-mcp-shared 0.5.x helpers.
"unifi-mcp-shared>=0.5,<0.6"
```

### Dependency-bound checklist

1. Identify upstream packages that changed (`unifi-core`, `unifi-mcp-shared`).
2. Identify downstream packages being tagged because they use that upstream code.
3. Update downstream dependency ranges in `apps/*/pyproject.toml` and
   `packages/unifi-mcp-relay/pyproject.toml` as needed.
4. **Verify the new pin range with the wheel-metadata check below.** `uv lock --check`
   passes even when the pin is wrong — workspace sources override the range locally.
5. Commit dependency-bound changes before creating local tags.

If dependency bounds are stale, the release can publish successfully but install an
older upstream package that lacks the required API surface. Treat dependency-bound
alignment as part of the release artifact, not as optional cleanup.

### Why `uv lock --check` is not a sufficient gate

Every downstream `pyproject.toml` declares `[tool.uv.sources] unifi-mcp-shared = { workspace = true }`
(and the equivalent for `unifi-core`). In workspace contexts, that source override takes
precedence over the version range in `[project.dependencies]` — `uv sync` and `uv lock`
always resolve to the local checkout regardless of whether the declared range still
allows the upstream version being released. **`uv lock --check`, `pytest`, and every CI
job in this repo pass cleanly even when the published wheel's `requires_dist` will reject
the just-released upstream package.**

The pin only takes effect when pip/uv resolves the published wheel against PyPI — i.e.,
on a fresh `uvx <pkg>@latest` or `pip install <pkg>` on a user's machine, with no
workspace context. That is exactly the path users hit and CI does not.

Docker images built from this repo are also unaffected, because the Dockerfiles use
`uv sync --frozen --package <pkg>` against the workspace lock and bundle the local
shared checkout. The pin mismatch is a **PyPI-only** failure mode.

### Pre-tag wheel-metadata check (the gate that actually works)

Before pushing any tag whose dependency range was just edited, build the wheel and read
its `Requires-Dist` to confirm the published artifact will permit the upstream version
being released:

```bash
# After bumping pins, BEFORE pushing tags:
rm -rf /tmp/wheelcheck && mkdir -p /tmp/wheelcheck
for app in apps/network apps/protect apps/access packages/unifi-mcp-relay; do
  echo "=== $app ==="
  uv build --wheel "$app" --out-dir /tmp/wheelcheck/$(basename $app) 2>&1 | tail -2
  whl=$(ls /tmp/wheelcheck/$(basename $app)/*.whl | tail -1)
  python -m zipfile -e "$whl" /tmp/wheelcheck/extracted/$(basename $app)/
  grep -h 'Requires-Dist.*\\(unifi-mcp-shared\\|unifi-core\\)' \\
    /tmp/wheelcheck/extracted/$(basename $app)/*.dist-info/METADATA
done
```

For each output line, confirm the range is `>=<new-upstream-version>` and `<<next-major>`.
A stale `<0.5` upper bound on a release that needs shared 0.5.0+ is the canonical failure
mode — see "PyPI pin masked by workspace source" in Cross-Cutting Gotchas.

A fast supplementary grep that catches the most common shape:

```bash
# Confirm no downstream pyproject still pins below the new upstream major.minor.
# Example: releasing shared 0.5.0 — every match below should be empty.
grep -n "unifi-mcp-shared" apps/*/pyproject.toml packages/*/pyproject.toml \\
  | grep -v 'workspace = true' \\
  | grep -v '>=0.5'
```

### Verification before tagging

Before pushing a tag, verify the version would resolve correctly by running the
scoped git describe command explicitly:

```bash
# For network package, verify the --match pattern is scoped
cd apps/network
git describe --dirty --tags --long --match network/v*
# Expected: network/v0.14.13-0-g<hash> (or similar with no sibling tags)

# Test the actual version that would be reported at build time
pip install -e ".[dev]"
python -c "import importlib.metadata; print(importlib.metadata.version('unifi-mcp-network'))"
# Expected: exactly matches the tag version, e.g. 0.14.13
```

If the version does NOT match what you're about to tag, the `--match` pattern is
still contaminated by sibling tags. Example failure modes:

```bash
# WRONG — picks up protect/v0.3.5 because --match is too broad
git describe --tags --long --match v*
# network/v0.14.13-125-g... (125 commits past a wrong tag)

# CORRECT — scoped to network/ prefix only
git describe --tags --long --match network/v*
# network/v0.14.13-0-g...
```

**Gotcha — tag resolution is at build time, not install time.** hatch-vcs reads
tags when the package is built (during CI), not when it is installed. The tag must
be reachable on the exact commit being built. If CI triggers before the tag propagates
to GitHub, the version will be wrong even if the tag exists locally.

---

## Procedure E: Manifest Bumper — args[2] vs args[0] Correction

The manifest bumper workflow (`bump-plugin-versions.yml`) rewrites version fields in
`plugin.json` and `server.json` files after a successful publish. A past bug (PR #227)
corrupted the bumper to target `args[0]` (the flag name) instead of `args[2]` (the
version pin value).

### Correct bumper configuration

In `bump-plugin-versions.yml`, the version replacement must target the third positional
argument — the version pin field, not the flag name:

```yaml
# WRONG — corrupts the flag name
- run: python scripts/bump_version.py ${{ ... }} --json-path '$.version' --index 0

# CORRECT — targets the version pin value
- run: python scripts/bump_version.py ${{ ... }} --json-path '$.version' --index 2
```

The bumper script reads the manifest JSON, extracts the version bump from the publish
output, and replaces it at the specified index. Index 2 is the version string itself;
index 0 would corrupt the flag or field name.

**Atomic manifest sync — all plugin marketplaces:** When the bumper runs after a publish,
it must atomically update version fields in ALL plugin manifest copies that get deployed
to end users:
- `plugins/unifi-network/.claude-plugin/plugin.json` (Claude plugin marketplace)
- `plugins/unifi-network/.openai/plugin.json` (if deployed to OpenAI agents marketplace)
- `plugins/unifi-network/.mcp.json` (MCP server manifest, if exposed as standalone server)
- Same for protect, access, api, etc.

The bumper workflow must commit a single atomic update across all copies. If some manifest
files are updated and others are not, users will see version mismatches or stale metadata
in non-updated marketplaces.

**Verification:** After a release workflow completes and the bumper runs, check the
manifest commit in GitHub. All `plugin.json` and `.mcp.json` files should have updated
version strings (e.g., `"version": "0.14.14"`), NOT corrupted field names. Spot-check
that Claude plugin, OpenAI agents, and standalone MCP manifests are all in sync.

---

## Procedure F: Dependency-Ordered Tag Pushing

The dependency graph:

```
unifi-core  →  unifi-mcp-shared  →  unifi-network-mcp
                                  →  unifi-protect-mcp
                                  →  unifi-access-mcp
                                  →  unifi-mcp-relay
            →  unifi-api-server
```

**Critical rule:** Push each tag INDIVIDUALLY, one at a time. Wait for GitHub Actions to
complete and confirm the PyPI package is live before pushing the next tag. Batch-pushing
tags in a single `git push` command causes GitHub Actions workflows to NOT trigger — releases
are silently skipped. This is a GitHub Actions orchestration quirk: when multiple tags are
pushed in a single push event, only the first workflow starts; subsequent tags are ignored.
The silent failure causes PyPI to stay on the old version, artifact uploads to be skipped,
and downstream installs to fail with unresolved dependencies.

**Rule:** Upstream tags first. Wait for PyPI confirmation before downstream tags. Downstream
packages declare a minimum version of their upstream dependencies in `pyproject.toml`; if
the upstream version is not yet on PyPI when the downstream workflow runs, pip will fail
to resolve the dependency.

### Tag push sequence — PUSH ONE AT A TIME

```bash
# Step 1 — upstream foundation
git tag core/v0.2.0
git push origin core/v0.2.0
# WAIT: confirm https://pypi.org/project/unifi-core/ shows 0.2.0 and CI is green

# Step 2 — shared layer
git tag shared/v0.4.0
git push origin shared/v0.4.0
# WAIT: confirm https://pypi.org/project/unifi-mcp-shared/ shows 0.4.0 and CI is green

# Step 3 — app servers and API (push individually, one per command)
git tag network/v0.14.13
git push origin network/v0.14.13
# WAIT: confirm https://pypi.org/project/unifi-network-mcp/ shows 0.14.13 and CI is green

git tag protect/v0.3.5
git push origin protect/v0.3.5
# WAIT: confirm https://pypi.org/project/unifi-protect-mcp/ shows 0.3.5 and CI is green

git tag access/v0.2.4
git push origin access/v0.2.4
# WAIT: confirm https://pypi.org/project/unifi-access-mcp/ shows 0.2.4 and CI is green

git tag api/v0.2.1
git push origin api/v0.2.1
# WAIT: confirm https://pypi.org/project/unifi-api-server/ shows 0.2.1 and CI is green

# Step 4 — relay
git tag relay/v0.1.0
git push origin relay/v0.1.0
# WAIT: confirm https://pypi.org/project/unifi-mcp-relay/ shows 0.1.0 and CI is green

# Step 5 — worker, if relay/worker behavior changed
git tag worker/v1.3.1
git push origin worker/v1.3.1
# WAIT: confirm npm registry and CI are green
```

**Why one push per tag:** The single-push-multiple-tags pattern (`git push origin tag1 tag2`)
fires all workflows simultaneously but GitHub only queues the first. Subsequent workflows
start only after the first completes (or not at all, silently). The expected behavior
(all workflows start in parallel) does not happen. Workflow skips are invisible in the job
log — the jobs don't appear at all, so it's easy to miss that a publish never happened.

**Worker app:** `apps/worker` has a separate npm release flow using OIDC via GitHub Actions.
Apply the same ordering principle: if the worker depends on a Python package version or relay
protocol behavior, confirm the upstream PyPI release is updated before pushing the `worker/v*` tag.

---

## Procedure G: generate_release_notes.py Path Configuration

GitHub's built-in `--generate-notes` option includes every PR merged between the
previous tag and the current tag in the entire repo — regardless of which files
changed. In a monorepo, a `network/v0.14.13` release would absorb protect and access
PRs. The custom script `scripts/generate_release_notes.py` filters PRs to only those
touching paths relevant to each package.

### Per-package path configuration

Open `scripts/generate_release_notes.py` and locate the `APP_CONFIGS` dict. Each
entry is a `PackageConfig` with `path_groups` — a tuple of `PathGroup` objects that
group related paths under a label. For app servers, the structure is:

```python
APP_CONFIGS = {
    "network": PackageConfig(
        key="network",
        display_name="UniFi Network MCP",
        pypi_package="unifi-network-mcp",
        install_command="uvx unifi-network-mcp=={version}",
        path_groups=(
            PathGroup("Network MCP", ("apps/network/", "plugins/unifi-network/")),
            PathGroup("Shared Libraries", ("packages/unifi-core/", "packages/unifi-mcp-shared/")),
            PathGroup(
                "Release Infrastructure",
                (
                    ".github/workflows/release-network.yml",
                    ".github/workflows/docker-network.yml",
                    ".github/workflows/test-network.yml",
                    ".github/workflows/bump-plugin-versions.yml",
                    *COMMON_PACKAGE_PATHS,  # pyproject.toml, uv.lock
                ),
            ),
        ),
    ),
    # ... one entry per package
}
```

Note: paths are directory prefixes (e.g., `"apps/network/"`) — not `**` globs.

Each app server entry should include:
1. Its own app/package directory as the primary `PathGroup`
2. Shared dependency directories (`packages/unifi-core/`, `packages/unifi-mcp-shared/`)
3. Its own publish/test/docker workflows as Release Infrastructure

---

## Procedure H: Release Validation

After pushing a tag, verify it resolved correctly before closing the work.

1. **Check CI:** The tag push triggers GitHub Actions. Confirm the version check job goes green.

2. **Verify the version locally:**

   ```bash
   cd apps/<app>
   hatch version
   # Should print exactly the tagged version, e.g., "0.4.0"
   ```

   The version test in CI must use the same scoped `--match` pattern as your
   `git_describe_command` in `pyproject.toml`. If the version test uses `--match v*`
   (too broad), it will pick up sibling package tags on multi-tag commits. Verify
   the CI test runs: `git describe --dirty --tags --long --match app-name/v*`.

3. **Confirm PyPI:** `pip index versions unifi-network-mcp` or check the PyPI project page.

4. **Install smoke test:**

   ```bash
   pip install --upgrade unifi-network-mcp
   python -c "import unifi_network_mcp; print(unifi_network_mcp.__version__)"
   ```

5. **Post-Release Live Smoke Verification (Full Release Validation):**

   After all tags are pushed and all PyPI packages are live, run a full post-release
   smoke test to verify API contracts work end-to-end with the released wheel versions:

   ```bash
   # Set .env credentials (real hardware or staging controller)
   # Then run the full three-domain smoke sequence:
   python scripts/live_smoke.py --server network --phase safe
   python scripts/live_smoke.py --server protect --phase safe
   python scripts/live_smoke.py --server access --phase safe
   ```

   All three phases must exit with status 0 and have zero failed/exception records in
   the artifacts. This confirms the released wheels work against real UniFi hardware
   and that API contracts hold. This is the final release validation gate — if any phase
   fails, the release is broken and requires either an immediate patch release or a
   rollback announcement.

---

## Cross-Cutting Gotchas

**Sibling tag contamination.** If `git_describe_command` `--match` is too broad
(e.g., `v*`), hatch-vcs picks up a sibling package's tag and reports the wrong
version. Symptom: `pip install unifi-network-mcp==0.14.13` installs a package that
prints `0.3.5` from `importlib.metadata`. Fix: tighten the `--match` pattern in
`raw-options.git_describe_command` in `pyproject.toml` and rebuild.

**PR merge is NOT the release trigger — the tag push is.** `hatch-vcs` reads git tags at build time to generate `_version.py`. Merging a PR does NOT trigger a release. If the tag is never pushed, PyPI stays on the old version with no error — the build succeeds but installs the previous release. The tag push IS the release trigger. (Session 3: `core/v0.1.2` was never tagged; PyPI stayed at 0.1.1 until the tag was pushed manually.) Always run Procedure H after tagging.

**Silent version freeze.** If a tag is missing, `hatch-vcs` falls back to `fallback_version = "0.0.0"` or the last matching tag. There is no error at merge time. The failure surfaces only when a user installs and notices the wrong version. Always run Procedure H after tagging.

**Missing tag causes broken downstream install.** If `unifi-core` code is merged but
`core/vX.Y.Z` is never pushed, downstream packages requesting `unifi-core>=X.Y.Z`
will fail to install — pip resolver error, not a code error. Check PyPI before
debugging code. The fix is to push the missing tag and wait for the publish workflow.

**Main-only merges are invisible to existing users.** Cache invalidation for plugin manifests requires a tagged release. A main-only merge updates the repo but does not trigger a publish workflow or invalidate any user caches. Existing users stay on their cached version indefinitely until the next tagged release. If a manifest or policy change is urgent, cut a patch release immediately (see Procedure A: Plugin-only Release).

**Malformed git tag — missing 'v' prefix.** During local tag creation, you may accidentally
create a tag like `protect/0.4.2` (no 'v') instead of `protect/v0.4.2`. This tag exists
locally but is syntactically wrong and will be ignored by hatch-vcs and CI workflows.
The malformed tag remains in your local tag list indefinitely, cluttering the namespace
and potentially confusing future releases. **Prevention:** Before pushing any tags, list
and validate them:
```bash
git tag -l | grep -E 'network|protect|access|relay|core|shared|api' | sort -V
# Validate every line contains '/v' prefix (e.g., "network/v0.14.13")
# If you see a malformed tag like "protect/0.4.2", delete it:
git tag -d protect/0.4.2
# Then create the correct one:
git tag protect/v0.4.2
```

**PyPI pin masked by workspace source — failure mode the entire CI matrix cannot detect.**
Workspace `[tool.uv.sources]` overrides the version range in `[project.dependencies]`
during `uv sync`/`uv lock`, so local dev, every test job, and `uv lock --check` all
pass with a stale pin. The pin is only enforced when pip/uv resolves the published
wheel against PyPI — i.e., on a user's machine via `uvx <pkg>@latest`. Docker images
also bypass the failure because the Dockerfiles use `uv sync --frozen --package <pkg>`
against the workspace lock. Symptom: fresh `uvx`/`pip install` of the freshly published
downstream package crashes immediately with `ModuleNotFoundError` for a module that
only exists in the just-published upstream version. Canonical occurrence: the 2026-05-17
coordinated release (network 0.18.0 / protect 0.4.0 / access 0.3.0 / relay 0.2.0) where
`unifi-mcp-shared>=0.4.5,<0.5` shipped alongside `from unifi_mcp_shared.metadata import …`
even though `metadata.py` only existed in shared 0.5.0; ~24h breakage, 4 reporters,
silently-affected user count a multiple of that, fixed by PR #284. Prevention: run the
wheel-metadata check in Procedure D before pushing tags. Never trust `uv lock --check`
as the gate for this class of bug.

**Batch tag push silently skips releases.** When `git push origin tag1 tag2 tag3` is used
to push multiple tags in one command, GitHub Actions only starts the workflow for the first
tag. Subsequent tags are queued but the workflows never execute, leaving PyPI on the old
version with no error or warning. The fix: push tags one at a time. This is a GitHub
orchestration issue, not a git or hatch-vcs bug. Always use individual `git push origin tag`
commands per tag and wait for PyPI confirmation between pushes.

**PyPI package names differ from directory names.** Always use the correct PyPI name when
installing, checking, or troubleshooting. `unifi-network-mcp` ≠ `unifi-mcp-network`. See
the Package Map for correct names. When debugging a release, verify the PyPI project page
uses the expected name.
