---
name: myco:extend-unifi-api
description: >-
  Apply this skill when working on apps/api/ — implementing resource endpoints,
  wiring multi-controller factory managers, designing pagination for new list
  endpoints, or choosing error contracts. Covers: Strawberry GraphQL type
  registration via type_registry.register_tool_type() for read tools; cursor-based
  pagination via the module-level paginate() function and Cursor class; render-hint
  kind conventions and forward-compatible optional extensions; HTTP 409 vs
  200-envelope error contracts for resource vs action endpoints; ManagerFactory
  class for multi-controller concurrency; apps/api dependency rule (unifi-core
  only); the 8-surface new-tool CI gate per Phase 8 (Strawberry projection,
  GraphQL Query field, REST resource route, Action dispatcher, Fixture e2e,
  Artifact regeneration, openapi.json drift gate, graphql-reference.md drift gate);
  and release tag policy. Activate even when the user hasn't explicitly asked about
  types or pagination — any PR touching apps/api/ should follow these patterns.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Extending the unifi-api REST Platform

`apps/api/` is the non-MCP HTTP delivery channel for UniFi controller data —
the substrate for future app consumers (Pi extension, dashboards, Electron
desktop). It is **not** an MCP server; its patterns, types, pagination, and
error contracts are distinct from the MCP layer and must stay that way.

As of Phase 6, the read-path serialization layer has been replaced with
Strawberry GraphQL types. Every new tool added to the API must implement a
full 8-surface contract per Phase 8 requirements (see Procedure A).

This skill covers everything needed when adding or modifying a resource in
`apps/api/`: registering Strawberry types, paginating list endpoints, setting
render hints, choosing error contracts, wiring factory managers for
multi-controller concurrency, and staying within the dependency rules.

## Prerequisites

- `unifi-core` already has the manager method for the resource (or you've
  added one following the existing manager patterns).
- The MCP tool function already exists (or is being added in the same PR).
- You are working in `apps/api/src/unifi_api/` — not in `apps/network/`,
  `apps/protect/`, or `apps/access/`.
- **Dependency rule:** `apps/api/` may only import from `unifi-core`. It must
  NOT import from `unifi-mcp-shared` (that package is for MCP servers only).
  Violating this creates circular imports.

## Procedure A: 8-Surface New-Tool Checklist (Phase 8 Requirement)

Phase 8 introduced a mandatory 8-surface requirement for every new tool added
to the API. All eight surfaces must be completed and gated before merge.

**The 8 surfaces:**

1. **Strawberry GraphQL type** — Define in `apps/api/src/unifi_api/types/<domain>/<resource>.py`
   Register via `type_registry.register_tool_type("unifi_tool_name", YourType)`

2. **GraphQL Query field** — Add query resolver in `apps/api/src/unifi_api/resolvers/<domain>/<resource>.py`
   Wire into `schema.py` Query root type

3. **REST resource route** — Implement `GET /v1/sites/{site_id}/<resource>` and `GET /v1/sites/{site_id}/<resource>/{id}`
   in `apps/api/src/unifi_api/routes/<domain>/<resource>.py`

4. **Action dispatcher** — Implement `POST /v1/actions/unifi_tool_name` with manager dispatch

5. **Fixture e2e test** — Add `test_<tool_name>.py` in `apps/api/tests/fixtures/` covering
   both GraphQL and REST resource paths with real controller data (or mocked)

6. **Artifact regeneration** — Run `scripts/codegen_api_docs.py` to update openapi.json

7. **openapi.json drift gate** — CI confirms openapi.json matches the current API surface
   (commit updated openapi.json from codegen)

8. **graphql-reference.md drift gate** — CI confirms graphql-reference.md matches the
   GraphQL schema (commit updated reference from codegen)

**Merge blocker:** Any PR adding a new tool/resource must declare all 8 surfaces
as complete. Missing surfaces are flagged in CI. Do NOT mark a surface complete
unless the code actually implements it.

## Procedure B: Registering Strawberry Types (Phase 6+)

**Serializers are obsolete.** Phase 6 replaced the serializer layer entirely with
Strawberry types. All read-path type marshaling now goes through GraphQL type
registration.

**1. Define the Strawberry type:**

Create a new file at the correct path:

```
apps/api/src/unifi_api/types/<domain>/<resource>.py
```

Example:

```python
# apps/api/src/unifi_api/types/network/clients.py
import strawberry
from typing import Optional
from unifi_api.types._base import UniFiType

@strawberry.type
class Client(UniFiType):
    mac: str
    hostname: Optional[str]
    ip: Optional[str]
    status: str
    last_seen: int

    @classmethod
    def from_manager_object(cls, obj):
        """Convert manager object to Strawberry type."""
        return cls(
            mac=obj.raw.get("mac"),
            hostname=obj.raw.get("hostname"),
            ip=obj.raw.get("last_ip"),
            status=obj.raw.get("state"),
            last_seen=obj.raw.get("last_seen"),
        )
```

**2. Register the type:**

Register it in `apps/api/src/unifi_api/types/__init__.py` (or a registry module):

```python
from .network.clients import Client
from unifi_api.types._base import type_registry

type_registry.register_tool_type("unifi_list_clients", Client)
type_registry.register_tool_type("unifi_get_client", Client)
```

**3. The registry automatically wires types for GraphQL Query fields and REST
resource endpoints.** Both paths dispatch through the same Strawberry type.

## Procedure C: Mutation Tool Registration (Write Path)

Mutation tools (create, update, delete) are registered separately from read types.
The mutation_registry controls which write operations are exposed to GraphQL mutations
and action endpoints.

**Mutation flow:**

```
MCP tool function
  ↓
Mutation tool definition with parameters
  ↓
mutation_registry.register_mutation(tool_name, handler)
  ↓
GraphQL Mutation field wired to the handler
  ↓
Action endpoint POST /v1/actions/{tool_name}
```

**1. Define the mutation handler:**

```python
# apps/api/src/unifi_api/mutations/network/firewall.py
from unifi_api.mutations._base import MutationHandler

class FirewallPolicyCreateHandler(MutationHandler):
    async def execute(self, request_data: dict, controller_id: str, site_id: str):
        manager = await self.get_manager(controller_id, "network", "firewall_policy_manager")
        return await manager.create_policy(**request_data)
```

**2. Register the mutation:**

```python
# In the mutation_registry init
from unifi_api.mutations.network.firewall import FirewallPolicyCreateHandler
from unifi_api.mutations._base import mutation_registry

mutation_registry.register_mutation(
    "unifi_create_firewall_policy",
    FirewallPolicyCreateHandler(),
)
```

**3. The registry wires the mutation to both GraphQL and REST action endpoints.**
The mutation becomes available as:
- GraphQL: `mutation { createFirewallPolicy(input: {...}) { ... } }`
- REST: `POST /v1/actions/unifi_create_firewall_policy`

**Rule:** All mutation handlers must follow the same preview/confirm flow
(Procedure H) and must not use the shared validator with injected defaults
(see skill: community-pr-review, Gate 4).

## Procedure D: Implementing Cursor-Based Pagination

Resource list endpoints use cursor-based pagination — not offset-based.
Offset pagination skips or duplicates rows under concurrent inserts; cursor
pagination is stable because it keys off the last-seen `(ts, id)` tuple.

**Endpoint signature:**

```
GET /v1/sites/{id}/clients?limit=50&cursor=<opaque>
```

**Response envelope** (every list endpoint returns this shape):

```json
{
  "items": [ /* up to limit objects */ ],
  "next_cursor": "eyJsYXN0X2lkIjogImFiYzEyMyIsICJsYXN0X3RzIjogMTcyNzc0ODkwMH0="
}
```

The cursor is an opaque base64-encoded `{last_id, last_ts}`. Consumers detect
end-of-list when `next_cursor` is `null`. Do NOT include `total_count` — it
requires a full table scan and is stale under concurrency.

**Using the pagination helpers** (`services/pagination.py`):

```python
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

# Decode incoming cursor (if any)
cursor: Cursor | None = None
if cursor_param:
    try:
        cursor = Cursor.decode(cursor_param)
    except InvalidCursor:
        raise HTTPException(
            status_code=400,
            detail={"kind": "invalid_cursor", "message": "cursor position has been deleted"},
        )

# Fetch full snapshot from the manager (pagination is applied in-memory)
items = await client_manager.get_clients()

# Apply pagination: returns (page, next_cursor_or_None)
page, next_cursor = paginate(
    items,
    limit=limit,
    cursor=cursor,
    key_fn=lambda item: (item.raw.get("last_seen", 0), item.raw.get("_id", "")),
)

return {
    "items": [item_type.from_manager_object(item) for item in page],
    "next_cursor": next_cursor.encode() if next_cursor else None,
}
```

`paginate()` is a **module-level function** — not a class method. It takes:
- `items`: the full unsorted snapshot from the manager
- `limit`: page size (keyword-only)
- `cursor`: decoded `Cursor` or `None` (keyword-only)
- `key_fn`: callable returning `(ts, id)` for each item (keyword-only)

It returns `(page: list, next_cursor: Cursor | None)`. The `Cursor` class
handles base64 encoding/decoding; call `.encode()` to produce the opaque
string for the response.

