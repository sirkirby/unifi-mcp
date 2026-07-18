---
name: myco:runtime-bootstrap-and-test-isolation
description: |-
  Activate this skill when adding a new manager, adding a new tool category,
  writing or debugging tool unit tests, diagnosing tool-visibility failures,
  investigating startup performance, or extending/maintaining/debugging the
  two-tier tool discovery system (`tool_index`) — even if the user doesn't
  explicitly ask about the runtime architecture or "tool discovery." Covers:
  (1) the four-stage bootstrap sequence and which layer owns which changes,
  (2) adding a new manager via @lru_cache singleton factories in runtime.py,
  (3) the three-stage decorator replacement system that enables test isolation
  without a live controller, (4) lazy loading mechanics and
  tools_manifest.json regeneration that controls which tool categories are
  visible, (5) the permission model's two safety axes, and (6) the two-tier
  tool_index discovery layer: the FastMCP named-param wrapper vs. the silent
  `args: dict` trap, compact-vs-full schema tiers (`include_schemas`), Worker
  cloud parity, and SKILL.md runtime manifest sync.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Runtime Bootstrap, Singleton Management, Test Isolation, and Tool Discovery

The project uses a four-stage lazy-loading architecture that keeps startup token cost near ~200 tokens (meta-tools only) while making the full ~5000-token tool suite available on demand. Understanding the layer boundaries is essential for knowing where to make changes when adding managers, tool categories, or writing tests. The wrong layer means silent failures — missing singletons, invisible tools, or broken test imports. The `tool_index` meta-tool (Procedure F) is the discovery layer that surfaces those lazily-loaded tools to agents.

## Prerequisites

- Familiarity with the project's `runtime.py`, `main.py`, and `tools/` directory layout. Each app has its own copy under `apps/{app}/src/{package}/` (e.g., `apps/network/src/unifi_network_mcp/runtime.py`).
- `make manifest` available (run from repo root; `uv run make manifest` if outside the venv)
- Any new tool category module must be created on disk before regenerating the manifest
- For Procedure F (tool discovery): two implementation surfaces exist — local server (per-app handler, e.g. `apps/access/src/unifi_access_mcp/tool_index.py`, plus the shared `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py`) and Worker cloud (`apps/worker/worker/src/`). Both must move together.

## Procedure A: Understanding the Bootstrap Sequence and Layer Ownership

Bootstrap follows four stages in strict order:

```
main.py
  └─► runtime.py          # decorator wiring + @lru_cache singleton factories
        └─► tools/ (lazy) # loaded on first meta-tool execute() call
              └─► managers/ # domain logic only; no MCP awareness
```

**Layer responsibilities:**

| Layer | Owns | Does NOT own |
|---|---|---|
| `main.py` | Live permission enforcement (stage 3 decorator via `setup_permissioned_tool`) | Business logic, tool registration |
| `runtime.py` | Decorator pipeline, singleton manager factories | Domain logic |
| `tools/` (lazy) | Tool definitions, MCP registration | Singletons, permissions |
| `managers/` | Domain logic, API calls | MCP adapter, decorators |

**Change routing — use this table before writing any code:**

| What you're adding | Where the change goes |
|---|---|
| New manager (shared service) | `runtime.py` — new `@lru_cache` factory + module-level alias |
| New tool within an existing category | `tools/<category>.py` only — no `runtime.py` changes |
| New tool category | `tools/<category>.py` + `make manifest` to update `tools_manifest.json` |
| Permission logic change | `main.py` via `setup_permissioned_tool` arguments |

Routing to the wrong layer is the most common mistake. A new tool module does not need a `runtime.py` singleton; a new manager does and nothing will remind you if you skip it.

## Procedure B: Adding a New Manager via @lru_cache Singleton Pattern

Every shared service (network client, cache, connection pool) is managed as an `@lru_cache` singleton in `runtime.py`. This is an informal contract — no CI gate enforces it.

**When you need this:** whenever you create a new `managers/<domain>_manager.py` that must be shared across tool calls.

**Steps:**

1. Create `managers/<domain>_manager.py` with your domain logic class.

2. Open `runtime.py` and add a factory function decorated with `@lru_cache`. Use a **public** name (no leading underscore) — all existing factories follow this convention:

