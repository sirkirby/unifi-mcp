---
name: myco:extend-unifi-api
description: >-
  Apply this skill when implementing a new UniFi resource type end-to-end across all layers —
  manager class, tool layer, domain models, tests, API REST/GraphQL exposure, and action
  dispatcher integration. Covers: manager CRUD with 405 workarounds, V2 API response
  normalization, domain Pydantic models and field validation, tool modules with preview/confirm
  flow, typed action input models for non-CRUD operations, test suites at both layers, manifest
  generation, test_scaffold.py registration, Strawberry GraphQL type registration,
  cursor-based pagination for list endpoints, render-hint conventions, HTTP error contracts
  (409 for capability mismatch), ManagerFactory multi-controller concurrency, the 8-surface
  Phase 8 CI gate, mutation tool registration, and DISPATCH_ARG_TRANSLATORS action dispatcher
  wiring. Activates for any task that introduces new resource support across the manager/tool/API
  boundary.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Implementing New UniFi Resource Types End-to-End

This unified skill covers the complete flow for adding a new UniFi resource type from manager implementation through API exposure. Both manager/tool layer (`apps/{package}/`) and API layer (`apps/api/`) must be implemented together for a complete resource.

## Prerequisites

- Understand which package owns the resource (network, protect, access).
- Know whether the resource's GET-by-ID endpoint returns 405 (Step 2A).
- Have a live controller available for validation output in PR description.
- **Dependency rule:** `apps/api/` may only import from `unifi-core`, never `unifi-mcp-shared`.

---

## Part 1: Manager/Tool Layer (apps/{package}/)

### Step 1 — Create Manager Class

**File:** `apps/{package}/managers/{resource}_manager.py`

```python
from functools import lru_cache
from .base_manager import BaseManager

class DnsManager(BaseManager):
    def list(self): return self.client.get("/v2/api/site/{site}/dns/record")
    def get_by_id(self, id: str) -> dict | None:
        records = self.list()
        return next((r for r in records if r["_id"] == id), None)
    def create(self, data: dict) -> dict: return self.client.post("/v2/api/site/{site}/dns/record", data)
    def update(self, id: str, updates: dict) -> dict:
        existing = self.get_by_id(id)
        return self.client.put(f"/v2/api/site/{{site}}/dns/record/{id}", {**existing, **updates})
    def delete(self, id: str) -> dict: return self.client.delete(f"/v2/api/site/{{site}}/dns/record/{id}")

@lru_cache(maxsize=None)
def get_dns_manager(client) -> DnsManager: return DnsManager(client)
```

### Step 2 — Check for 405 Endpoints and V2 Response Shapes

**2A: 405 resources (DNS, AP groups, ACL rules, filtering rules)** use `list() + filter`:
```python
def get_by_id(self, id: str) -> dict | None:
    return next((r for r in self.list() if r.get("_id") == id), None)
```

**2B: V2 single-resource responses may be wrapped in lists.** Always check `isinstance(response, list)` BEFORE `isinstance(response, dict)`:
```python
response = self.client.get(f"/v2/api/site/{{site}}/resource/{id}")
if isinstance(response, list): return response[0] if response else None
return response
```

### Step 3 — Define Domain Pydantic Model

**File:** `packages/unifi-core/src/unifi_core/<server>/models/<domain>.py`

```python
from pydantic import BaseModel
from typing import Optional, FrozenSet

class DnsRecord(BaseModel):
    id: Optional[str] = None
    record_type: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None
    ttl: Optional[int] = None
    enabled: Optional[bool] = None
    model_config = {"populate_by_name": True}

MUTABLE_FIELDS = frozenset({"record_type", "key", "value", "ttl", "enabled"})
READ_ONLY_FIELDS = frozenset({"id"})

def to_controller_update(fields: dict) -> dict:
    invalid = set(fields) - MUTABLE_FIELDS
    if invalid: raise ValueError(f"Read-only fields: {invalid}")
    return fields
```

### Step 4 — Create Tool Module

**File:** `apps/{package}/tools/{resource}.py`

Use explicit named parameters (never `args: dict`). Derive mutable-only schema for updates:
```python
from mcp.types import Tool, ToolAnnotations
from ..runtime import get_dns_manager
from unifi_core.network.models.dns_record import DnsRecord, MUTABLE_FIELDS

def get_tools() -> list[Tool]:
    _mutable = {k: v for k, v in DnsRecord.model_json_schema()["properties"].items() if k in MUTABLE_FIELDS}
    return [
        Tool(name="network_dns_record_list", description="List DNS records.", 
             inputSchema={"type": "object", "properties": {}},
             annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True)),
        Tool(name="network_dns_record_update", description="Update DNS record.",
             inputSchema={"type": "object", "properties": {"record_id": {"type": "string"}, **_mutable}, "required": ["record_id"]},
             annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True)),
    ]
```

All mutating tools require preview/confirm flow.

### Step 4.5 — Typed Action Input Models for Non-CRUD Actions

**File:** `packages/unifi-core/src/unifi_core/<server>/models/_actions.py`

```python
from pydantic import BaseModel, Field
from typing import Optional

class AlarmArmInput(BaseModel):
    alarm_id: str = Field(..., description="Alarm ID to arm")
    override: Optional[bool] = None
```

### Step 5-7 — Tests, test_scaffold.py, Manifest Generation

1. Write `test_{resource}_manager.py` and `test_{resource}_tools.py` with live output in PR.
2. Register in `test_scaffold.py` REGISTERED_CATEGORIES.
3. Run `make generate` to update manifest. Commit the output.

### Step 8 — Register Action Dispatcher (API-Layer)

**File:** `apps/api/src/unifi_api/services/dispatch_overrides.py`

