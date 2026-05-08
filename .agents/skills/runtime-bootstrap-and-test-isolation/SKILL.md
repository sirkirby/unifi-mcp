---
name: myco:runtime-bootstrap-and-test-isolation
description: |-
  Activate this skill when adding a new manager, adding a new tool category,
  writing or debugging tool unit tests, diagnosing tool-visibility failures,
  or investigating startup performance — even if the user doesn't explicitly
  ask about the runtime architecture. Covers four procedural domains: (1) the
  four-stage bootstrap sequence and which layer owns which changes, (2) adding
  a new manager via @lru_cache singleton factories in runtime.py, (3) the
  three-stage decorator replacement system that enables test isolation without
  a live controller, and (4) lazy loading mechanics and tools_manifest.json
  regeneration that controls which tool categories are visible to tool_index.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Runtime Bootstrap, Singleton Management, and Test Isolation

The project uses a four-stage lazy-loading architecture that keeps startup token cost near ~200 tokens (meta-tools only) while making the full ~5000-token tool suite available on demand. Understanding the layer boundaries is essential for knowing where to make changes when adding managers, tool categories, or writing tests. The wrong layer means silent failures — missing singletons, invisible tools, or broken test imports.

## Prerequisites

- Familiarity with the project's `runtime.py`, `main.py`, and `tools/` directory layout
- `make manifest` available (run from repo root; `uv run make manifest` if outside the venv)
- Any new tool category module must be created on disk before regenerating the manifest

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
from functools import lru_cache
from managers.domain_manager import DomainManager

@lru_cache
def get_domain_manager() -> DomainManager:
    return DomainManager(get_connection_manager())   # pass your dependency via its getter
```

3. Add a module-level alias in the **"Shorthand aliases"** section at the bottom of `runtime.py` so tool modules can import the singleton by name:

```python
# runtime.py — shorthand aliases section (bottom of file)
domain_manager = get_domain_manager()
```

Tool modules then import: `from unifi_network_mcp.runtime import domain_manager`

4. Verify singleton identity in a quick test:

```python
from unifi_network_mcp.runtime import get_domain_manager
assert get_domain_manager() is get_domain_manager()
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

**Writing a tool unit test:**

```python
# tests/tools/test_acl.py  (example — tool files are flat: tools/acl.py)
from unifi_network_mcp.tools.acl import some_acl_function   # safe: stage 2 already stripped kwargs

def test_acl_function_returns_expected(mock_manager):
    result = some_acl_function(site_id="default")    # no permission kwargs needed
    assert result["status"] == "ok"
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

## Cross-Cutting Gotchas

**No CI gate for manifest or singleton gaps.** Both the `tools_manifest.json` omission and the missing `@lru_cache` factory are silent failures that pass CI. The manifest produces invisible tools; the missing singleton produces a new instance per call (functional but expensive, and breaks any stateful caching the manager relies on).

**Singleton state leaks between tests.** `@lru_cache` persists across the test session. Add `.cache_clear()` calls to test fixtures for any manager factory that holds mutable state or connection objects.

**Layer confusion is the root cause of most extension mistakes.** Before writing any code for a new manager, tool, or category, consult the change routing table in Procedure A to identify exactly which files need to change — and which ones do not.

**Permission logic belongs in the decorator layer, not in tool functions.** Any branching on `permission_category` inside a tool function is dead code — those kwargs are consumed by the decorator layer before the function body runs.

**DI violation in shared packages** — `unifi-mcp-shared` and `unifi-core` must never import application-level config. All context flows in via `setup_permissioned_tool()`. If you see `from app.settings import ...` inside these packages, that is a regression.

**Missing `confirm` parameter breaks bypass mode.** Every mutating tool must declare `confirm: bool = False`. Bypass injection inspects the function signature; if the param is missing, bypass mode silently fails to inject `confirm=True`.