```python
# Real pattern, from apps/access/src/unifi_access_mcp/runtime.py
from functools import lru_cache
from managers.door_manager import DoorManager

@lru_cache
def get_door_manager() -> DoorManager:
    return DoorManager(get_connection_manager())   # pass your dependency via its getter
```

3. Add a module-level alias in the **"Shorthand aliases"** section at the bottom of `runtime.py` so tool modules can import the singleton by name (e.g. `traffic_flow_manager = get_traffic_flow_manager()` in `apps/network/src/unifi_network_mcp/runtime.py`):

```python
# runtime.py — shorthand aliases section (bottom of file)
door_manager = get_door_manager()
```

Tool modules then import: `from unifi_access_mcp.runtime import door_manager`

4. Verify singleton identity in a quick test:

```python
from unifi_access_mcp.runtime import get_door_manager
assert get_door_manager() is get_door_manager()
```

**Adding a tool vs. adding a manager:**
Adding a new tool file inside an existing category requires **zero** `runtime.py` changes. Only new *managers* (shared services) need the factory pattern. Conflating the two causes either missing singletons or unnecessary `runtime.py` churn.

**`@lru_cache` and mutable state in tests:**
`@lru_cache` persists across the entire test session. If your manager holds mutable state or connection objects, call `get_domain_manager.cache_clear()` in test teardown to prevent cross-test contamination.

## Procedure C: Three-Stage Decorator Replacement and Test Isolation

Tool functions go through three decorator replacements during bootstrap and permission wiring. This is what makes the entire test suite work without a live UniFi controller and enables the full permission/confirmation flow.

**The three stages:**

| Stage | Where | What it installs | Effect |
|---|---|---|---|
| 1 | `runtime.py` — `get_server()` | `create_mcp_tool_adapter(server.tool)` stored as `server._original_tool` | Registers tool with the MCP server |
| 2 | `runtime.py` — `get_server()` | `_create_permissioned_tool_wrapper(server._original_tool)` replaces `server.tool` | **Strips `permission_category`/`permission_action` kwargs from the call signature** |
| 3 | `main.py` | `setup_permissioned_tool(server=server, ...)` | Checks real permissions at call time and routes to preview/execute state machine |

**Why stage 2 is the key to test isolation:**

Tool functions declare `permission_category` and `permission_action` as kwargs so the live enforcement decorator (stage 3) can inspect them. By the time stage 2 completes, those kwargs have been consumed and stripped from the visible signature. This means:

- Any tool module can be imported directly in a test — the kwarg mismatch that would cause a `TypeError` at call time is already gone
- Tests do **not** need a live controller or a mock permission system
- Stage 3 enforcement (in `main.py`) is never reached in tests, so it can be safely absent

**The permission/confirmation flow (Stage 3 in `main.py`):**

Stage 3 installs the full permission enforcement chain via `setup_permissioned_tool()`:

```python
from unifi_mcp_shared.permissioned_tool import setup_permissioned_tool

setup_permissioned_tool(
    server=server,
    category_map=category_map,           # maps tool category to permission category
    server_prefix=server_prefix,         # used for env var resolution
    register_tool_fn=register_tool,      # callback to add tool to tool_index
    diagnostics_enabled_fn=lambda: diag, # callable returning bool
    wrap_tool_fn=wrap_with_diagnostics,  # diagnostics wrapper
    logger=logger,
)
```

After this call, the permission system is fully operational: callers will see preview/execute state machine (confirm mode) or immediate execution (bypass mode), and policy gates block entire tool categories.

**Writing a tool unit test (real example from `apps/network/tests/unit/test_outlet_control.py`):**

```python
# tests/unit/test_outlet_control.py
from unifi_network_mcp.tools.devices import set_outlet_state  # safe: stage 2 already stripped kwargs

@pytest.mark.asyncio
async def test_set_outlet_state_...(...):
    # patches the manager method directly on the class so interception
    # works regardless of singleton vs mock instance resolution
    ...
```

**Do not** pass `permission_category` or `permission_action` at test call sites — those kwargs are already gone after stage 2 and passing them will raise `TypeError: unexpected keyword argument`.

