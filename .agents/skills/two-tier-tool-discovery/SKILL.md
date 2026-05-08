---
name: myco:two-tier-tool-discovery
description: |-
  Activate this skill whenever you need to extend, maintain, or debug the
  two-tier tool discovery system — even if the user doesn't explicitly ask
  about "tool discovery." This covers: adding or modifying parameters on the
  tool discovery layer in `tool_index.py` (including the critical FastMCP
  named-param wrapper pattern vs. the silent `args: dict` trap), implementing
  or adjusting the compact-vs-full schema tiers (`include_schemas` flag,
  token-count rationale), keeping the Worker cloud path in parity with local
  `tool_index` changes, updating `plugins/*/skills/*/SKILL.md` runtime
  manifests after any parameter or behavior change, and preserving the
  one-unified-server architecture. Also applies to future MCP spec issue #2211
  (`max_response_bytes`) alignment.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Two-Tier Tool Discovery System

The unifi-mcp project implements a meta-tool (`tool_index`) that lets agents and users enumerate available tools at two fidelity levels: a compact default (~38K chars, names and descriptions only) and a full-schema tier (~127K chars, with complete input schemas). Maintaining it requires keeping four artifacts in sync: the local discovery layer, the Worker cloud handler, the `plugins/*/skills/*/SKILL.md` manifests, and the package semver.

## Prerequisites

- **One-unified-server rule**: `tool_index` is a meta-tool that describes other tools. It must remain a single canonical entry point — do not add a second discovery handler in a plugin or subsystem, as this would fragment the index and break agents.
- **Two source repos**:
  - Local server: `apps/*/src/*/tool_index.py` (backend handler with FastMCP-registered wrapper) and `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py` (shared handler)
  - Worker cloud: `~/Repos/unifi-mcp-worker` (the Worker's `tool_index` handler)
- **Two-layer architecture**: The discovery system uses a named-param wrapper as the FastMCP-registered function, which delegates to a backend `tool_index_handler` via an assembled `args` dict. Both layers need updating when adding a new parameter.

## Procedure A: Adding or Modifying Parameters on the Tool Discovery Layer

### The FastMCP Named-Param Architecture (Read This First)

FastMCP maps `tools/call` arguments to Python function parameters **by name**. The discovery system uses a two-layer design to exploit this:

**Layer 1 — FastMCP-registered wrapper** (in `tool_index.py`, typically named `_tool_index_wrapper`): Uses explicit named params. FastMCP calls this with `category="clients"` etc.

**Layer 2 — Backend handler** (`tool_index_handler` in each `tool_index.py`): Still receives an assembled `args: dict | None`. The wrapper builds this dict and passes it down.

**Wrong — registering `tool_index_handler` directly with `@tool_decorator` would silently drop all named arguments:**
```python
# If this were registered directly with @tool_decorator, args would always
# be None — no caller sends {"args": {...}}, so FastMCP never populates it.
async def tool_index_handler(args: dict | None = None) -> dict:
    category = args.get("category") if args else None  # args is always None
    search = args.get("search") if args else None       # never reached
```

**Correct — the actual pattern: a thin named-param wrapper delegates to the backend:**
```python
# In tool_index.py — this is what @tool_decorator registers with FastMCP:
async def _tool_index_wrapper(
    category: str | None = None,
    search: str | None = None,
    include_schemas: bool = False,
) -> dict:
    args = {}
    if category is not None:
        args["category"] = category
    if search is not None:
        args["search"] = search
    if include_schemas:
        args["include_schemas"] = include_schemas
    return await tool_index_handler(args or None)

# In tool_index.py — the backend:
async def tool_index_handler(args: dict | None = None) -> dict:
    args = args or {}
    return get_tool_index(
        category=args.get("category"),
        search=args.get("search"),
        include_schemas=bool(args.get("include_schemas", False)),
    )
```

This rule applies to every handler in `tool_index.py`: the FastMCP-facing function must use named params.

### Steps

1. Open `apps/*/src/*/tool_index.py` where the wrapper and handler reside.
2. Add the new parameter to the FastMCP-registered wrapper function's signature with a sensible default (preserves backwards compatibility for callers that omit it).
3. In the wrapper, add the new param to the `args` dict it assembles before calling `tool_index_handler`.
4. Open each backend `tool_index_handler` — in each app's `tool_index.py` and the shared `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py`. In each, add `args.get("new_param")` and thread it into the `get_tool_index()` call.
5. In `get_tool_index()` (shared `tool_index.py`), implement the actual filtering/shaping logic.
6. Update the `register_tool()` call's `input_schema` in the app's `tool_index.py` to document the new parameter for schema-aware callers.
7. Start the local server and call `tool_index` with and without the new parameter to confirm correct behavior in both modes.
8. Bump the shared package version (minor bump — see Procedure E).

## Procedure B: Implementing the Two-Tier Schema Design

The two tiers exist to manage token budgets across different agent tasks.

| Tier | Invocation | Approximate size | Contents |
|------|-----------|-----------------|----------|
| Compact (default) | Omit `include_schemas` or pass `false` | ~38K chars | Tool names + descriptions only |
| Full | `include_schemas: true` | ~127K chars | Names + descriptions + full input schemas |

### Design Rationale

Agents performing tool discovery in a fresh context cannot afford 127K chars on every call. The compact default lets them enumerate categories and identify the right tool. The full tier is for when they need to invoke a tool and require the exact parameter schema. This design is intentionally backwards-compatible: callers that predate `include_schemas` receive compact output automatically.

### Steps

1. In the FastMCP-registered wrapper function in `tool_index.py`, accept `include_schemas: bool = False` as a named param and include it in the assembled `args` dict.
2. In `get_tool_index()` (`packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py`), when building each tool entry in the response:
   - Always include `name` and `description`
   - Include `inputSchema` (or equivalent) only when `include_schemas is True`
3. Keep the compact response shape consistent with the full response — same keys present, schema fields simply absent. Agents should be able to parse both tiers with the same code path.
4. Document the approximate size of each tier in a comment near `get_tool_index()`. Future maintainers need to understand why the flag exists.
5. Add or update tests asserting:
   - Default call omits schema fields
   - `include_schemas=True` includes schema fields
   - Both responses contain all tool names

## Procedure C: Worker Cloud Parity Maintenance

Every parameter added to the local tool discovery layer must be mirrored in the Worker cloud handler. This is a **standing maintenance obligation** — not optional. A stale Worker silently ignores new parameters and returns wrong results with no error.

### Steps

1. After the local PR is merged, open `~/Repos/unifi-mcp-worker`.
2. Locate the Worker's `tool_index` handler (the file analogous to the app's `tool_index.py`).
3. Add the same parameter with the same signature and default. The same named-param wrapper pattern applies — use explicit named params in the FastMCP-registered function.
4. Implement the same logic. If the Worker delegates to the shared package, ensure the shared package is published first (see Procedure E), then update the Worker's dependency pin.
5. Open a PR to the Worker repo. In the PR description, reference the local PR so the connection is traceable.
6. Close any open Worker issues that tracked the parity gap.
7. Merge the Worker PR after the local PR is live.

