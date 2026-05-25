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
- **Two implementation surfaces**:
  - Local server: `apps/*/src/*/tool_index.py` (backend handler with FastMCP-registered wrapper) and `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py` (shared handler)
  - Worker cloud: `apps/worker/worker/src/` (the Worker's tool index and MCP handling code)
- **Two-layer architecture**: The discovery system uses a named-param wrapper as the FastMCP-registered function, which delegates to a backend `tool_index_handler` via an assembled `args` dict. Both layers need updating when adding a new parameter.

## Procedure A: Adding or Modifying Parameters on the Tool Discovery Layer

### The FastMCP Named-Param Architecture (Read This First)

FastMCP maps `tools/call` arguments to Python function parameters **by name**. The discovery system uses a two-layer design to exploit this:

**Layer 1 — FastMCP-registered wrapper** (in `tool_index.py`, typically named `_tool_index_wrapper`): Uses explicit named params. FastMCP calls this with `category="clients"` etc.

**Layer 2 — Backend handler** (`tool_index_handler` in each `tool_index.py`): Still receives an assembled `args: dict | None`. The wrapper builds this dict and passes it down.

**Wrong — registering `tool_index_handler` directly with `@tool_decorator` would silently drop all named arguments:**
```python
# If this were registered directly with @tool_decorator, args would always
# be None — no caller sends {\\\"args\\\": {...}}, so FastMCP never populates it.
async def tool_index_handler(args: dict | None = None) -> dict:
    category = args.get(\\\"category\\\") if args else None  # args is always None
    search = args.get(\\\"search\\\") if args else None       # never reached
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
        args[\\\"category\\\"] = category
    if search is not None:
        args[\\\"search\\\"] = search
    if include_schemas:
        args[\\\"include_schemas\\\"] = include_schemas
    return await tool_index_handler(args or None)

# In tool_index.py — the backend:
async def tool_index_handler(args: dict | None = None) -> dict:
    args = args or {}
    return get_tool_index(
        category=args.get(\\\"category\\\"),
        search=args.get(\\\"search\\\"),
        include_schemas=bool(args.get(\\\"include_schemas\\\", False)),
    )
```

This rule applies to every handler in `tool_index.py`: the FastMCP-facing function must use named params.

### Steps

1. Open `apps/*/src/*/tool_index.py` where the wrapper and handler reside.
2. Add the new parameter to the FastMCP-registered wrapper function's signature with a sensible default (preserves backwards compatibility for callers that omit it).
3. In the wrapper, add the new param to the `args` dict it assembles before calling `tool_index_handler`.
4. Open each backend `tool_index_handler` — in each app's `tool_index.py` and the shared `packages/unifi-mcp-shared/src/unifi_mcp_shared/tool_index.py`. In each, add `args.get(\\\"new_param\\\")` and thread it into the `get_tool_index()` call.
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

1. In the same monorepo PR, inspect `apps/worker/worker/src/` for the Worker-side tool discovery and MCP handling path.
2. Locate the Worker's `tool_index` handler or equivalent catalog-shaping code.
3. Add the same parameter with the same signature and default. The same named-param wrapper pattern applies — use explicit named params in the FastMCP-registered function.
4. Implement the same logic. If the Worker delegates to the shared package, ensure the shared package is published first (see Procedure E), then update the Worker's dependency pin.
5. Add or update Worker tests in `apps/worker/worker/test/`, especially contract fixtures shared with the relay when protocol shape changes.
6. Run `make worker-check` or root `make check` before opening the PR.
7. Reference any Worker parity issue in the monorepo PR description so the connection is traceable.

**Coordination order**: shared Python code changes and Worker parity changes land together in the monorepo PR; release order is still upstream Python packages first, then `worker/v*` if the Worker depends on newly released relay behavior.

## Procedure D: Updating SKILL.md Runtime Manifests

`plugins/*/skills/*/SKILL.md` files are **agent-readable invocation manifests**. Agents read these at runtime to learn what parameters a tool accepts. A stale manifest causes agents to call `tool_index` with wrong or missing parameters — treat this with the same urgency as a code bug, not as documentation.

The manifest location varies by runtime environment:

- **Local monorepo development**: `.agents/plugins/*/skills/*/SKILL.md`
- **OpenClaw distributed agent**: `~/.codex-plugin/myco/skills/*/SKILL.md` (OpenClaw globally-unique skill directories)
- **Claude desktop plugin**: `.agents/plugins/*/skills/*/SKILL.md` (mirrored from monorepo)
- **Codespark / other runtimes**: `~/.agents/plugins/*/skills/*/SKILL.md` (XDG-compliant home paths)

When `tool_index` parameters change, all four paths must be synchronized to ensure all runtimes reflect the new behavior.

### Steps

1. After any parameter change to `tool_index`, find all SKILL.md files that reference it across all runtime paths:
   ```bash
   # Local monorepo
   grep -rl \\\"tool_index\\\" .agents/plugins/*/skills/*/SKILL.md

   # OpenClaw
   grep -rl \\\"tool_index\\\" ~/.codex-plugin/myco/skills/*/SKILL.md 2>/dev/null || true

   # XDG home paths
   grep -rl \\\"tool_index\\\" ~/.agents/plugins/*/skills/*/SKILL.md 2>/dev/null || true
   ```
2. For each matching SKILL.md, update the parameter list and invocation examples to match the new handler signature.
3. If a SKILL.md describes the output shape, update that section too if tier behavior changed.
4. Include SKILL.md updates in the **same PR** as the code change — they are runtime artifacts, not documentation that can lag behind.
5. After merge, verify that OpenClaw and XDG-path deploys are triggered (see `bump-plugin-versions.yml`).

In PR #145, 7 SKILL.md files across `plugins/unifi-network/skills/*/`, `plugins/unifi-protect/skills/*/`, and `plugins/unifi-access/skills/*/` were swept as part of the handler change. Missing even one leaves a stranded manifest that will mislead future agents.

## Procedure E: Semver and Release Coordination

Adding optional parameters to the tool discovery layer is a **minor** semver bump — new capability, fully backwards-compatible. Removing a parameter or changing its semantics is a **major** bump.

### Steps

1. Bump `packages/unifi-mcp-shared/pyproject.toml` (minor: `X.Y.Z` → `X.(Y+1).0`).
2. Publish the shared package to PyPI via CI before opening the Worker PR.
3. Update the Worker's dependency pin to the new shared package version.
4. The Worker npm package is published separately via OIDC trusted publishing, triggered by a `worker/v*` tag in this monorepo. Coordinate release order:
   - Publish shared package (PyPI) first
   - Confirm any relay protocol dependency is available, then tag the Worker release so CI publishes to npm

### Plugin Version Sync via `bump-plugin-versions.yml`

The monorepo CI uses `bump-plugin-versions.yml` to synchronize SKILL.md manifests across all four runtime environments (monorepo, OpenClaw, Claude desktop, XDG paths). When `tool_index` parameter or behavior changes:

1. Ensure all SKILL.md files updated in Procedure D include the new parameter documentation.
2. Merge the PR to `main`.
3. The CI job `bump-plugin-versions.yml` automatically:
   - Detects changed SKILL.md files in the merged commit
   - Increments the manifest version field
   - Pushes updates to OpenClaw registry and XDG-path caches
   - Triggers Claude plugin regeneration if needed
4. Monitor the CI job to confirm all manifest types (monorepo, OpenClaw, Claude, XDG) received the update.
5. If a manifest type fails to sync, manually trigger `bump-plugin-versions.yml` with the failed type as input.

This ensures agents across all runtimes see the same tool discovery behavior.

## Cross-Cutting Gotchas

### The `args: dict` Wrapper Trap Is a Silent Failure

If you accidentally register `tool_index_handler` directly with `@tool_decorator` (bypassing the named-param wrapper), there is no warning, no exception, and no test failure. The handler receives `None` for its `args` param and returns unfiltered results as if no parameters were passed. This is the exact problem the two-layer wrapper was introduced to solve. Always verify new or changed discovery params with a live call before merging.

### tools_manifest.json Sync — Keep Python Docstrings Current

After regenerating `tools_manifest.json` from live introspection, the tool descriptions it contains may lag behind actual parameter defaults in the Python source. For example, a parameter's docstring may claim `"Default empty list"` but the actual code default is `None`. When agents read `tools_manifest.json`, they trust the descriptions to match runtime behavior. Stale docstrings in the source lead to stale manifest descriptions and agents make wrong assumptions about optional parameters.

**Prevention**:
1. When adding or changing a parameter default in `tool_index.py`, immediately update the Python docstring to match.
2. After any default change, regenerate `tools_manifest.json` via a local build or CI trigger.
3. Inspect the regenerated manifest for stale descriptions before merging — do not assume docstring changes propagate automatically.

### The Named-Param Rule Is Codebase-Wide

Every handler in `tool_index.py` — and any other FastMCP handler in the project — must use explicit named parameters if callers will pass named arguments. The `args: dict` pattern is only safe for backend functions that are not directly FastMCP-registered. If a handler appears to ignore its parameters, the registration path is the first thing to check.

### MCP Spec Issue #2211 (`max_response_bytes`)

The MCP spec is actively discussing a `max_response_bytes` response-size cap. The two-tier design is already aligned: compact is the default, full is opt-in. When the standard lands, `include_schemas` may become the enforcement mechanism. No breaking change should be needed because the compact tier is already the default behavior.

### One-Unified-Server Architecture

`tool_index` is the canonical tool discovery entry point. If someone proposes adding a second discovery handler in a plugin or subsystem, decline. Fragmentation breaks agents that rely on a single index and makes parity maintenance across local and Worker paths exponentially harder.

### Tool Descriptions vs Pydantic Field Descriptions — Keep the Boundary

Tool descriptions in `@server.tool(description=...)` should describe **what the tool does**, broadly what shape it returns, and how it relates to neighbouring tools. They MUST NOT contain per-field semantic disambiguation. Field-by-field meaning belongs on the Pydantic `Field(description=...)` of the underlying model — which is exactly what the full-schema tier of this discovery system surfaces.

**Wrong** — per-field semantics bloating the tool description:

```python
@server.tool(
    name="unifi_list_clients",
    description=(
        "Returns connected clients with mac, `name` (user-assigned alias "
        "from the UniFi console), `hostname` (DHCP-reported), IP, "
        "`status` (online/offline)… Prefer `name` over `hostname` for "
        "human-readable labels when both are set. …"
    ),
)
```

**Right** — terse tool description + meaning on the Pydantic Field:

```python
# Tool layer (apps/<server>/src/.../tools/clients.py)
@server.tool(
    name="unifi_list_clients",
    description=(
        "Returns connected clients with mac, name, hostname, ip, status "
        "(online/offline), connection type (wired/wireless), and for "
        "wireless clients: ssid, signal_dbm, channel, radio. …"
    ),
)

# Model layer (packages/unifi-core/src/unifi_core/<server>/models/clients.py)
name: Optional[str] = Field(
    default=None,
    description="User-assigned alias set in the UniFi console (preferred for display)",
    json_schema_extra={"mutable": False},
)
hostname: Optional[str] = Field(
    default=None,
    description="DHCP-reported hostname from the device itself",
    json_schema_extra={"mutable": False},
)
```

The compact discovery tier (no schemas) ships the lean tool description. Agents that need field meaning call `unifi_tool_index` with `include_schemas=true` and read the Field descriptions through the surfaced JSON schema. This is the entire point of the two-tier design: protect token budgets by default, opt into depth on demand.

**Why this matters operationally**: every agent that calls `tool_index` without `include_schemas` pays for whatever text is in tool descriptions on every invocation. Per-field documentation in those strings multiplies cost without benefit — the agent that cares about field semantics will request the schema tier anyway.

**Operational nuance that ISN'T a field meaning** (e.g. "merges live /stat/sta with /rest/user snapshot for active clients") *does* belong in the tool description — that information doesn't live on any individual field.