**If you see `TypeError: unexpected keyword argument 'permission_category'` in a test:**
The import is happening before stage 2 completes — typically because you're importing a module that bypasses the bootstrap path. Import from the fully bootstrapped module path, not directly from an undecorated source file.

**Important rule: permission logic belongs in the decorator layer, not in tool functions.** Never put branching on `permission_category` inside a tool function body — those kwargs are consumed by the decorator layer before the function is called. Any such code is dead and will never execute.

**`test_tool_map_sync.py` path constraint:**
`apps/network/tests/unit/test_tool_map_sync.py` uses a hardcoded relative path (`Path("apps/network/src/unifi_network_mcp/tools_manifest.json")`) and must be run from the **repository root**. Running pytest from a subdirectory causes it to silently pass with zero real coverage:

```bash
# Always run from repo root:
pytest apps/network/tests/unit/test_tool_map_sync.py
```

## Procedure D: Lazy Loading, tools_manifest.json, and the Startup Token Budget

Domain tools are not registered at startup. Only meta-tools register during bootstrap, keeping startup cost at roughly **~200 tokens**. If all domain tools loaded eagerly the cost would be ~5000 tokens — a 25× difference that matters for latency and cold-start performance.

**How lazy loading works:**
- `categories.py` builds `TOOL_MODULE_MAP` from `tools_manifest.json` at module load time
- `setup_lazy_loading` installs a loader that imports the relevant `tools/<category>.py` module on demand when that tool is first called
- Subsequent calls to the same category are already cached by Python's module system

**`tools_manifest.json` — the visibility gate:**

`tool_index` uses `tools_manifest.json` to enumerate which categories exist. A category not listed in the manifest is **completely invisible** at runtime — no error, no warning, silent omission.

**When to regenerate the manifest:**
- After adding a new tool category file under `tools/`
- After renaming or removing a category

**How to regenerate:**

```bash
# From repo root:
make manifest
```

Commit the updated `tools_manifest.json` alongside the new category code. A PR that adds a tool category without updating the manifest merges cleanly and breaks tool discovery silently in production — there is no CI gate that catches this.

**Diagnosing silent tool invisibility:**

If a newly added tool is absent from `tool_index` output, work through this checklist:

1. Confirm the category file exists under `tools/` (e.g., `tools/domain.py`)
2. Open `tools_manifest.json` — is the category listed? If not, run `make manifest` and commit the result
3. Confirm the tool function is exported from the category module
4. Restart the MCP server — lazy loading caches on first import; stale processes won't see new code

**Startup vs. on-demand load — what counts as "startup":**
The ~200-token budget covers only the meta-tool registrations. Any performance investigation that measures "startup cost" must distinguish between meta-tool registration (always eager) and domain tool load (deferred until first use). A category that gets called on every request is effectively eager; a niche category stays cheap.

## Procedure E: Permission Model and Two-Axis Safety

The permission system has exactly two independent axes controlling mutating tools (create/update/delete). Conflating them causes architectural errors and incorrect PR review feedback.

**Axis 1 — Permission mode (caller-controlled, runtime)**

The caller invokes a mutating tool with either:

- `confirm` (default): the tool enters preview mode on first call; the caller must re-invoke with `confirm=True` to execute the mutation.
- `bypass`: skip the preview step and execute immediately. Only permitted when the admin has granted bypass for this tool category in the server config.

This axis is dynamic — the same tool behaves differently depending on what the caller passes. It is NOT a configuration-time setting.

**Axis 2 — Policy gates (admin-controlled, config-time)**

Each tool category has a policy gate that is either enabled or disabled by the administrator in the server configuration. A disabled gate blocks execution for all callers regardless of `permission_mode`.

Key invariant: **tools are always registered and visible regardless of policy gates.** The gate blocks at *execution time*, not at *registration time*. Never assume a tool appearing in the MCP tool list is unrestricted — it may be gated off.

| Axis | Controls | Configured via | Trigger behavior |
|---|---|---|---|
| **Permission mode** | Workflow (preview vs. immediate execute) | `UNIFI_TOOL_PERMISSION_MODE` / `UNIFI_<SERVER>_TOOL_PERMISSION_MODE` env var | `"confirm"` → two-stage; `"bypass"` → inject `confirm=True` |
| **Policy gates** | Hard on/off per tool | `PolicyGateChecker` / `category_map` config | Blocked tools return `{"success": False, "error": "..."}` on **any** call |

