---
name: myco:monorepo-release-pipeline
description: >-
  Covers the full release pipeline for the unifi-mcp monorepo: determining release scope by analyzing changed packages, scoping hatch-vcs version tag globs per Python package to prevent sibling-tag contamination, pushing tags in strict dependency order (unifi-core → unifi-mcp-shared → app servers → relay → worker when needed), configuring scripts/generate_release_notes.py path scoping per package, wiring per-package publish workflows for OIDC trusted publishing, coordinating cross-package version bumps in pyproject.toml, understanding app vs. library versioning and writeback behavior, and validating releases post-tag. Apply this skill when cutting any release, adding a new package, bumping unifi-core, or debugging a versioning or publish-workflow failure — even if the user does not explicitly ask about tag ordering or release notes.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Monorepo Release Pipeline

The unifi-mcp repo ships seven independently versioned Python packages plus the
Node/TypeScript worker app: `unifi-core`
and `unifi-mcp-shared` live under `packages/`; `unifi-mcp-network`, `unifi-mcp-protect`,
`unifi-mcp-access`, and `unifi-api-server` live under `apps/`; `unifi-mcp-relay` lives under `packages/`
alongside core and shared; `unifi-mcp-worker` lives under `apps/worker/` and publishes to npm.
Each has its own package identity, tag namespace, publish workflow, and release-notes scope. Getting the release sequence wrong leaves downstream
packages referencing non-existent PyPI versions or produces contaminated release notes
that bleed across package boundaries.

## Prerequisites

- All feature PRs for the release are merged to `main`.
- Working tree is clean: `git status` shows nothing staged or modified.
- Remote is current: `git fetch origin && git log origin/main..HEAD` shows nothing.
- PyPI credentials are **not** stored locally — publishing is handled entirely by
  GitHub Actions OIDC trusted publishing (no `TWINE_PASSWORD`, no `PYPI_TOKEN`).
- Decide which packages are changing and their new versions before pushing any tag.

## Package Map

| Package | Directory | Tag namespace | Publish workflow |
|---|---|---|---|
| `unifi-core` | `packages/unifi-core/` | `core/v*` | `release-core.yml` |
| `unifi-mcp-shared` | `packages/unifi-mcp-shared/` | `shared/v*` | `release-shared.yml` |
| `unifi-mcp-network` | `apps/network/` | `network/v*` | `release-network.yml` |
| `unifi-mcp-protect` | `apps/protect/` | `protect/v*` | `release-protect.yml` |
| `unifi-mcp-access` | `apps/access/` | `access/v*` | `release-access.yml` |
| `unifi-api-server` | `apps/api/` | `api/v*` | `release-api.yml` |
| `unifi-mcp-relay` | `packages/unifi-mcp-relay/` | `relay/v*` | `release-relay.yml` |
| `unifi-mcp-worker` | `apps/worker/` | `worker/v*` | `release-worker.yml` |

When adding a new package, extend this table and the release-notes path configuration
before pushing any tag.

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

## Procedure B: App vs. Library Versioning and Writeback Behavior

Understanding the difference between library and app package versioning is essential because writeback behavior differs, and missing writeback from an app package is a bug — while missing writeback from a library package is correct.

### Library packages (unifi-core, unifi-mcp-shared, relay)

These packages use `dynamic = [\"version\"]` in `pyproject.toml` with hatch-vcs. Version is derived from the git tag **at build time** — no `_version.py` is ever committed to the repo. When a library tag is pushed:

- The publish workflow builds and publishes the tagged commit as-is
- `bump-plugin-versions.yml` runs and outputs: `No version changes to commit`
- This is **correct and expected** — not a bug or a missed step
- There is no manifest file to update (no plugin.json or server.json)

### App packages (network, protect, access)

These packages have writable manifest assets that get updated on tag:

- `plugins/unifi-network/.claude-plugin/plugin.json`
- `plugins/unifi-protect/.claude-plugin/plugin.json`
- `plugins/unifi-access/.claude-plugin/plugin.json`
- `apps/{network,protect,access}/server.json`

When an app tag is pushed, the workflow commits a version writeback to these files.
If the writeback commit is missing, the manifests will be stale and users will see
the wrong version reported by the tool.

**Rule:** Never expect writeback from a library package tag. Never accept a
missing writeback from an app package tag.

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

## Procedure D: Align Cross-Package Dependency Bounds Before Tagging

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
4. Run `uv lock --check` after the edits.
5. Commit dependency-bound changes before creating local tags.

