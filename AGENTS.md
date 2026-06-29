# Project Rules

## Non-Goals

This project is **not**:

- a general-purpose network management framework
- a UniFi controller replacement or admin dashboard
- a real-time monitoring or alerting service
- a CI/CD pipeline runner or deployment tool
- a web application with a frontend UI (dev consoles are debugging REPLs only)
- a database or persistent storage layer (all state lives on UniFi controllers)

## Architecture Rules

### Layering

- Tool functions MUST NOT contain business logic beyond argument validation and response formatting
- Tool functions MUST delegate to manager methods for all controller interactions
- Manager methods MUST NOT import from `<app>.tools` (no circular dependencies)
- All controller communication MUST flow through `ConnectionManager`
- Tool modules MUST import singletons from `<app>.runtime`, never instantiate directly
- Shared packages MUST NOT import from app packages (dependency flows downward only)
- App packages MUST NOT import from each other (no cross-app dependencies)

### Singletons

- All shared objects (server, config, managers) MUST be created via `@lru_cache` factories in `<app>/runtime.py`
- Tests MUST monkey-patch the factory or alias before importing tool modules
- There MUST be exactly one `ConnectionManager` instance per server process

### Tool Response Contract

All tools MUST return `Dict[str, Any]`:

```python
{"success": True, "data": <result>}                                    # Success
{"success": False, "error": "<specific, actionable message>"}          # Error
{"success": True, "requires_confirmation": True, "preview": <payload>} # Mutation preview
```

- Exceptions MUST NOT escape tool functions. Catch, log with `exc_info=True`, return error dict.
- Error messages MUST include the operation that failed (e.g., `"Failed to list devices: ..."` not just `str(e)`).
- Raw tracebacks MUST NOT be exposed to MCP clients.

### Confirmation System

All state-changing tools MUST implement preview-then-confirm:
- `confirm=False` (default): validate input, return preview payload
- `confirm=True`: execute the mutation on the controller
- Bypass mode injects `confirm=True` automatically
- **Anchor:** `packages/unifi-mcp-shared/src/unifi_mcp_shared/confirmation.py`

### MCP Tool Annotations

All tools MUST include `annotations=ToolAnnotations(...)` in `@server.tool()`:
- Read-only: `readOnlyHint=True, openWorldHint=False`
- Mutating: `readOnlyHint=False, destructiveHint=<bool>, idempotentHint=<bool>, openWorldHint=False`
- `destructiveHint=True` for delete, block, reboot, revoke operations
- `idempotentHint=True` for update/rename (same args = same result)
- All tools: `openWorldHint=False` (closed UniFi controller domain)

### Async

- All I/O-bound operations MUST use `async`/`await`
- No synchronous blocking calls in tool implementations or managers
- `asyncio.run()` MUST NOT be called from within an async context

### Logging

- All log output MUST go to stderr (stdout is reserved for JSON-RPC in stdio mode)
- Use `%s` format strings in logger calls, not f-strings, for lazy evaluation
- Configuration errors SHOULD fail fast at startup with clear guidance

### Hard Bans

- Hardcoding host, port, credentials, or feature flags in Python source is **banned** — use `config.yaml` with `${oc.env:VAR,default}` or `UNIFI_`-prefixed env vars
- Permission category strings MUST be defined in `<app>/categories.py` (`NETWORK_CATEGORY_MAP`, etc.)
- Tool-to-module mappings MUST be in `TOOL_MODULE_MAP` in `<app>/categories.py`
- Validation models MUST be pydantic BaseModel classes in `packages/unifi-core/src/unifi_core/<server>/models/<domain>.py` — never inline JSON schema dicts in tool functions or app-local schemas modules
- No monkey-patches in production code
- **Anchor:** `apps/network/src/unifi_network_mcp/config/config.yaml`

### API Surface Boundaries

UniFi exposes three API surfaces with disjoint ID/auth models: the V2 controller API (session cookie auth, Mongo ObjectIDs, `snake_case` fields), the public Integration API (`X-API-Key` auth, UUIDs, `camelCase` fields), and the UniFi-OS **Alarm Manager v2** service (`/api/v2/alarms/`, session + **SuperAdmin** auth, UUIDs, `snake_case` fields). They are **not interchangeable**.