**Key rules:**

1. **Tools are always visible** — policy gates never hide a tool from the tool list. They block at call time.
2. **Gates fire on every call** — the policy gate check runs at the top of the `gated_func` wrapper, before any `confirm` branching.
3. **Mode and gates are independent** — `permission_mode=bypass` does not override a policy gate.

## Procedure F: Two-Tier Tool Discovery System (`tool_index`)

`tool_index` is the meta-tool that enumerates the tools lazy-loaded in Procedure D. It exposes two fidelity tiers — compact (~38K chars, names+descriptions) and full (~127K chars, `include_schemas=true`, adds input schemas) — and has two implementation surfaces (local server + Worker cloud) that must be kept in parity.

**One-unified-server rule:** `tool_index` must remain the single canonical discovery entry point. Do not add a second discovery handler in a plugin or subsystem — it fragments the index and breaks agents.

**The FastMCP named-param wrapper pattern (critical):** FastMCP maps `tools/call` arguments to Python function parameters **by name**. A handler registered directly with `@tool_decorator` that takes `args: dict | None` will silently always receive `None` — no caller sends `{"args": {...}}`. The fix is a two-layer design. Layer 1, the FastMCP-registered wrapper, lives in the shared `packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py` (`_tool_index_wrapper`, built per-server via a factory that closes over each app's handler); Layer 2, the backend `tool_index_handler`, lives in each app's per-app discovery module (e.g. `apps/access/src/unifi_access_mcp/tool_index.py`) plus the shared `get_tool_index()` implementation in `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py`:

```python
# Layer 1 — packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py (named params):
async def _tool_index_wrapper(
    category: str | None = None,
    search: str | None = None,
    include_schemas: bool = False,
) -> dict:
    args = {}
    if category is not None: args["category"] = category
    if search is not None: args["search"] = search
    if include_schemas: args["include_schemas"] = include_schemas
    return await tool_index_handler(args or None)

# Layer 2 — e.g. apps/access/src/unifi_access_mcp/tool_index.py (still takes assembled args dict):
async def tool_index_handler(args=None) -> dict:
    args = args or {}
    return get_tool_index(
        category=args.get("category"),
        search=args.get("search"),
        include_schemas=bool(args.get("include_schemas", False)),
    )
```

This rule applies to every FastMCP-registered handler in the project, not just `tool_index`.

**Adding/modifying a parameter — steps:**

1. Add the param to `_tool_index_wrapper` in `packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py` with a backwards-compatible default.
2. Thread it into the `args` dict the wrapper assembles.
3. Update each backend `tool_index_handler` (per-app, e.g. `apps/network/src/unifi_network_mcp/tool_index.py`, `apps/protect/src/unifi_protect_mcp/tool_index.py`, `apps/access/src/unifi_access_mcp/tool_index.py`) to read it and pass it to `get_tool_index()`.
4. Implement the actual filtering/shaping logic in `get_tool_index()` in `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py`.
5. Update the `register_tool()` call's `input_schema` to document the new parameter.
6. **Mirror the change in the Worker cloud path** (`apps/worker/worker/src/`) in the same PR — a stale Worker silently ignores new parameters with no error. Add/update Worker tests in `apps/worker/worker/test/`; run `make worker-check` or root `make check`.
7. Update every `plugins/*/skills/*/SKILL.md` runtime manifest that documents `tool_index` params — across all four runtime paths: local monorepo (`.agents/plugins/*/skills/*/SKILL.md`), OpenClaw (`~/.codex-plugin/myco/skills/*/SKILL.md`), Claude desktop (mirrored `.agents/plugins/*/skills/*/SKILL.md`), and XDG runtimes (`~/.agents/plugins/*/skills/*/SKILL.md`). These are agent-readable runtime artifacts, not lagging documentation — update in the same PR. `grep -rl "tool_index" .agents/plugins/*/skills/*/SKILL.md` to find them.
8. Bump `packages/unifi-mcp-shared/pyproject.toml` (minor bump for new optional param; major for removal/semantic change). Publish to PyPI before opening the Worker PR, then update the Worker's dependency pin and tag `worker/v*` for npm publish via OIDC.
9. After merge, the CI workflow `.github/workflows/bump-plugin-versions.yml` auto-syncs SKILL.md manifests across all four runtime environments — monitor it; manually re-trigger with the failed type if one doesn't sync.
10. Start the local server and call `tool_index` with and without the new parameter to confirm both tiers behave correctly before merging.

**Two-tier response shape:** always include `name`/`description`; include `inputSchema` only when `include_schemas is True`. Keep the same keys present in both tiers so callers can use one parsing path.

## Cross-Cutting Gotchas

**No CI gate for manifest or singleton gaps.** Both the `tools_manifest.json` omission and the missing `@lru_cache` factory are silent failures that pass CI. The manifest produces invisible tools; the missing singleton produces a new instance per call (functional but expensive, and breaks any stateful caching the manager relies on).

**Singleton state leaks between tests.** `@lru_cache` persists across the test session. Add `.cache_clear()` calls to test fixtures for any manager factory that holds mutable state or connection objects.

**Layer confusion is the root cause of most extension mistakes.** Before writing any code for a new manager, tool, or category, consult the change routing table in Procedure A to identify exactly which files need to change — and which ones do not.

**Permission logic belongs in the decorator layer, not in tool functions.** Any branching on `permission_category` inside a tool function is dead code — those kwargs are consumed by the decorator layer before the function body runs.

**DI violation in shared packages** — `unifi-mcp-shared` and `unifi-core` must never import application-level config. All context flows in via `setup_permissioned_tool()`. If you see `from app.settings import ...` inside these packages, that is a regression.

**Missing `confirm` parameter breaks bypass mode.** Every mutating tool must declare `confirm: bool = False`. Bypass injection inspects the function signature; if the param is missing, bypass mode silently fails to inject `confirm=True`.

**Worktree `uv sync --all-packages` requirement.** New git worktrees do not inherit the monorepo's installed package set. Before running focused pytest in a new worktree, run `uv sync --all-packages` from the worktree root; otherwise cross-package imports (`from unifi_core...`, `from unifi_mcp_shared...`) fail with `ModuleNotFoundError`. Note: `uv sync` (without `--all-packages`) installs only the current package and will not install workspace siblings.

**The `args: dict` wrapper trap is a silent failure (tool_index).** Registering `tool_index_handler` directly with `@tool_decorator` (bypassing the named-param wrapper) produces no warning, no exception, no test failure — the handler just always receives `None` and returns unfiltered results. Always verify new/changed discovery params with a live call before merging.

**`tools_manifest.json` can drift from Python docstrings.** After regenerating the manifest from live introspection, tool descriptions may lag actual parameter defaults in source (e.g., docstring says "default empty list" but code default is `None`). Update the docstring immediately when changing a default, regenerate the manifest, and inspect it for staleness before merging — this does not happen automatically.

**Full-schema tier inference can drop Pydantic validation keywords.** The `include_schemas=true` tier builds `inputSchema` via a shared `_infer_input_schema` helper that independently derives a JSON schema from the tool's Python signature — this can silently diverge from and drop constraints that FastMCP's own internal schema derivation retains. When adding a parameter with Pydantic `Field` constraints, verify the full-schema tier output actually includes them; don't assume `_infer_input_schema` mirrors FastMCP's derivation.

**MCP `max_response_bytes` cap alignment.** The two-tier design (compact default, full opt-in) is already aligned with the MCP spec's discussed response-size cap; `include_schemas` may become the enforcement mechanism when the standard lands. No breaking change expected.

**Tool descriptions vs. Pydantic Field descriptions — keep the boundary.** `@server.tool(description=...)` text should describe what the tool does and how it relates to neighboring tools — never per-field semantic disambiguation. Field-by-field meaning belongs on the Pydantic `Field(description=...)`, surfaced via the full-schema tier. Every agent calling `tool_index` without `include_schemas` pays for whatever text is in tool descriptions on every call; per-field documentation there multiplies cost without benefit. Operational nuance that isn't a field meaning (e.g. "merges live /stat/sta with /rest/user snapshot") still belongs in the tool description.