**Constraints:**

- `limit` default: 50; max: 200. Reject higher values with `400 Bad Request`.
- UniFi managers return full snapshots — pagination is applied in-memory after
  the manager call, not via per-page controller round-trips.

## Procedure E: Designing Render Hints

Every Strawberry type declares a `kind` field at the class level. This is the
minimum required contract. Optional metadata fields are additive — declare them
only when a specific consumer needs them.

**Seed kinds:**

| Kind  | When to use                                           |
|-------|-------------------------------------------------------|
| `LIST`        | Flat collection (clients, devices, rules)             |
| `DETAIL`      | Single entity with full fields                        |
| `DIFF`        | Structured change delta (mutation preview)            |
| `TIMESERIES`  | Time-indexed data (uptime, event graphs)              |
| `EVENT_LOG`   | Log entries with timestamps                           |
| `EMPTY`       | Success with no output (config write, delete)         |
| `STREAM`      | Streaming data (camera streams, live feeds)           |

**Minimum — every type must have this:**

```python
@strawberry.type
class MyType(UniFiType):
    kind: str = "LIST"  # required
    # ... fields ...
```

**Optional extensions — declare only what downstream renderers need:**

```python
@strawberry.type
class MyType(UniFiType):
    kind: str = "LIST"
    primary_key: str = "mac"                              # optional
    display_columns: list[str] = ["hostname", "ip"]      # optional
    sort_default: str = "last_seen"                       # optional
```

Clients that don't understand optional fields ignore them — no breaking change.

## Procedure F: Resource Endpoints vs. Action Endpoints — Error Contracts

These two endpoint families follow different error conventions. Don't mix them.

**Resource endpoints** (`GET /v1/sites/{id}/{resource}`) follow REST convention:
HTTP status code signals success; body provides detail.

| Situation                        | Status | Body                                                          |
|----------------------------------|--------|---------------------------------------------------------------|
| Success                          | 200    | `{"items": [...], "next_cursor": ...}`                        |
| Controller lacks required product| **409**| `{"kind": "capability_mismatch", "missing_product": "protect", "message": "..."}` |
| Invalid cursor                   | 400    | `{"kind": "invalid_cursor", "message": "..."}`                |
| limit > 200                      | 400    | standard validation error                                     |

Why 409 for capability mismatch (not 404, not 200):
- Not 404: the endpoint path is valid; the issue is controller state.
- Not 200: a GET that can't return the resource is a 4xx, not a success.
- 409 "conflicts with server state" is accurate: the controller doesn't have
  the required product.

```
GET /v1/sites/default/cameras?controller=xyz
→ HTTP 409 Conflict
{"kind": "capability_mismatch", "missing_product": "protect",
 "message": "Controller does not support the Protect product"}
```

**Action endpoints** (`POST /v1/actions/{tool_name}`) follow MCP convention:
always return HTTP 200; surface errors in the envelope.

```json
POST /v1/actions/unifi_list_cameras
→ HTTP 200
{"success": false, "error": "Cameras product not available"}
```

**Client handling pattern:** switch on `status === 409` before parsing body;
use `kind === "capability_mismatch"` to distinguish from ETag conflicts on
mutations.

## Procedure G: Wiring the Multi-Controller Factory

`unifi-api` serves multiple concurrent controller sessions in one process, so
the MCP-style global singleton factories don't work here. The implementation
uses `ManagerFactory` — a manual async-aware cache (explicitly **not**
`@lru_cache`, because async values and per-call session args make `@lru_cache`
the wrong tool).

**All factory logic lives in one module:**

```
apps/api/src/unifi_api/services/managers.py
```

**Accessing managers in routes** — the factory is wired into `app.state`
during lifespan; routes access it there:

```python
from unifi_api.services.managers import ManagerFactory

# In a route handler:
factory: ManagerFactory = request.app.state.manager_factory

# Get a connection manager for a specific controller + product:
cm = await factory.get_connection_manager(session, controller_id, "network")

# Get a named domain manager (attr_name matches the manager class name in the
# product builder dict, e.g. "client_manager", "firewall_manager"):
client_mgr = await factory.get_domain_manager(
    session, controller_id, "network", "client_manager"
)
```

`ManagerFactory` uses `asyncio.Lock` per `controller_id` around construction
to prevent concurrent-cache-miss races. Cache lives at the connection layer
because that's where aiohttp session state lives; manager construction is
cheap (just stores a reference to the `ConnectionManager`).

**Cache invalidation** — on controller delete or credentials update:

```python
await factory.invalidate_controller(controller_id)
```

