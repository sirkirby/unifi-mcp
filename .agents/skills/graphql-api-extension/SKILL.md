---
name: myco:graphql-api-extension
description: |
  Apply this skill when adding a new resource to the GraphQL API layer in
  apps/api/ — writing a Strawberry type, wiring an N+1-safe resolver,
  registering the type, adding relationship edges, regenerating SDL/docs, or
  diagnosing the 6 CI gates (test_graphql_coverage, test_sdl_drift,
  test_docs_drift, test_n1_regression, test_naming_convention,
  test_versioning_policy). Covers: scaffold-resource CLI;
  from_manager_output/render_hint/to_dict three-method contract; registration
  in type_registry_init.py via register_tool_type(); ctx.cache.get_or_fetch()
  N+1 dedupe; relationship edges via _controller_id/_site private fields;
  docgen regeneration (uv run --package unifi-api-server python -m
  unifi_api.graphql.docgen); and the EXEMPT_PRODUCTS ratchet (permanently
  empty). Activate whenever a PR touches apps/api/src/unifi_api/graphql/ or
  adds a read tool needing a GraphQL Query field — even if the user doesn't
  mention Strawberry.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# GraphQL API Extension (unifi-api)

## A — Scaffold a New Resource

Run the CLI generator first to create a starter type file and resolver stub:

```bash
cd apps/api
uv run --package unifi-api-server unifi-api graphql scaffold-resource <product> <resource>
# Example: unifi-api graphql scaffold-resource network port_profile
```

The scaffold creates files under `apps/api/src/unifi_api/graphql/types/<product>/`
and a resolver stub in `resolvers/<product>.py`. It is a starting template —
all 6 CI gates still run and must pass. The scaffold does **not** add the
registration call to `type_registry_init.py`; do that in Procedure B.

## B — Author a Strawberry Type and Register It

**1. Write the type class** in
`apps/api/src/unifi_api/graphql/types/<product>/<resource>.py`.

All Strawberry types implement a three-method contract:

```python
import strawberry
from dataclasses import asdict
from typing import Any

@strawberry.type(description="A UniFi <resource> record.")
class MyResourceType:
    id: strawberry.ID | None
    name: str | None
    # ... additional fields

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        """Drives column hints in API responses."""
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["name", ...],
            "sort_default": "name:asc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "MyResourceType":
        """Receives raw manager dict or object; shapes it into the type."""
        raw = getattr(obj, "raw", obj if isinstance(obj, dict) else {})
        return cls(
            id=raw.get("_id") or raw.get("id"),
            name=raw.get("name"),
            # Field names in raw often differ: "_id"→id, "ip_subnet"→subnet
        )

    def to_dict(self) -> dict:
        """Powers the REST projection layer."""
        out = asdict(self)
        return {k: v for k, v in out.items()
                if not k.startswith("_") and not callable(v)}
```

All three methods are required. `from_manager_output` receives the raw dict or
object from the manager layer. `to_dict` drives REST response shaping.
`render_hint` provides column and sort hints in the API response envelope.

Private context fields (for relationship edges, Procedure D) use
`strawberry.Private[str | None]` and are excluded from `to_dict` automatically.

**2. Register in `type_registry_init.py`**
(`apps/api/src/unifi_api/graphql/type_registry_init.py`), inside
`build_registry()`:

```python
from unifi_api.graphql.types.network.my_resource import MyResourceType

# Inside build_registry():
reg.register_tool_type("unifi_list_my_resources", MyResourceType, "list")
reg.register_tool_type("unifi_get_my_resource_details", MyResourceType, "detail")
```

`kind` values: `"list"` (multi-item), `"detail"` (single item),
`"timeseries"`, `"event_log"`.

**EXEMPT_PRODUCTS gotcha**: `EXEMPT_PRODUCTS` in
`apps/api/tests/graphql/test_graphql_coverage.py` is permanently `set()`.
Every registered read tool must have a corresponding GraphQL Query field.
There is no exemption path — adding a tool to `type_registry_init.py` without
wiring a Query field immediately fails `test_graphql_coverage`.

## C — Write a Resolver with N+1 Protection

Every resolver must route through `ctx.cache.get_or_fetch()` so concurrent
fields in the same request share a single manager round-trip.

**Pattern: private fetch helper + Query field**

```python
# apps/api/src/unifi_api/graphql/resolvers/<product>.py

import strawberry
from strawberry.types import Info
from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.network.my_resource import MyResourceType


async def _fetch_my_resources(
    ctx: GraphQLContext, controller: str, site: str
) -> list:
    key = f"network/my-resources/{controller}/{site}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session, controller, "network", "my_resource_manager",
            )
            return list(await mgr.get_my_resources())

    return await ctx.cache.get_or_fetch(key, _do)


@strawberry.type
class NetworkQuery:
    @strawberry.field(permission_classes=[IsRead])
    async def list_my_resources(
        self,
        info: Info[GraphQLContext, None],
        controller_id: str,
        site: str = "default",
    ) -> list[MyResourceType]:
        raw = await _fetch_my_resources(info.context, controller_id, site)
        return [MyResourceType.from_manager_output(r) for r in raw]
```