- **Tool families share an ID space.** Tools whose returned IDs and accepted IDs are mutually portable form a *family*. Cross-family ID use is prohibited.
- **Tool descriptions MUST scope IDs** when they could be confused with another family's IDs. Standard formula: *"These IDs are scoped to the <family> tool family — do not pass them to other <resource> tools."* This applies to MCP tool descriptions, GraphQL type/query descriptions, and REST route descriptions alike.
- **Integration API tools MUST require an API key** and fail with a clear remediation message when it is missing. The auth check belongs in the manager so every tool in the family inherits it.
- **Alarm Manager v2 (`/api/v2/alarms/`) requires a SuperAdmin credential.** Reach it via `uiprotect`'s `api_request(..., api_path="/api/v2/alarms/")` (no bespoke client). A Protect-scoped account returns 403 — managers MUST map this to an actionable "requires SuperAdmin" error so callers/agents self-diagnose. Blast radius is topology-dependent: broad on a combined UDM console, contained to Protect on a standalone UNVR.
- **Silent cross-API ID translation is banned** unless the mapping is 1:1, stable, and verified against live data. Zones are grandfathered (1:1 by name, stable, unique). Policies are not (membership diverges, no bridge field, V2 has duplicate names).
- **Bridging tools must be explicit.** If you need to cross ID namespaces, write a named bridging tool (`unifi_resolve_<resource>_id_for_<family>`) with documented failure modes. Never bury the bridge inside another tool.

**Enforcement:** family scoping is currently *guidance* — descriptions + this rule. There is no runtime or type-level check. Cross-family ID misuse fails at the controller (e.g., 400 from the integration API) and surfaces as a tool error. Stronger enforcement (typed IDs, runtime regex checks, manifest family field) is on the table if and when the integration-API surface grows beyond the current single family.

**Reference family (Integration API):** `unifi_get_firewall_policy_ordering` + `unifi_reorder_firewall_policies` in `apps/network/src/unifi_network_mcp/tools/firewall.py`.

**Skill:** `add-integration-api-tool` (full procedure for contributors).

## Permission System

Two concepts:

**Permission Mode** — controls mutation handling:
- `confirm` (default): mutations require preview-then-confirm
- `bypass`: mutations execute without confirmation
- Read-only tools are always allowed

Env var precedence (most specific wins): `UNIFI_<SERVER>_TOOL_PERMISSION_MODE` > `UNIFI_TOOL_PERMISSION_MODE`

**Policy Gates** — hard boundaries that disable actions:

Three-level hierarchy (most specific wins): `UNIFI_POLICY_<SERVER>_<CATEGORY>_<ACTION>` > `UNIFI_POLICY_<SERVER>_<ACTION>` > `UNIFI_POLICY_<ACTION>`

Actions: `CREATE`, `UPDATE`, `DELETE`. Unset = allowed.

All tools MUST remain visible and discoverable regardless of policy gates. Authorization is checked at call time by the `permissioned_tool` decorator.

- **Anchor:** `packages/unifi-mcp-shared/src/unifi_mcp_shared/policy_gate.py`

## Golden Paths

All changes MUST follow a golden path. If no path applies, ask before inventing a new pattern.

### Add a new tool to an existing category

1. Add manager method in `apps/<server>/src/<pkg>/managers/<domain>_manager.py`
   - **Anchor (read-only):** `apps/network/src/unifi_network_mcp/managers/client_manager.py`
   - **Anchor (mutating):** `apps/network/src/unifi_network_mcp/managers/firewall_manager.py`
2. Add tool function in `apps/<server>/src/<pkg>/tools/<category>.py`
   - **Anchor (read-only):** `apps/network/src/unifi_network_mcp/tools/clients.py:lookup_by_ip`
   - **Anchor (mutating):** `apps/network/src/unifi_network_mcp/tools/firewall.py:create_firewall_policy`