This evicts all cached `ConnectionManager` and domain manager instances for
that controller.

**`unifi-core` needs zero changes** for this pattern. Existing managers
already support per-controller instantiation; `ManagerFactory` layers the
async-safe caching on top.

## Procedure H: Mutation Tools with confirm=false Preview and Sibling Preservation

Mutation action endpoints often support a "preview" mode where `confirm=false` returns
a simulated result without executing the mutation. This allows clients to show users
what would change before requiring confirmation.

**confirm=false preview pattern:**

When a mutation tool has a `confirm` parameter, the action endpoint handler must respect it:

```python
# POST /v1/actions/unifi_update_network_settings
result = await network_manager.update_network_settings(
    {...}, 
    confirm=request.body.get("confirm", False)
)
```

In preview mode (`confirm=false`), the manager method returns a **preview object**
showing the intended changes without persisting them. The response envelope is the same
for both preview and confirmed modes — the client interprets `confirm=false` as a
hint to show a confirmation dialog before re-submitting with `confirm=true`.

**deepcopy sibling preservation for merge operations:**

When a mutation modifies a complex object (e.g., firewall rule with nested conditions),
use `copy.deepcopy()` to preserve unmodified sibling fields during the merge. This
prevents accidental field deletion.

```python
import copy

async def update_firewall_rule(rule_id: str, updates: dict) -> FirewallRule:
    # Fetch the current rule
    current = await self.get_firewall_rule(rule_id)
    
    # Deep copy to avoid mutating the cached original
    merged = copy.deepcopy(current.raw)
    
    # Apply updates (shallow merge is safe here because merged is a deep copy)
    merged.update(updates)
    
    # Send to API
    result = await self._api.put(f"/rest/firewall/rule/{rule_id}", json=merged)
    return FirewallRule(result)
```

**Why deepcopy matters:** If you merge updates into `current.raw` directly, sibling
fields that weren't specified in `updates` may be dropped by the API if they're not
in the final payload. Deepcopy ensures you're working on an independent copy and can
safely apply sparse updates without side effects. This is especially important for
rules, policies, and config objects where nested fields are common and the API is
strict about required fields.

**Pattern for multi-step mutations:**

```python
# Example: update rule + conditions in one operation
async def update_rule_with_conditions(rule_id: str, new_conditions: list) -> FirewallRule:
    current = await self.get_firewall_rule(rule_id)
    merged = copy.deepcopy(current.raw)
    
    # Preserve other fields, replace only conditions
    merged["conditions"] = new_conditions
    
    result = await self._api.put(f"/rest/firewall/rule/{rule_id}", json=merged)
    return FirewallRule(result)
```

## Cross-Cutting Gotchas

**Dependency rule — never import `unifi-mcp-shared` from `apps/api/`.** `unifi-mcp-shared` contains validator schemas for MCP servers. Importing it from `apps/api/` creates circular imports and couples two unrelated delivery channels. The correct dependency chain is: `apps/api/` → `unifi-core` only.

**Serializer layer is obsolete (Phase 6+).** Do not write new serializers. All read-path marshaling goes through Strawberry types and `from_manager_object()` conversion. Legacy serializer code may remain for reference but is not wired into new tools.

**8-surface requirement is mandatory as of Phase 8.** Every new tool must implement all 8 surfaces (type, query, resource routes, action dispatcher, fixtures, codegen artifacts, drift gates). Incomplete PRs are merge-blocked by CI.

**Mutation registry controls write-path exposure.** Mutations must be explicitly registered in mutation_registry to be wired to GraphQL mutations and action endpoints. An unregistered mutation will not be callable via the API, even if the manager method exists.

**Release tag policy — no `api/*` tags until Phase 7.** Phases 0–6 are internal development only. The first consumer-facing tag is `api/v0.1.0` (Phase 7), paired with a GHCR Docker image, docs, and release notes. Do not cut partial release tags; they create support burden before the full surface is ready.

**Single PR per phase.** Phases 0–2 each landed as a single PR despite comparable scope. Phase 3 follows the same pattern. Splitting into sub-PRs creates incoherent transitional states with no shipping value to justify the overhead.

**New tool category contribution checklist** (extends `add-tool-category`):
1. Manager method in `unifi-core` — shared, already required
2. MCP tool function in `apps/<domain>/` — already required
3. **All 8 surfaces** in `apps/api/` — Strawberry type, GraphQL query, REST routes, action dispatcher, fixture tests, codegen artifacts, and drift gate commits — required for Phase 8+ CI gate
4. **Mutation registration** (for write tools) — mutation_registry.register_mutation() wiring required for create/update/delete tools
