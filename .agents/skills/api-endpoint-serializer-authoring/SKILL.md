---
name: myco:api-endpoint-serializer-authoring
managed_by: myco
display_name: API Endpoint and Serializer Authoring (apps/api)
user-invocable: false
description: >-
  Apply this skill when adding an endpoint to apps/api/, authoring a
  mutation-ack serializer, wiring ManagerFactory, resolving Phase 5A routing
  collisions, or diagnosing the validate_manifest or test_resource_route_coverage
  CI gates. Covers: resource vs. action classification (409 vs. 200+envelope);
  Cursor + paginate() pagination in services/pagination.py; ManagerFactory
  concurrency scoping; apps/api → unifi-core-only dependency rule; Phase 5A
  patterns (capability-aware dispatch on product_kinds, dual-kind stats,
  wrapper-dict unwrap, path disambiguation, TOOL_ROUTE_OVERRIDES in
  test_resource_route_coverage.py); @register_serializer(tools={...}) decorator;
  seven RenderKind values; field-curation discipline; _reset_registry_for_tests()
  isolation; and the two CI gates. Post-Phase 6: read tools use Strawberry types
  (graphql-api-extension skill); serializers cover mutation acks only. Activate
  even without explicit serializer mention — any apps/api/ PR may need CI-gate
  alignment.
tags:
  - api
  - serializer
  - routing
  - endpoint
  - phase-5a
  - ci-gates
allowed-tools:
  - Read
  - Grep
  - Edit
  - Write
  - Bash
---

# API Endpoint and Serializer Authoring (apps/api)

## A. Adding a Resource or Action Endpoint

### 1. Classify the endpoint type
- **Resource endpoint** (`GET /v1/sites/{id}/cameras`): implies the resource
  exists; return HTTP **409** when the required product is absent.
- **Action endpoint**: advisory; always return HTTP **200** with a
  `capability_not_available` envelope when the capability is missing — never
  404 or 409 for action endpoints.

### 2. Wire cursor-based pagination
Use `Cursor` and `paginate()` from
`apps/api/src/unifi_api/services/pagination.py`:

```python
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

cursor = Cursor.decode(cursor_str) if cursor_str else None
page, next_cursor = paginate(items, cursor=cursor, limit=limit, key_fn=key_fn)
```

- Cursor encodes `{last_id, last_ts}` as Base64 — survives new inserts;
  offset/page-number pagination does not.
- Default limit 50, max 200. Expose `cursor` as an opaque query-string param.

### 3. Apply the dependency rule
`apps/api/` MUST only import from `unifi-core`. Never import `unifi-mcp-shared`
inside `apps/api/` — it couples the REST server to MCP protocol concerns.

### 4. Wire ManagerFactory
`ManagerFactory` lives in `apps/api/src/unifi_api/services/managers.py`. It
caches one manager per `(controller_id, product)` pair behind asyncio locks:

```python
manager = await factory.get_connection_manager(session, controller_id, product)
```

- `product_kinds` in the DB row is a comma-separated string. The factory
  splits it and raises `UnknownProduct` if the product isn't listed — so set
  `product_kinds` accurately when registering a controller.
- Each concurrency scope (request) shares the cached manager instance; no
  per-request teardown.

---

## B. Phase 5A Advanced Routing Patterns

### Capability-aware dispatch
When two products expose identically-named endpoint families (e.g., both
Network and Protect expose `/events`), dispatch at request time by consulting
`controller.product_kinds`. Route to the correct manager based on which
products are active — avoids collisions without duplicate routes.

### Path disambiguation for cross-product collisions
Add per-product prefixes on ambiguous routes:
- `/access/events` — not `/events`
- `/protect/health` — not `/health`

Without prefixes, three product packages collide in the route namespace.

### Dual-kind stats
Accept a `kind=timeseries|detail` query parameter on the same endpoint; select
the appropriate `RenderKind` at the route layer. Avoids duplicating tools for
two render modes of the same data.

### Wrapper-dict unwrap pattern
When a UniFi API returns a wrapper dict (e.g., switch-ports, port-stats,
lldp-neighbors):
1. Register the serializer as `RenderKind.DETAIL`.
2. At the route layer, call the tool inline and override `render_hint` to
   emit `LIST`.

Do NOT push list logic into the DETAIL serializer.

### TOOL_ROUTE_OVERRIDES
When a route function name doesn't follow the default convention (tool name
minus product prefix), add an entry to `TOOL_ROUTE_OVERRIDES` in:

```
apps/api/tests/test_resource_route_coverage.py
```

