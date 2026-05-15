# Contributing

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
make network-test      # Run network server tests
make network-lint      # Lint network server
make network-manifest  # Regenerate network tools manifest
make protect-test      # Run protect server tests
make protect-lint      # Lint protect server
make protect-manifest  # Regenerate protect tools manifest
make access-test       # Run access server tests
make access-lint       # Lint access server
make access-manifest   # Regenerate access tools manifest
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

## Development Workflow

### Adding a tool to the network server

1. Add the manager method in `apps/network/src/unifi_network_mcp/managers/<domain>_manager.py`
2. Add the tool function in `apps/network/src/unifi_network_mcp/tools/<category>.py`
3. Add the tool name to `TOOL_MODULE_MAP` in `apps/network/src/unifi_network_mcp/utils/lazy_tool_loader.py`
4. Run `make network-manifest` from the repo root (or `make manifest` from `apps/network/`)
5. Add tests in `apps/network/tests/`
6. Commit code + manifest + tests together

### Adding a tool to the protect server

1. Add the manager method in `apps/protect/src/unifi_protect_mcp/managers/<domain>_manager.py`
2. Add the tool function in `apps/protect/src/unifi_protect_mcp/tools/<category>.py`
3. Run `make protect-manifest` from the repo root (or `make manifest` from `apps/protect/`)
   - The manifest auto-discovers tools from `@server.tool()` decorators; no manual map update needed
4. Add tests in `apps/protect/tests/`
5. Commit code + manifest + tests together

### Adding a tool to the access server

1. Add the manager method in `apps/access/src/unifi_access_mcp/managers/<domain>_manager.py`
2. Add the tool function in `apps/access/src/unifi_access_mcp/tools/<category>.py`
3. Run `make access-manifest` from the repo root (or `make manifest` from `apps/access/`)
4. Add tests in `apps/access/tests/`
5. Commit code + manifest + tests together

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

# Specific test file
uv run --package unifi-network-mcp pytest apps/network/tests/unit/test_permissions.py -v
uv run --package unifi-protect-mcp pytest apps/protect/tests/unit/test_camera_tools.py -v
uv run --package unifi-access-mcp pytest apps/access/tests/unit/test_door_tools.py -v
```

Tests use `pytest-asyncio` for async support and `aioresponses` for HTTP mocking.

## Release Process (Maintainers)

1. Run `make pre-commit` from root.
2. Determine release scope by package tag namespace (`core/v*`, `shared/v*`, `network/v*`, `protect/v*`, `access/v*`, `api/v*`, `relay/v*`, `worker/v*`).
3. If a downstream package needs code from a newly released upstream package, update its `pyproject.toml` dependency range before tagging. For example, Protect/API releases that require new `unifi-core` models must allow the new `unifi-core` line.
4. Run `uv lock --check` and commit any dependency-bound changes before creating local tags.
5. Push tags in dependency order: `core` first, then `shared`, then app/API packages, then `relay`, then `worker` if the worker needs the released relay behavior. Wait for each upstream package to appear on PyPI before pushing dependents.
6. CI publishes to PyPI or npm, builds Docker images where applicable, and creates GitHub Releases.

## Questions?

Open an issue or discussion at https://github.com/sirkirby/unifi-mcp/issues