3. Add tool name to `TOOL_MODULE_MAP` in `<pkg>/categories.py`
4. Run `make manifest`
5. Add tests in `apps/<server>/tests/unit/test_<category>.py`
6. Add `ToolAnnotations` to the `@server.tool()` decorator
7. Commit code + manifest + tests together

### Add a new tool category

1. Create manager: `apps/<server>/src/<pkg>/managers/<domain>_manager.py`
   - **Anchor:** `apps/network/src/unifi_network_mcp/managers/routing_manager.py`
2. Add `@lru_cache` factory + alias in `<pkg>/runtime.py`
3. Create tool module: `apps/<server>/src/<pkg>/tools/<category>.py`
   - **Anchor:** `apps/network/src/unifi_network_mcp/tools/clients.py`
4. Add tool names to `TOOL_MODULE_MAP` in `<pkg>/categories.py`
5. Add category to the server's `CATEGORY_MAP` in `<pkg>/categories.py`
6. Run `make manifest`
7. Add tests, update docs and README as needed
8. Commit everything together

### Add a configuration value

1. Add default to `apps/<server>/src/<pkg>/config/config.yaml` with `${oc.env:VAR,default}` syntax
   - **Anchor:** `apps/network/src/unifi_network_mcp/config/config.yaml`
2. Add env var to `.env.example` with a comment
3. Document in README.md configuration section

### Add or modify an update tool

Update tools MUST use the fetch-merge-put pattern. The manager fetches current state, merges the caller's partial updates, and PUTs the full object. The tool layer accepts a partial dict, validates via the domain's pydantic model (`<Model>.to_controller_update`), and shows a before/after preview.

1. Manager method: fetch existing → copy → merge updates → PUT full object
   - **Anchor:** `apps/network/src/unifi_network_mcp/managers/network_manager.py:update_network`
2. Define or extend the pydantic model in `packages/unifi-core/src/unifi_core/<server>/models/<domain>.py`. Mark mutable fields as such (default mutability); read-only fields use `json_schema_extra={"mutable": False}`.
3. Tool function: validate the caller's partial dict via `<Model>.to_controller_update(fields)`, fetch current state for preview, use `update_preview`.
   - **Anchor (model):** `packages/unifi-core/src/unifi_core/network/models/wlans.py`
   - **Anchor (tool):** `apps/network/src/unifi_network_mcp/tools/wlans.py:update_wlan`
5. Tool description MUST include: "Pass only the fields you want to change — current values are automatically preserved."
6. Run `make manifest`
7. Add tests covering: partial merge preserves unmentioned fields, not-found returns False, empty update is a no-op

### Add or migrate a domain to shared field models

When a tool domain has list/create/update tools, define a shared pydantic model as the single source of truth for field names, types, and mutability. This ensures list output field names are always accepted by create/update tools — preventing silent data loss when callers round-trip fields from list output into create/update calls.

1. Create model in `packages/unifi-core/src/unifi_core/<server>/models/<domain>.py`
   - One `BaseModel` class with all fields (mutable + read-only)
   - Read-only fields marked with `json_schema_extra={"mutable": False}`
   - Export `MUTABLE_FIELDS` and `READ_ONLY_FIELDS` frozensets
   - Co-locate translation helpers: `from_controller(raw)`, `to_controller_create(model)`, `to_controller_update(fields)`
   - Models live in `unifi-core` so both the MCP tool layer and the API server can import them
   - **Anchor:** `packages/unifi-core/src/unifi_core/network/models/acl.py`
2. Refactor tool functions to derive I/O from the model
   - List/get tools: `from_controller(raw).model_dump()`
   - Create tool: build model from params → `to_controller_create()` → manager
   - Update tool: validate keys against `MUTABLE_FIELDS`, translate via `to_controller_update()` → manager
   - **Anchor:** `apps/network/src/unifi_network_mcp/tools/acl.py`
3. Manager layer is unchanged — continues to speak the controller API dialect
4. Add a field symmetry test asserting every mutable field is a create param
   - **Anchor:** `apps/network/tests/unit/test_acl_tools.py:TestListAclRules.test_list_and_create_field_symmetry`