**Coordination order**: local merge → shared package publish → Worker dependency update → Worker PR → Worker merge.

## Procedure D: Updating SKILL.md Runtime Manifests

`plugins/*/skills/*/SKILL.md` files are **agent-readable invocation manifests**. Agents read these at runtime to learn what parameters a tool accepts. A stale manifest causes agents to call `tool_index` with wrong or missing parameters — treat this with the same urgency as a code bug, not as documentation.

### Steps

1. After any parameter change to `tool_index`, find all SKILL.md files that reference it:
   ```bash
   grep -rl "tool_index" plugins/*/skills/*/SKILL.md
   ```
2. For each matching SKILL.md, update the parameter list and invocation examples to match the new handler signature.
3. If a SKILL.md describes the output shape, update that section too if tier behavior changed.
4. Include SKILL.md updates in the **same PR** as the code change — they are runtime artifacts, not documentation that can lag behind.

In PR #145, 7 SKILL.md files across `plugins/unifi-network/skills/*/`, `plugins/unifi-protect/skills/*/`, and `plugins/unifi-access/skills/*/` were swept as part of the handler change. Missing even one leaves a stranded manifest that will mislead future agents.

## Procedure E: Semver and Release Coordination

Adding optional parameters to the tool discovery layer is a **minor** semver bump — new capability, fully backwards-compatible. Removing a parameter or changing its semantics is a **major** bump.

### Steps

1. Bump `packages/unifi-mcp-shared/pyproject.toml` (minor: `X.Y.Z` → `X.(Y+1).0`).
2. Publish the shared package to PyPI via CI before opening the Worker PR.
3. Update the Worker's dependency pin to the new shared package version.
4. The Worker npm package is published separately via OIDC trusted publishing, triggered by a version tag on the Worker repo. Coordinate release order:
   - Publish shared package (PyPI) first
   - Update Worker dependency, tag the Worker release, CI publishes to npm

## Cross-Cutting Gotchas

### The `args: dict` Wrapper Trap Is a Silent Failure
If you accidentally register `tool_index_handler` directly with `@tool_decorator` (bypassing the named-param wrapper), there is no warning, no exception, and no test failure. The handler receives `None` for its `args` param and returns unfiltered results as if no parameters were passed. This is the exact problem the two-layer wrapper was introduced to solve. Always verify new or changed discovery params with a live call before merging.

### The Named-Param Rule Is Codebase-Wide
Every handler in `tool_index.py` — and any other FastMCP handler in the project — must use explicit named parameters if callers will pass named arguments. The `args: dict` pattern is only safe for backend functions that are not directly FastMCP-registered. If a handler appears to ignore its parameters, the registration path is the first thing to check.

### MCP Spec Issue #2211 (`max_response_bytes`)
The MCP spec is actively discussing a `max_response_bytes` response-size cap. The two-tier design is already aligned: compact is the default, full is opt-in. When the standard lands, `include_schemas` may become the enforcement mechanism. No breaking change should be needed because the compact tier is already the default behavior.

### One-Unified-Server Architecture
`tool_index` is the canonical tool discovery entry point. If someone proposes adding a second discovery handler in a plugin or subsystem, decline. Fragmentation breaks agents that rely on a single index and makes parity maintenance across local and Worker paths exponentially harder.