If dependency bounds are stale, the release can publish successfully but install an
older upstream package that lacks the required API surface. Treat dependency-bound
alignment as part of the release artifact, not as optional cleanup.

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

**Verification:** After a release workflow completes and the bumper runs, check the
manifest commit in GitHub. The `plugin.json` and `server.json` should have updated
version strings (e.g., `"version": "0.14.14"`), NOT corrupted field names.

## Procedure F: Dependency-Ordered Tag Pushing

The dependency graph:

```
unifi-core  →  unifi-mcp-shared  →  unifi-mcp-network
                                  →  unifi-mcp-protect
                                  →  unifi-mcp-access
                                  →  unifi-mcp-relay
            →  unifi-api-server
```

**Rule:** Push upstream tags first. Wait for PyPI to confirm the package is live
before pushing downstream tags. Downstream packages declare a minimum version of their
upstream dependencies in `pyproject.toml`; if the upstream version is not yet on PyPI
when the downstream workflow runs, pip will fail to resolve the dependency.

### Tag push sequence

```bash
# Step 1 — upstream foundation
git tag core/v0.2.0
git push origin core/v0.2.0
# WAIT: confirm https://pypi.org/project/unifi-core/ shows 0.2.0 before continuing

# Step 2 — shared layer
git tag shared/v0.4.0
git push origin shared/v0.4.0
# WAIT: confirm https://pypi.org/project/unifi-mcp-shared/ shows 0.4.0

# Step 3 — app servers and API (siblings after core/shared are live)
git tag network/v0.14.13
git tag protect/v0.3.5
git tag access/v0.2.4
git tag api/v0.2.1
git push origin network/v0.14.13 protect/v0.3.5 access/v0.2.4 api/v0.2.1
# Siblings can be pushed together — same dependency level

# Step 4 — relay
git tag relay/v0.1.0
git push origin relay/v0.1.0

# Step 5 — worker, if relay/worker behavior changed
git tag worker/v1.3.1
git push origin worker/v1.3.1
```

**Never batch tags across dependency levels.** Running
`git push origin core/v0.2.0 network/v0.14.13` in a single push fires both publish
workflows simultaneously. The network workflow may start before the core package is
indexed on PyPI (~2–5 minutes after the core workflow completes).

**Worker app:** `apps/worker` has a separate npm release flow using OIDC via GitHub Actions.
Apply the same ordering principle: if the worker depends on a Python package version or relay
protocol behavior, confirm the upstream PyPI release is updated before pushing the `worker/v*` tag.

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

3. **Confirm PyPI:** `pip index versions unifi-mcp-<app>` or check the PyPI project page.

4. **Install smoke test:**

   ```bash
   pip install --upgrade unifi-mcp-<app>
   python -c "import unifi_mcp_<app>; print(unifi_mcp_<app>.__version__)"
   ```

## Cross-Cutting Gotchas

**Sibling tag contamination.** If `git_describe_command` `--match` is too broad
(e.g., `v*`), hatch-vcs picks up a sibling package's tag and reports the wrong
version. Symptom: `pip install unifi-mcp-network==0.14.13` installs a package that
prints `0.3.5` from `importlib.metadata`. Fix: tighten the `--match` pattern in
`raw-options.git_describe_command` in `pyproject.toml` and rebuild.

**PR merge is NOT the release trigger — the tag push is.** `hatch-vcs` reads git tags at build time to generate `_version.py`. Merging a PR does NOT trigger a release. If the tag is never pushed, PyPI stays on the old version with no error — the build succeeds but installs the previous release. The tag push IS the release trigger. (Session 3: `core/v0.1.2` was never tagged; PyPI stayed at 0.1.1 until the tag was pushed manually.) Always run Procedure H after tagging.

**Silent version freeze.** If a tag is missing, `hatch-vcs` falls back to `fallback_version = "0.0.0"` or the last matching tag. There is no error at merge time. The failure surfaces only when a user installs and notices the wrong version. Always run Procedure H after tagging.

**Missing tag causes broken downstream install.** If `unifi-core` code is merged but
`core/vX.Y.Z` is never pushed, downstream packages requesting `unifi-core>=X.Y.Z`
will fail to install — pip resolver error, not a code error. Check PyPI before
debugging code. The fix is to push the missing tag and wait for the publish workflow.

**Main-only merges are invisible to existing users.** Cache invalidation for plugin manifests requires a tagged release. A main-only merge updates the repo but does not trigger a publish workflow or invalidate any user caches. Existing users stay on their cached version indefinitely until the next tagged release. If a manifest or policy change is urgent, cut a patch release immediately (see Procedure A: Plugin-only Release).