```python
from unifi_core.protect.models._actions import AlarmArmInput
DISPATCH_ARG_TRANSLATORS = {
    "protect_alarm_arm": lambda args, ctx: AlarmArmInput(**args).model_dump(),
}
```

Only action tools (arm, disarm, toggle) need this. CRUD tools do not.

---

## Part 2: API Layer (apps/api/)

### Procedure A: 8-Surface Phase 8 Requirement

All 8 must be complete:
1. Strawberry GraphQL type
2. GraphQL Query field
3. REST resource route (`GET /v1/sites/{site_id}/{resource}`)
4. Action dispatcher (`POST /v1/actions/unifi_tool_name`)
5. Fixture e2e test in `apps/api/tests/fixtures/`
6. Run `scripts/codegen_api_docs.py`
7. Commit updated `openapi.json`
8. Commit updated `graphql-reference.md`

Incomplete PRs are merge-blocked by CI.

### Procedure B: Strawberry Types

**File:** `apps/api/src/unifi_api/types/<domain>/<resource>.py`

```python
import strawberry
from typing import Optional
from unifi_api.types._base import UniFiType

@strawberry.type
class Client(UniFiType):
    kind: str = "LIST"  # required
    mac: str
    hostname: Optional[str]
    @classmethod
    def from_manager_object(cls, obj):
        return cls(mac=obj.raw.get("mac"), hostname=obj.raw.get("hostname"))
```

Register in `apps/api/src/unifi_api/types/__init__.py`:
```python
from unifi_api.types._base import type_registry
type_registry.register_tool_type("unifi_list_clients", Client)
```

### Procedure C: Mutation Registration

**File:** `apps/api/src/unifi_api/mutations/network/firewall.py`

```python
from unifi_api.mutations._base import MutationHandler, mutation_registry

class FirewallPolicyCreateHandler(MutationHandler):
    async def execute(self, request_data: dict, controller_id: str, site_id: str):
        manager = await self.get_manager(controller_id, "network", "firewall_policy_manager")
        return await manager.create_policy(**request_data)

mutation_registry.register_mutation("unifi_create_firewall_policy", FirewallPolicyCreateHandler())
```

### Procedure D: Cursor-Based Pagination

Use module-level `paginate()` function, not offset-based:

```python
from unifi_api.services.pagination import Cursor, paginate

cursor = Cursor.decode(cursor_param) if cursor_param else None
items = await manager.get_clients()
page, next_cursor = paginate(items, limit=50, cursor=cursor, 
                            key_fn=lambda i: (i.raw.get("last_seen", 0), i.raw.get("_id", "")))
return {"items": [...], "next_cursor": next_cursor.encode() if next_cursor else None}
```

### Procedure E: Render Hints

Every type has `kind` (LIST/DETAIL/DIFF/TIMESERIES/EVENT_LOG/EMPTY/STREAM). Optional: `primary_key`, `display_columns`, `sort_default`.

### Procedure F: Resource vs. Action Error Contracts

**Resource endpoints** (`GET /v1/sites/{id}/{resource}`): Use HTTP status codes. 409 Conflict for capability mismatch.

**Action endpoints** (`POST /v1/actions/{tool}`): Always 200; errors in envelope.

### Procedure G: ManagerFactory for Multi-Controller

Access via `request.app.state.manager_factory`:
```python
factory: ManagerFactory = request.app.state.manager_factory
cm = await factory.get_connection_manager(session, controller_id, "network")
mgr = await factory.get_domain_manager(session, controller_id, "network", "client_manager")
```

Uses `asyncio.Lock` per controller to prevent concurrent cache-miss races. Call `await factory.invalidate_controller(controller_id)` on delete/credential update.

### Procedure H: Mutation Preview and deepcopy

Use `copy.deepcopy()` to preserve sibling fields during merge:
```python
import copy
current = await self.get_firewall_rule(rule_id)
merged = copy.deepcopy(current.raw)
merged.update(updates)
result = await self._api.put(f"/rest/firewall/rule/{rule_id}", json=merged)
```

---

## Naming Conventions

Network/Access: `{package}_{resource}_{verb}` (e.g., `network_dns_record_create`)
Protect: `protect_{noun}_{verb}` (e.g., `protect_alarm_arm`)
Manager class: `{Resource}Manager`. Factory: `get_{resource}_manager` with `@lru_cache(maxsize=None)`.

---

## Cross-Cutting Gotchas

**Never use `args: dict`** — silently drops named kwargs. Use explicit parameters.

**test_scaffold.py registration required** — missing registration causes CI failure (not related to your code).

**405 ≠ auth issue** — switch to `list() + filter` immediately.

**V2 list wrapping** — check `isinstance(response, list)` BEFORE dict; list branch first.

**Manifest must be committed** — `make generate` output is not auto-generated in CI.

**Make targets:** `make generate`, `make check-generated`, `make ci` (not `make manifest`).

**Dependency rule:** Never import `unifi-mcp-shared` from `apps/api/` (circular imports).

**8-surface mandatory Phase 8+** — incomplete PRs merge-blocked by CI.

**Mutation registry controls write exposure** — unregistered mutations won't be callable via API.

**Release tag policy:** No `api/*` tags before Phase 7.

**Silent creation failures:** Controller may return 200 without creating; check required fields.

**Zone endpoint:** Use `/firewall/zone-matrix` not `/firewall/zones` (404).

**forget-client needs array:** `"macs": [mac]` not `"mac": mac`.

**Firewall policy required:** `schedule: {"mode": "ALWAYS"}` and `create_allow_respond: False` on BLOCK/REJECT.

**Firmware variation:** Different versions return different field shapes; request firmware version with bug reports.

**Action dispatcher arg-mismatch:** Without DISPATCH_ARG_TRANSLATORS, action tools fail silently. Test both MCP and `/v1/actions/` paths.