This is a **test-time mapping only** — it is NOT applied at server startup.
Adding an override here does NOT register a route; you still need a real
FastAPI route function. The dict currently has 17 entries (Task 22 audit).

---

## C. Authoring a Serializer (Post-Phase 6)

> **Phase 6 shift:** Read tools (`unifi_list_*`, `unifi_get_*`, `protect_*`,
> `access_list_*`) now project via Strawberry types — see the
> `graphql-api-extension` skill. The serializer layer covers **mutation acks
> only** (create/update/delete/toggle). `validate_manifest` accepts either a
> serializer or a Strawberry type registration as valid coverage.

### 1. Module placement
```
apps/api/src/unifi_api/serializers/<domain>/<resource>.py
```
Example: `apps/api/src/unifi_api/serializers/network/dns.py`

### 2. Decorator syntax — use the `tools=` dict form
The `tool_name=` / `kind=` keyword form does NOT exist. Use:

```python
from unifi_api.serializers._base import RenderKind, Serializer, register_serializer

@register_serializer(
    tools={
        "unifi_create_dns_record": {"kind": RenderKind.DETAIL},
        "unifi_update_dns_record": {"kind": RenderKind.DETAIL},
        "unifi_delete_dns_record": {"kind": RenderKind.DETAIL},
    },
)
class DnsMutationAckSerializer(Serializer):
    @staticmethod
    def serialize(obj) -> dict:
        if isinstance(obj, bool):
            return {"success": obj}
        if isinstance(obj, dict):
            return obj
        return {"result": str(obj)}
```

For a single tool using the class-level `kind`:
```python
@register_serializer(tools=["unifi_create_foo"])
```

### 3. RenderKind taxonomy
Seven values in `apps/api/src/unifi_api/serializers/_base.py`:

| Value | Use |
|---|---|
| `LIST` | Collection of items |
| `DETAIL` | Single resource or mutation ack |
| `DIFF` | Before/after comparison |
| `TIMESERIES` | Time-ordered data points |
| `EVENT_LOG` | Event stream |
| `EMPTY` | Action with no meaningful return |
| `STREAM` | Streaming response |

### 4. Field curation discipline
Declare exactly which fields appear for each `kind`. Serializers are curated,
not pass-through. Do not add a "return everything" serializer — the cumulative
curation effort across 235+ tools is intentional.

### 5. Serializer layering rule
Serializers live in `apps/api/` only. Managers and MCP tool functions MUST NOT
reference render hints or catalog metadata. This keeps MCP servers free of
serialization coupling (decision-a63cb266).

---

## D. CI Gates

### validate_manifest
Runs at server startup via `discover_serializers()` in
`apps/api/src/unifi_api/serializers/_registry.py`. Raises
`SerializerRegistryError` if any manifest tool lacks both a serializer
registration and a Strawberry type registration. After Phase 6, you need
at least one — not necessarily both.

### test_resource_route_coverage
File: `apps/api/tests/test_resource_route_coverage.py`

Every read tool must have a registered GET resource route. When adding a read
tool:
1. Register a route function in the FastAPI app.
2. If the name doesn't follow the default convention, add to
   `TOOL_ROUTE_OVERRIDES` in that test file.
3. Run `pytest apps/api/tests/test_resource_route_coverage.py` locally.

### Test isolation for serializer tests
Import `_reset_registry_for_tests` from `unifi_api.serializers._registry`.
It clears module-level registries AND evicts serializer submodules from
`sys.modules`, forcing `discover_serializers` to re-import and re-run all
decorators. Call in both setup and teardown.

```python
from unifi_api.serializers._registry import _reset_registry_for_tests

def setup_function():
    _reset_registry_for_tests()

def teardown_function():
    _reset_registry_for_tests()
```

---

## Cross-Cutting Gotchas

- **`ManagerFactory`, not `ControllerFactory`**: class lives in
  `apps/api/src/unifi_api/services/managers.py`. Wrong name → `ImportError`.
- **`product_kinds` is comma-separated in the DB**: Always split with
  `.split(",")` and filter empty strings. Inaccurate `product_kinds` causes
  `UnknownProduct` at request time.
- **TOOL_ROUTE_OVERRIDES is test-only**: Does not register routes. You still
  need a real FastAPI route function registered in the app.
- **Live smoke required**: Mock CI cannot detect UniFi API contract violations.
  Six confirmed violation classes only surfaced via live hardware testing.
  See `live-smoke-testing` skill before cutting a PR.
- **`apps/api` dependency boundary is enforced**: Importing `unifi_mcp_shared`
  anywhere in `apps/api/` is a build-time error.
