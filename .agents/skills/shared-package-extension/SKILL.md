---
name: myco:shared-package-extension
description: |
  Apply when extending unifi-mcp-shared with new entrypoints, deciding whether
  new capability belongs in unifi-core vs. unifi-mcp-shared, syncing relay
  protocol changes, or bumping workspace dependency versions across the monorepo.
  Covers four recurring procedures: (1) DI-only rule for shared-package entrypoints
  to avoid circular-import blast radius across all three app servers; (2) the
  "connectivity primitive or MCP layer?" scope gate for placing new capability in
  the right package; (3) manual relay protocol sync to discovery.py and protocol.py
  when shared-package protocol changes, because those files do not import from the
  shared package and won't pick up changes automatically; (4) lockstep pyproject.toml
  version bumping across unifi-mcp-shared and all four dependent apps when unifi-core
  is versioned. Activate this skill even if the user doesn't explicitly ask about
  isolation boundaries — any shared-package surgery or monorepo dependency bump
  triggers it.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Shared Package Extension and Isolation Boundaries

The monorepo has three structural packages with hard isolation rules: `unifi-core`
(connectivity primitives), `unifi-mcp-shared` (MCP layer — permissions, confirmation
flow, lazy loading, config), and `unifi-mcp-relay` (relay sidecar). Every time
`unifi-mcp-shared` gains a new entrypoint, every time `unifi-core` is versioned, or
every time the relay protocol changes, a specific procedure applies. Skipping them
causes import-time startup failures or silent protocol drift.

## Prerequisites

- Working in the monorepo at the repo root
- `uv` is the package manager; Python 3.13+ is enforced by workspace constraints
- Know which scenario applies: new shared entrypoint, scope decision, relay sync,
  or workspace version bump — each has its own procedure below

## Procedure A: Adding a New Entrypoint to `unifi-mcp-shared` (DI-Only Rule)

Every new entrypoint in `packages/unifi-mcp-shared/` must accept app-specific hooks
as parameters — never import directly from `unifi_network_mcp`, `unifi_protect_mcp`,
or `unifi_access_mcp` inside the shared package.

**Why this matters:** The shared package is already depended on by all three app
servers. A direct import back into any app server creates a cycle that breaks all
three servers at import time. The blast radius is total — no app server starts, and
the `ImportError` stack trace points at the shared package, making the root cause
non-obvious. This is the #1 documented contributor mistake in this codebase.

**Canonical pattern (correct):**

```python
# packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py
def register_meta_tools(
    mcp,
    get_tools_fn,        # injected by the calling app server
    get_server_info_fn,  # injected by the calling app server
):
    """Register meta tools. App-specific behavior provided via DI parameters."""
    ...
```

```python
# packages/unifi-mcp-shared/src/unifi_mcp_shared/permissioned_tool.py
def setup_permissioned_tool(
    mcp,
    tool_fn,
    permission_checker,  # injected hook — never imported from the app
):
    ...
```

**Anti-pattern (wrong):**

```python
# packages/unifi-mcp-shared/some_module.py
from unifi_network_mcp.config import get_config  # ← circular; breaks all three servers
```

**Steps:**

1. Write the new entrypoint with all app-specific behavior expressed as callable
   parameters or `typing.Protocol` types defined in the shared package.
2. Verify no app imports slipped in:
   ```bash
   grep -r "from unifi_network_mcp\|from unifi_protect_mcp\|from unifi_access_mcp" \
       packages/unifi-mcp-shared/
   ```
   Any hit is a bug — replace with an injected parameter.
3. Wire the injection at each app-server call site.
4. Confirm no circular import across all three servers:
   ```bash
   python -c "import unifi_network_mcp"
   python -c "import unifi_protect_mcp"
   python -c "import unifi_access_mcp"
   ```

**Tip:** For complex injected hooks, prefer a `typing.Protocol` over a bare
`Callable`. It lets mypy catch mismatches at the call site in each app server
rather than failing at runtime.

## Procedure B: Scope Gate — `unifi-core` vs. `unifi-mcp-shared`

Before adding new capability to either package, apply this decision test:

> **"Is this a connectivity primitive or an MCP layer concern?"**

| Belongs in `unifi-core` | Belongs in `unifi-mcp-shared` |
|---|---|
| Auth / session management | Permission checking |
| HTTP retry logic | Confirmation flow |
| Response merge / pagination | Lazy tool loading |
| Exception types | MCP config management |
| Connection pooling | Tool registration helpers |
| UniFi API request primitives | Meta-tools |

**Decision tree:**

1. Does the code talk directly to UniFi hardware or manage HTTP sessions? → `unifi-core`
2. Does the code coordinate MCP protocol concerns (permissions, tool registration,
   confirmations, config loading)? → `unifi-mcp-shared`
3. Does the code reference MCP types (`mcp`, `FastMCP`, tool decorators)? → `unifi-mcp-shared`
4. Still unclear? Ask: "Would this be useful in a non-MCP CLI that calls the UniFi API?"
   - Yes → `unifi-core`
   - No → `unifi-mcp-shared`

**After placing, verify the import direction is preserved:**

```
unifi_network_mcp  →  unifi-mcp-shared  →  unifi-core
unifi_protect_mcp  →  unifi-mcp-shared  →  unifi-core
unifi_access_mcp   →  unifi-mcp-shared  →  unifi-core
```

Arrows flow left-to-right only. No package imports from anything to its right in
this chain. Check with:

```bash
grep -r "from unifi_mcp_shared\|import unifi_mcp_shared" packages/unifi-core/
grep -r "from unifi_network_mcp\|from unifi_protect_mcp\|from unifi_access_mcp" \
    packages/unifi-mcp-shared/ packages/unifi-core/
```

Both commands should return nothing.

## Procedure C: Relay Protocol Sync

`packages/unifi-mcp-relay/` depends on `unifi-mcp-shared` (declared in its
`pyproject.toml`) and uses `unifi-core` transitively. However, the two files that
implement relay-specific protocol logic do **not** import from the shared package:

- `packages/unifi-mcp-relay/src/unifi_mcp_relay/discovery.py` — MCP protocol
  discovery (initialize handshake, tools/list, lazy-tool index)
- `packages/unifi-mcp-relay/src/unifi_mcp_relay/protocol.py` — relay wire format
  (WebSocket message types, `PROTOCOL_VERSION`, `RegisterMessage`)

**Consequence:** When the shared-package protocol changes (new message format, new
handshake field, changed endpoint path), those changes are **not automatically
reflected in these relay files**. There is no import error, no failing test, and no
CI check that catches relay protocol drift — it fails silently at runtime when a
client using the new protocol connects through a relay running the old one.

**Steps:**

1. Identify exactly what changed in `unifi-mcp-shared` (message schema field,
   endpoint path, header name, error envelope shape).
2. Open both relay files and locate the parallel implementation of the changed behavior.
3. Port the change manually — `discovery.py` and `protocol.py` share no abstractions
   with the shared package.
4. Trace the message path end-to-end through both implementations to confirm they agree.
5. If a meaningful test exists for the relay, run it; otherwise document the manual
   verification you performed in the PR.

**PR checklist trigger:** Any PR modifying the shared-package protocol must include a
"relay sync" section confirming `discovery.py` and `protocol.py` were reviewed and
updated if necessary. Community PR reviewers: look for this section.

## Procedure D: Workspace Dependency Version Bumping

When `unifi-core` is released at a new version, all dependents must be updated in
lockstep. `uv` workspace constraints enforce Python 3.13+ and will reject inconsistent
version pins.

**Dependent `pyproject.toml` files to update (five total):**

- `packages/unifi-mcp-shared/pyproject.toml`
- `apps/network/pyproject.toml`
- `apps/protect/pyproject.toml`
- `apps/access/pyproject.toml`
- `apps/api/pyproject.toml`

**Steps:**

1. Confirm the new `unifi-core` version (e.g., `0.4.0`).
2. Update the `unifi-core` entry in each of the five files:
   ```toml
   unifi-core = ">=0.4.0"
   ```
3. From the repo root, run `uv sync` to validate workspace constraints resolve cleanly.
   A failure here usually means a file was missed.
4. Commit all six files together (the `unifi-core` bump commit plus all five dependents)
   in a single commit. Never split — an intermediate state where some dependents still
   reference the old version breaks CI for any checkout between the two commits.
5. Tag `unifi-core` before tagging any dependent package. Dependency order and no-batching
   rules apply (see tag-push ordering gotcha in project memory).

## Cross-Cutting Gotchas

**Blast radius is total, not partial.** A circular import caused by one forbidden
`from unifi_network_mcp` inside `unifi-mcp-shared` breaks all three app servers, not
just the one referenced. The `ImportError` names the shared package in the traceback,
which misleads debugging toward the symptom rather than the cause.

**Relay drift has no automated safeguard.** Silent drift is the failure mode — both
sides appear healthy until a real client exercises the changed protocol path. Manual
review on every protocol-touching PR is the only protection.

**All five pyproject.toml files, every time.** Forgetting even one creates a workspace
inconsistency that `uv` may not surface immediately but will fail in CI or on a fresh
`uv sync`. Use `grep -r "unifi-core" apps/ packages/unifi-mcp-shared/` to audit
before committing.

**DI parameters document the contract.** When a new shared entrypoint accepts injected
callables, name the parameters descriptively (`get_tools_fn`, `permission_checker`) and
add a docstring. Future contributors reading the shared package won't have the app-server
context that makes the parameter's purpose obvious.

**Backwards-coupling enforcement gotcha.** The import direction must stay strict:
app servers can import from shared, shared can import from core, but never the reverse.
A single `from unifi_network_mcp` in shared breaks all three servers silently at import
time. No test catches this until the import is actually exercised. Always grep for app
imports in `packages/unifi-mcp-shared/` and `packages/unifi-core/` before committing.

**PyPI availability race in CI.** When publishing a new version of `unifi-core` to PyPI,
downstream apps that have already bumped their `pyproject.toml` to the new version pin
may fail in CI before PyPI reflects the new version (5–10 second delay is typical). If
you see CI failures claiming the version doesn't exist on PyPI, fetch the package directly
to confirm availability:
```bash
pip index versions unifi-core | head -5
```
Re-run CI after waiting 30 seconds if the version appears in local pip but not in the
build environment yet.

**Diagnostics direct-import pattern.** When debugging shared-package behavior from an
app server, resist the urge to import diagnostics modules or helper functions directly
from unifi-mcp-shared for inline inspection. Instead, write the diagnostic logic in the
app server's namespace and import the shared module as a black box. Direct imports of
shared internals from diagnostic code count the same as regular imports for cycle-checking
purposes and can accidentally introduce a reverse dependency.
