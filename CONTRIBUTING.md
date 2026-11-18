# Contributing

Thanks for helping improve UniFi MCP. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md) in all project spaces.

## Before You Start

- Search existing issues and discussions before opening a new one.
- For substantial features, behavior changes, or new tool categories, open an
  issue first so maintainers can confirm the direction before you invest time.
- Proposing a new server for another UniFi application? Read
  [Proposing a new server](#proposing-a-new-server) first: a new server has to
  ship complete.
- Use [GitHub Discussions](https://github.com/sirkirby/unifi-mcp/discussions)
  for setup help, configuration questions, and general troubleshooting.
- Do not include UniFi credentials, API keys, tokens, controller addresses, or
  other private deployment details in public issues, discussions, pull requests,
  screenshots, or logs.
- For a Network, Protect, or Access MCP bug, prefer a reviewed
  [sanitized support bundle](docs/support-bundles.md) over raw tool output or
  diagnostic logs. The Site Manager server has no support bundle; describe the
  problem by hand and follow its
  [troubleshooting guide](apps/sitemanager/docs/troubleshooting.md).
  The InnerSpace server has no support bundle either; follow its
  [troubleshooting guide](apps/innerspace/docs/troubleshooting.md).
- Report suspected vulnerabilities privately through
  [GitHub Security Advisories](https://github.com/sirkirby/unifi-mcp/security/advisories),
  not public issues.

For more support routing details, see [SUPPORT.md](SUPPORT.md).

## Where to Start Reading

New to the codebase? Read these in order:

1. **[README.md](README.md)** -- project overview and installation
2. **[QUICKSTART.md](QUICKSTART.md)** -- get a server running in 5 minutes
3. **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** -- monorepo layout, package responsibilities, and the tool/manager/connection layering
4. **[AGENTS.md](AGENTS.md)** -- architecture rules, coding conventions, and permission/confirmation patterns enforced across servers
5. **[docs/README.md](docs/README.md)** -- full documentation index (tool loading modes, permissions, deployment)

The Monorepo Layout table below and the Development Workflow section are the fastest way to find where a change belongs once you know what you're changing.

## Prerequisites

- Python 3.13+
- Node.js 22+ for the Cloudflare Worker app
- [uv](https://docs.astral.sh/uv/) (package manager)

## Setup

```bash
git clone https://github.com/sirkirby/unifi-mcp.git
cd unifi-mcp
make sync
```

This installs all Python workspace packages in development mode plus the self-contained worker npm dependencies.

## Monorepo Layout

| Path | What | Makefile |
|------|------|----------|
| `/` | Workspace root | `make test` runs all tests |
| `apps/network/` | Network MCP server | `make test`, `make lint`, `make manifest` |
| `apps/protect/` | Protect MCP server | `make test`, `make lint`, `make manifest` |
| `apps/access/` | Access MCP server | `make test`, `make lint`, `make manifest` |
| `apps/sitemanager/` | Site Manager MCP server (cloud account, read-only) | `make test`, `make lint`, `make manifest` |
| `apps/innerspace/` | InnerSpace MCP server (console login, read-only; not yet released) | `make test`, `make lint`, `make manifest` |
| `apps/worker/` | Cloudflare Worker gateway + npm CLI | `make check` |
| `packages/unifi-core/` | Shared connectivity | Tested via root `make core-test` |
| `packages/unifi-mcp-shared/` | Shared MCP patterns | Tested via root `make shared-test` |

## Root Makefile

The root Makefile delegates to app/package Makefiles:

```bash
make test              # Run ALL tests (core + shared + relay + worker + apps)
make check             # Run format check + lint + generated drift checks + tests
make build             # Build deployable artifacts, including the worker typecheck
make sync              # Install Python workspace + worker npm dependencies
make lint              # Lint all packages
make format            # Format all packages
make pre-commit        # Format + lint + test

# Individual packages
make core-test         # Run unifi-core tests
make shared-test       # Run unifi-mcp-shared tests
make relay-test        # Run unifi-mcp-relay tests
make worker-build      # Install worker deps + typecheck the Worker app
make worker-check      # Run worker CLI tests + TypeScript checks

# Individual apps (network, protect, access, sitemanager, innerspace) — see "App-Level Makefile" below
make -C apps/network test      # Run network server tests
make -C apps/network lint      # Lint network server
make -C apps/network manifest  # Regenerate network tools manifest
```

## App-Level Makefile

For focused work on the network server:

```bash
cd apps/network
make test         # Run network tests
make lint         # Lint network code
make format       # Format network code
make manifest     # Regenerate tools_manifest.json
make run-lazy     # Run in lazy mode (default)
make run-eager    # Run in eager mode
make run-meta     # Run in meta_only mode
make pre-commit   # Format + lint + test
```

The protect and access servers have the same targets:

```bash
cd apps/protect
make test         # Run protect tests
make lint         # Lint protect code
make format       # Format protect code
make manifest     # Regenerate tools_manifest.json
make run-lazy     # Run in lazy mode (default)
make run-eager    # Run in eager mode
make run-meta     # Run in meta_only mode
make console      # Start interactive dev console
make pre-commit   # Format + lint + test
```

```bash
cd apps/access
make test         # Run access tests
make lint         # Lint access code
make format       # Format access code
make manifest     # Regenerate tools_manifest.json
make run-lazy     # Run in lazy mode (default)
make run-eager    # Run in eager mode
make run-meta     # Run in meta_only mode
make console      # Start interactive dev console
make pre-commit   # Format + lint + test
```

The Site Manager server has a smaller set: it has no dev console, and `make run`
starts it in lazy mode.

```bash
cd apps/sitemanager
make test         # Run sitemanager tests
make lint         # Lint sitemanager code
make format       # Format sitemanager code
make manifest     # Regenerate tools_manifest.json
make run          # Run the server locally (lazy mode)
make pre-commit   # Format, manifests, lint and test
```

The InnerSpace server's targets are the same, from `apps/innerspace`. Its tests
never contact a console: they use a loopback stub or a fake manager. A live run
needs a console with InnerSpace installed and a login of your own.

Site Manager's tests never call `api.ui.com`; they pass a loopback `base_url` to the
connection manager or mock the transport. A live read-only smoke run needs a
Site Manager API key of your own and is skipped without one:
`uv run --all-packages python scripts/live_smoke.py --server sitemanager --phase readonly`.

## Development Workflow

Managers live in `unifi-core`, not in the app. A manager change ships in a
`unifi-core` release, so an app that calls a new manager method raises its
`unifi-core` floor once that release is on PyPI (see
[What reviewers check](#what-reviewers-check)).

### Adding a tool to the network server

1. Add the manager method in `packages/unifi-core/src/unifi_core/network/managers/<domain>_manager.py`, with tests in `packages/unifi-core/tests/network/`
2. Add the tool function in `apps/network/src/unifi_network_mcp/tools/<category>.py`
3. Run `make manifest` from `apps/network/` (or `make manifest` from the repo root to regenerate every app)
   - The lazy-loading tool map is built from the tool modules and the manifest; no manual map update needed
4. Add tests in `apps/network/tests/`
5. Commit code + manifest + tests together

### Adding a tool to the protect server

1. Add the manager method in `packages/unifi-core/src/unifi_core/protect/managers/<domain>_manager.py`, with tests in `packages/unifi-core/tests/protect/`
2. Add the tool function in `apps/protect/src/unifi_protect_mcp/tools/<category>.py`
3. Run `make manifest` from `apps/protect/` (or `make manifest` from the repo root to regenerate every app)
   - The manifest auto-discovers tools from `@server.tool()` decorators; no manual map update needed
4. Add tests in `apps/protect/tests/`
5. Commit code + manifest + tests together

### Adding a tool to the access server

1. Add the manager method in `packages/unifi-core/src/unifi_core/access/managers/<domain>_manager.py`, with tests in `packages/unifi-core/tests/access/`
2. Add the tool function in `apps/access/src/unifi_access_mcp/tools/<category>.py`
3. Run `make manifest` from `apps/access/` (or `make manifest` from the repo root to regenerate every app)
4. Add tests in `apps/access/tests/`
5. Commit code + manifest + tests together

### Adding a tool to the sitemanager server

The Site Manager server is read-only by design, and its destination is the
fixed `api.ui.com` origin. Follow the "Site Manager credential isolation" rules
in [AGENTS.md](AGENTS.md) before adding a tool.

1. Add the manager method under `packages/unifi-core/src/unifi_core/sitemanager/managers/`, with tests in `packages/unifi-core/tests/sitemanager/`
2. Add the tool function in `apps/sitemanager/src/unifi_sitemanager_mcp/tools/<category>.py`
3. Run `make manifest` from `apps/sitemanager/` (or `make manifest` from the repo root to regenerate every app)
4. Add tests in `apps/sitemanager/tests/`
5. Commit code + manifest + tests together

### Adding a tool to the innerspace server

The InnerSpace server is read-only in this version, and it reads through a
console login session only. Follow the "InnerSpace session isolation" rules in
[AGENTS.md](AGENTS.md) before adding a tool. A tool that writes needs its own
design first: open an issue.

1. Add the manager method under `packages/unifi-core/src/unifi_core/innerspace/managers/`
2. Add the tool function in `apps/innerspace/src/unifi_innerspace_mcp/tools/<category>.py`, with the `ToolAnnotations(readOnlyHint=True, ...)`, `permission_category`, `permission_action="read"` and `auth="local_only"` the other tools carry
3. Run `make manifest` from `apps/innerspace/` (or `make manifest` from the repo root to regenerate every app)
4. If the tool should also be served by `unifi-api-server`, add its REST route and GraphQL field in the same pull request and regenerate the action catalog
5. Add tests in `apps/innerspace/tests/`
6. Commit code + manifest + tests together

### Adding a shared package feature

1. Make the change in `packages/unifi-core/` or `packages/unifi-mcp-shared/`
2. Run the relevant package tests: `make core-test` or `make shared-test`
3. Run `make test` to verify nothing breaks across the workspace

### Code quality

Before committing:

```bash
make pre-commit   # Format + lint + all tests
```

Or from the app directory:
```bash
cd apps/network && make pre-commit
```

Formatting uses [ruff](https://docs.astral.sh/ruff/) with a 120-character line length.

## Proposing a new server

New servers are welcome as pull requests. They are held to the same bar as the
servers maintainers built, because once one ships, users and maintainers carry
it. Pull requests rarely reach that bar on the first pass. Maintainers will close
the gap with you, by review or by pushing to your branch. The bar does not move.

### Open an issue first

Say:
- which application it covers;
- which API it uses: official or internal, and its credential;
- which tools are reads and which are writes;
- which application version and hardware you test on;
- whether you can re-test when the application updates.

Writes against an internal API need someone who can keep re-testing them, or
they are not accepted.

### What "complete" means

1. **Core first.** The client and managers live in `packages/unifi-core/`. Any
   shared change lives in `packages/unifi-mcp-shared/`. They go in their own PR,
   which is released before the server PR, because the server's pin-alignment
   check needs them on PyPI.
2. **The server app.** Follow "Adding a New Server" in
   [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), including every release and
   check registration it lists.
3. **API parity.** Every tool is also reachable through `unifi-api-server`, and
   `apps/api/tests/test_resource_route_coverage.py` covers the new product.
4. **Permissions.** Writes register a policy-gate prefix, preview before they
   confirm, and follow the [AGENTS.md](AGENTS.md) permission rules.
5. **Live evidence.** Add a target in `scripts/live_smoke.py` and post its
   results from real hardware, with identifiers removed.
6. **Deployment.** A Dockerfile and a Docker Compose service.
7. **Docs.**
   - The app's README and `docs/`: configuration, tools and troubleshooting.
   - The root README, QUICKSTART and docs site tables.
   - Docs that tell people to install the package (install commands, badges)
     merge only after it is on PyPI.
8. **Plugin bundle.** Claude Code and Codex manifests, a setup skill and
   references. They land with or after the first release tag.
9. **Support bundle,** or a stated reason the server has none.

### Order of work

1. Core PR.
2. Release core.
3. Server PR, reads first. Writes can follow in their own PR.
4. Release the server.
5. Plugin, docs and the install-instruction docs.

Maintainers register the PyPI trusted publisher and own the package name.

## What reviewers check

These come up in review again and again. Getting them right before you open a
pull request saves a round trip. To keep high-priority and security fixes
moving, maintainers may push these corrections to your branch directly. You keep
the authorship credit.

- **One package per PR when a boundary is crossed.** Put changes to
  `unifi-core` or `unifi-mcp-shared` in their own PR. It is released before a
  downstream PR that depends on it.
- **Evidence from real hardware.** For anything that calls a UniFi API, show a
  run against a real controller with its application version.
  - For a write, show the write and a read-back.
  - Mock tests alone do not count: response shapes differ between versions.
- **Writes that cannot clobber.**
  - Preview first (`confirm=false`).
  - Read back after writing.
  - Declare `permission_action` and `confirm`, so the operation gate runs the
    confirmed write one at a time and two calls cannot overwrite each other. Do
    not add your own write lock.
  - State any remaining race in the docstring, such as another client editing
    the same controller.
- **Typed tools, not passthroughs.** One tool per setting or resource, with
  validation. Generic "read or write any setting" accessors are declined.
- **One ID family per tool.** V2 and Integration IDs never mix in one tool, and
  no tool silently translates between them. See "API tool families" in
  [AGENTS.md](AGENTS.md).
- **Unavailable is not empty.** When the controller no longer serves something,
  return an error that says so, never an empty success.
- **Lean tool descriptions.** A tool's description gives its purpose and a brief
  shape. Explain individual fields in Pydantic `Field` descriptions.
- **Redaction is server policy.** Never add a request argument that returns
  secrets. See "Response redaction" in [AGENTS.md](AGENTS.md).
- **House style.**
  - Use `%s` logging, never f-strings.
  - Never put issue or PR numbers in code, comments or tests: describe the
    behaviour instead.
  - Commit the regenerated artifacts from `make pre-commit`.
- **Docs in the same PR as the tool.** For a new tool, update the README, the
  app README, the app's `docs/tools.md`, `docs/ARCHITECTURE.md`, and the
  plugin's skill.
- **No private details.** Keep credentials, IP addresses, MAC addresses,
  hostnames and SSIDs out of PRs, issues, commits and test fixtures.

## PR Conventions

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make changes, run `make pre-commit`
4. Push and open a PR against `main`
5. All PRs require passing CI (lint + test)

**Do not push directly to `main`.**

Commit message style:
- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation only
- `refactor:` code change that neither fixes a bug nor adds a feature
- `test:` adding or updating tests
- `chore:` maintenance (deps, CI, config)

## Running Tests

```bash
# All tests
make test

# With coverage
cd apps/network && make test-cov
cd apps/protect && make test-cov
cd apps/access && make test-cov
cd apps/sitemanager && make test-cov
cd apps/innerspace && make test-cov

# Specific test file
uv run --package unifi-network-mcp pytest apps/network/tests/unit/test_permissions.py -v
uv run --package unifi-protect-mcp pytest apps/protect/tests/unit/test_camera_tools.py -v
uv run --package unifi-access-mcp pytest apps/access/tests/unit/test_door_tools.py -v
```

Tests use `pytest-asyncio` for async support and `aioresponses` for HTTP mocking.

## Release Process (Maintainers)

These steps release Python packages and the Worker by tag. Plugins release by
merge; see [Plugin changes](#plugin-changes). The `monorepo-release-pipeline`
skill is the full procedure for both.

1. Run `make pre-commit` from root.
2. Determine release scope by package tag namespace (`core/v*`, `shared/v*`, `network/v*`, `protect/v*`, `access/v*`, `sitemanager/v*`, `innerspace/v*`, `api/v*`, `relay/v*`, `worker/v*`).
3. Build release batches from actual dependency edges. A downstream package must wait when its
   wheel metadata names the new upstream version, its code requires a newly published upstream API,
   or its release workflow installs that new version. Existing compatible bounds alone do not
   require a wait. Also keep Worker out of any batch containing a tag namespace configured in
   `bump-plugin-versions.yml`: both workflows push writebacks to `main` without shared concurrency
   or a non-fast-forward retry. Finish and fetch the plugin writeback before pushing Worker. An
   API-only tag may share the Worker batch because it does not trigger plugin sync.
4. Prepare dependency-bound changes per batch. If a downstream floor names an upstream version that
   is not published yet, publish and validate the upstream batch first. Then update the downstream
   `pyproject.toml` range, run `uv lock --check`, land that change on `main`, and create the downstream
   tags from the updated commit. Never make the upstream tag wait on a floor bump that cannot pass
   pin alignment until that upstream version exists on PyPI.
5. Within each batch, push every tag back-to-back using a separate `git push origin <tag>` command
   for each ref, then monitor the workflows concurrently. Do not combine multiple refs in one push.
   Before starting a dependent batch, confirm each required upstream artifact is available on PyPI
   or npm and its release workflow passed.
6. CI publishes to PyPI or npm, builds Docker images where applicable, and creates GitHub Releases.
   When a batch includes a tag namespace configured in `bump-plugin-versions.yml`, wait for the final
   version-sync run. Network, Protect, or Access tags must produce the expected consolidated
   writeback to `main`. A Core-, Shared-, or Relay-only trigger may complete successfully with
   `No version changes to commit`; do not require a nonexistent writeback. API-only and Worker-only
   batches do not trigger that workflow.

### Plugin changes

Plugins release by merge, not by tag: a plugin release is a version bump landing
on `main`. Every change under `plugins/<name>/`, including docs, skills and setup
scripts, needs a version bump of that plugin in the same PR. Run
`make check-plugin-versions` and `make check-plugin-tool-refs` (both in
`make pre-commit`; fetch history and tags first). The second fails when a shipped
plugin file names a tool missing from the server release the plugin pins. Bump
sizes, client update steps and release rules are in the `monorepo-release-pipeline`
skill (Procedure E); user-facing support is in [plugin support](docs/plugin-support.md).
When a release changes what existing users must do (a setting moves, a command
changes, a migration is needed), add its notes to the
[plugin upgrade guide](docs/plugin-upgrade.md). Real-client evidence for the
support matrix comes from the [plugin acceptance procedure](docs/plugin-acceptance.md),
run from `main` after the release merge.

To try a Claude Code plugin change locally, run
`claude --plugin-dir plugins/<name>`. That loads your working copy for the session
and silently replaces an installed marketplace copy with the same manifest name:
`claude plugin list` still shows the marketplace plugin as enabled, and only a
`--debug` session logs that `--plugin-dir` overrode it. Managed settings that lock
the plugin take precedence over `--plugin-dir`. Local loading does not exercise the
marketplace path, where the installed copy under
`~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/` changes only when the
version changes, so the release is verified from `main` after merge.

## Questions?

Review the [support bundle guide](docs/support-bundles.md), then open an issue or
discussion at https://github.com/sirkirby/unifi-mcp/issues