5. Register the `(server, domain)` pair in the cross-layer symmetry test
   - The matching Strawberry type at `unifi_api.graphql.types.<server>.<domain>` must expose every pydantic `MUTABLE_FIELDS` name with a compatible type annotation
   - This catches MCP↔API drift at PR time
   - **Anchor:** `apps/api/tests/unit/test_cross_layer_symmetry.py`
6. **If the change touches the API surface** (a Strawberry type, resolver field, REST route, or serializer), regenerate the API artifacts. These are **NOT** produced by `make manifest` — there is no make target for them, so it is easy to miss and the drift gates then fail at PR time:
   - `apps/api/src/unifi_api/graphql/schema.graphql` (GraphQL SDL), `apps/api/openapi.json`, and **both** docgen reference docs `apps/api/docs/graphql-reference.md` AND `apps/api/docs/openapi-reference.md` (the REST-endpoint reference)
   - Regen: SDL via `print(str(schema))`; openapi via `app.openapi()`; **both reference docs at once** via `python -m unifi_api.graphql.docgen` (it writes graphql-reference.md AND openapi-reference.md — calling only `render_reference()` misses the REST one). Exact commands are in the drift gates' docstrings (`apps/api/tests/graphql/test_sdl_drift.py`, `test_openapi_drift.py`, `test_docs_drift.py`)
7. Run `make manifest`
8. Commit model + refactored tools + tests together

### Modify the permission system

1. Shared logic: `packages/unifi-mcp-shared/src/unifi_mcp_shared/policy_gate.py`
2. Server-specific categories: `CATEGORY_MAP` in the app's `categories.py`
3. Enforcement: `permissioned_tool` decorator in the app's `main.py`
4. Policy gates configured via `UNIFI_POLICY_*` env vars (no config.yaml section)
5. Tests in `packages/unifi-mcp-shared/tests/` and `apps/<server>/tests/unit/`

### Add shared functionality

1. Choose package: `unifi-core` (controller abstractions, no MCP dependency) or `unifi-mcp-shared` (MCP utilities)
2. Add module to `packages/<pkg>/src/<pkg_name>/`
3. Add tests in `packages/<pkg>/tests/`
4. Run `make core-test` or `make shared-test`

## Quality Gates

A change is not done unless ALL pass:

```bash
make pre-commit   # format + lint + sync-skills + test
```

### Tool Changes Checklist

- [ ] Follows anchor pattern (thin wrapper, delegates to manager)
- [ ] Returns standardized `{"success": bool, ...}` response
- [ ] Added to `TOOL_MODULE_MAP` in `categories.py`
- [ ] `make manifest` run and manifest committed
- [ ] If the change touches the API surface (Strawberry type / resolver / route / serializer): `apps/api/src/unifi_api/graphql/schema.graphql`, `apps/api/openapi.json`, and BOTH docgen docs `apps/api/docs/graphql-reference.md` + `apps/api/docs/openapi-reference.md` (run `python -m unifi_api.graphql.docgen` to regenerate both) regenerated and committed — NOT covered by `make manifest`; the `test_sdl_drift` / `test_openapi_drift` / `test_docs_drift` gates enforce them
- [ ] Mutating tools implement preview-then-confirm
- [ ] Tools returning raw controller secrets redact at the boundary according to response policy (see Response redaction pattern)
- [ ] Permission category and action set via decorator kwargs
- [ ] `ToolAnnotations` added
- [ ] Tests cover success, error, and permission denial paths
- [ ] Works in all three registration modes (lazy, eager, meta_only)

### Configuration Changes Checklist

- [ ] Default in `config.yaml` with `${oc.env:VAR,default}`
- [ ] `.env.example` updated
- [ ] README.md configuration table updated

### Version and Manifest Rules