The cache key must be unique per (resource, controller, site). Concurrent
resolvers requesting the same key share a single in-flight `asyncio.Future`
(implemented in `RequestCache` at
`apps/api/src/unifi_api/graphql/context.py`). Never call a manager directly
from a resolver without going through `ctx.cache`.

## D — Wire Relationship Edges

When a type field resolves to another type (e.g., `Network.clients`), carry
`_controller_id` and `_site` as `strawberry.Private` fields on the parent type:

```python
@strawberry.type(description="A UniFi LAN/VLAN network configuration.")
class Network:
    id: strawberry.ID | None
    name: str | None

    # Private context — NOT in SDL, NOT in to_dict()
    _controller_id: strawberry.Private[str | None] = None
    _site: strawberry.Private[str | None] = None

    @strawberry.field(description="Clients on this network.")
    async def clients(self, info: Info) -> list[Client]:
        from unifi_api.graphql.resolvers.network import _fetch_clients
        if not self._controller_id:
            return []
        site = self._site or "default"
        raw_clients = await _fetch_clients(
            info.context, self._controller_id, site
        )
        return [Client.from_manager_output(c) for c in raw_clients
                if _get_network_id(c) == self.id]
```

Set `_controller_id` and `_site` in `from_manager_output` or after
construction in the parent resolver. Both sides of the edge must use
`ctx.cache.get_or_fetch` — the child fetch returns immediately from cache.
The `test_n1_regression.py` depth assertion catches any regression where an
edge triggers a fresh manager round-trip.

## E — Regenerate SDL and Docs

After any type addition or modification, regenerate both artifact files:

```bash
cd apps/api
uv run --package unifi-api-server python -m unifi_api.graphql.docgen
```

This writes:

- `apps/api/src/unifi_api/graphql/schema.graphql` — SDL artifact checked by
  `test_sdl_drift`
- `apps/api/docs/graphql-reference.md` — human-readable reference checked by
  `test_docs_drift`

Both files must be committed in the same PR that adds the type. There is no
deferred-commit grace period — a stale `schema.graphql` or
`graphql-reference.md` immediately fails two CI gates.

## F — 6 CI Gates (All Permanent)

All 6 gates run on every PR touching `apps/api/`. Run locally before pushing:

```bash
cd apps/api
uv run --package unifi-api-server pytest tests/graphql/ -v
```

| Gate | Test file | What it enforces |
|------|-----------|------------------|
| Coverage parity | `test_graphql_coverage.py` | Every manifest read tool maps to a GraphQL Query field; `EXEMPT_PRODUCTS = set()` |
| SDL drift | `test_sdl_drift.py` | `schema.graphql` matches live `str(schema)` — regenerate with docgen |
| Docs drift | `test_docs_drift.py` | `graphql-reference.md` matches docgen render |
| N+1 regression | `test_n1_regression.py` | `RequestCache` dedupe depth ≤ 1 per request |
| Naming convention | `test_naming_convention.py` | Tool-to-field path via `_naming.tool_to_field_path`; no collisions |
| Versioning policy | `test_versioning_policy.py` | Fields removed from SDL were `@strawberry.deprecated(...)` in the prior artifact |

**Common failure modes:**

- *SSE-coupling trap* — Protect resolver files also contain SSE event
  handlers. Editing a Protect type without checking both the resolver and the
  SSE handler risks a silent type mismatch at event dispatch time.
- *Deprecation two-PR rule* — To remove a field: PR1 adds
  `@strawberry.deprecated(reason="...")`, PR2 removes the field. Removing
  in one PR fails `test_versioning_policy`.
- *tool_name mismatch* — `register_tool_type("unifi_list_foo", ...)` must
  exactly match the `name=` on the corresponding `@mcp.tool` decorator. A
  typo passes `test_graphql_coverage` only if the tool name also appears in
  the manifest — the gate checks manifest membership, not string equality.

---

## Cross-Cutting Gotchas

**Registration placement** — New registrations belong in
`type_registry_init.py`'s `build_registry()` function, not in the type file
or in `type_registry.py`. `TypeRegistry` in `type_registry.py` is a data
structure; `type_registry_init.py` is its population layer.

**Scaffold field mapping** — The scaffold generates a generic
`from_manager_output` skeleton. Always audit it against the actual manager
output dict — field names in raw dicts often differ from SDL names
(e.g., `"_id"` → `id`, `"ip_subnet"` → `subnet`).

**Mutation tools excluded** — `type_registry_init.py` registers read tools
only. Mutation tools use `serializer_registry` on the REST `/v1/actions/{tool}`
endpoint. Do not register mutation tools in `type_registry_init.py`.