- Version is derived from git tags via `hatch-vcs`. MUST NOT manually edit version in `pyproject.toml`.
- Before release tags, update downstream `pyproject.toml` dependency ranges when a downstream package requires newly tagged `unifi-core` or `unifi-mcp-shared` code; pip only installs versions allowed by the published wheel metadata.
- Each app's `tools_manifest.json` MUST be regenerated (`make manifest`) and committed before release.
- The Cloudflare worker lives in `apps/worker/` as a self-contained Node/TypeScript app. It is intentionally excluded from the uv workspace and released from `worker/v*` tags via npm; run `make worker-check` for focused worker changes and root `make check` before merging worker or relay protocol changes.

## Patterns

### Silent-drop mitigation (#138)

All three app servers run on `StrictKwargFastMCP` (a `FastMCP` subclass in `packages/unifi-mcp-shared/src/unifi_mcp_shared/strict_dispatch.py`) that intercepts incoming `tools/call` requests and rejects unknown top-level kwargs against `tools_manifest.json` BEFORE pydantic's `extra="ignore"` can silently drop them. Schema-dict drops (free-form `*_data` dicts) are independently caught by `additionalProperties: false` from #206. Do not bypass this wrapper; do not patch FastMCP internals to achieve the same effect. The wrapper retires when upstream lands `extra="forbid"` on FastMCP's tool arg models — at that point `StrictKwargFastMCP` becomes a no-op guard and can be removed cleanly.

- **Anchor:** `packages/unifi-mcp-shared/src/unifi_mcp_shared/strict_dispatch.py`

### Response redaction (#348)

Secret-bearing response fields are redacted at egress boundaries, NOT in domain models — `from_controller` and friends carry real values. Sensitivity is decided by key name in `packages/unifi-core/src/unifi_core/redaction.py` (`is_sensitive_key` / `redact_sensitive_fields` / `redact_value`); policy is resolved centrally by `packages/unifi-core/src/unifi_core/policy.py` (`should_redact_sensitive_fields`) and exposed to MCP apps through `packages/unifi-mcp-shared/src/unifi_mcp_shared/response_policy.py`. Redact once per surface — MCP tool returns, the REST serializer, GraphQL types, SSE frames, and diagnostics — using `redact_sensitive=True` by default. Raw secret values are enabled only by response policy (`UNIFI_REDACT_SENSITIVE_FIELDS=false` or a server-specific override such as `UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_PROTECT_REDACT_SENSITIVE_FIELDS=false`, `UNIFI_ACCESS_REDACT_SENSITIVE_FIELDS=false`, or `UNIFI_API_REDACT_SENSITIVE_FIELDS=false`); do not add per-tool/request opt-out arguments. Redacted values surface as the marker `***REDACTED***`; write-back of the marker is rejected centrally in `StrictKwargFastMCP.call_tool` (MCP) and `dispatch_action` (API) — do NOT add per-tool marker checks.

- **Anchor:** `packages/unifi-core/src/unifi_core/redaction.py`

### Extension Over Patching

- Prefer adding new tool modules and managers over modifying existing ones
- New tool categories get their own manager + tool module (vertical slice)
- Fix root causes, not symptoms

### Conflict Resolution

- Consult the anchor files in Golden Paths when unsure which pattern to follow
- If no anchor applies, ask before inventing a new pattern
- If adopting a genuinely new pattern, update this rules file first

### Plan First

Before non-trivial changes, produce a short plan covering: approach, impacted files, which anchors apply, new tests needed, verification steps.

**Skip the plan only when all are true:** single-file edit, no new behavior or tools, no config/permission/schema changes, no new tests.

<!-- myco:managed:start -->
## Myco Managed Guidance

- When `capture.ignore_plan_dirs_in_git` is enabled, custom directories in `capture.plan_dirs` may be intentionally gitignored after capture into Myco.
- Do not force-add files from intentionally gitignored custom plan directories unless the user explicitly asks.
- When orienting in this codebase — finding a feature, locating files relevant to a change, or understanding an unfamiliar subsystem — use Myco first: call `myco tool call myco_cortex --json --input '{"op":"canopy_map"}'` as the CLI path, or `myco_cortex({"op":"canopy_map"})` via MCP when the host exposes Myco tools cleanly, before falling back to Glob/Grep.
<!-- myco:managed:end -->
