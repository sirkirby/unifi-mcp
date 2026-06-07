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
- **V2 API identifier hazard:** Understand the difference between UniFi V2 ObjectID (`_id`) and Integration UUID semantics before implementing cross-controller queries.

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

### Step 2.5 — V2 API Identifier Hazard: ObjectID vs. Integration UUID

**Critical:** UniFi V2 API returns two identifier types that are NOT interchangeable:

| Identifier | Source | Use case | Example |
|---|---|---|---|
| `_id` (ObjectID) | V2 API `GET /api/site/{site}/devices` response | Local CRUD within a site/controller | "605d...7f3a" |
| Integration UUID | External system mappings, cross-controller queries | Multi-controller operations, relay protocol | "12345678-uuid-format" |

**Hazard:** If you extract an `_id` from a V2 response and send it to a different controller as a GET parameter, it will fail silently (404 or empty result) because the ObjectID is local to that controller's database. Always document which identifier type your tool accepts. If you need cross-controller queries, you must use the Integration UUID path, not the ObjectID path.

**Example gotcha:** Alarm rule IDs from Protect — `rule._id` is the controller-local ObjectID; if you're implementing a cross-controller alarm view, you need the Integration UUID instead. Check the API docs and test against multi-controller setups.

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
6. Run `apps/api/src/unifi_api/graphql/docgen.py` to generate GraphQL reference docs
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

### Procedure B.5 — Protect List Tools: Two Valid Patterns

Protect list tools have two valid patterns depending on whether the manager returns a
homogeneous list or a variable-shape envelope:

**Pattern 1 — `kind=list` with `_coerce_list_result` normalization** (recognition tools):
Used for `protect_list_known_faces` and `protect_list_known_license_plates`. These tools
return a single-key dict envelope (e.g., `{"items": [...]}`) from the manager. The API
routes layer (`apps/api/src/unifi_api/routes/actions.py`) automatically calls
`_coerce_list_result()` for any tool with `kind="list"` — it unwraps a single-key dict
into a bare list. Implement these tools as standard `kind=list` types; do not manually
unwrap the envelope in the type or tool layer.

**Pattern 2 — `kind=DETAIL` wrapper** (alarm rules and other variable-shape resources):
Used for resources that return either a bare list or a `{items, count}` dict depending on
firmware version. The API type's `from_manager_output` accepts both shapes and normalizes:
```python
@strawberry.type
class AlarmRuleListType(UniFiType):
    kind: str = "DETAIL"
    # fields...
    @classmethod
    def from_manager_output(cls, raw):
        if isinstance(raw, list):
            data = raw[0] if raw else {}
        else:
            data = raw  # {items: [...], count: N}
        return cls(...)
```

**Choosing the pattern:** Use `kind=list` + `_coerce_list_result` when the manager returns
a consistent single-key envelope. Use `kind=DETAIL` wrapper when the firmware may return
bare list or dict depending on version. Document the firmware versions tested.

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

**V2 ObjectID vs. Integration UUID:** ObjectIDs are controller-local; if implementing cross-controller queries, use Integration UUID path instead. Test against multi-controller setups.

**Pass-through test pattern:** For tools that pass raw manager output to API without transformation, validate that the shape is compatible with Strawberry type expectations. Use snapshot tests or schema-compliance tests to catch shape drift early.

**`_coerce_list_result` for kind=list action tools:** `apps/api/src/unifi_api/routes/actions.py` automatically calls `_coerce_list_result()` for any action tool whose type has `kind="list"`. It unwraps single-key dict envelopes (e.g., `{"items": [...]}`) to a bare list; bare lists pass through unchanged. Protect recognition tools (`protect_list_known_faces`, `protect_list_known_license_plates`) rely on this. If your new list tool's manager returns a multi-key dict, `_coerce_list_result` will raise — ensure manager output is either a bare list or a single-key envelope dict.

**api-actions phase uses a curated 6-tool sample:** `API_ACTIONS_SAMPLE` in `scripts/live_smoke.py` is hardcoded to 6 tools (network clients/devices, protect cameras/lights, access doors/users). New tools are NOT automatically included in `--phase api-actions` coverage. To add api-actions smoke coverage for a new tool, explicitly append it to `API_ACTIONS_SAMPLE` in `scripts/live_smoke.py`.

**Tool description vs. Pydantic Field description:** Tool `description=` field conveys the tool's purpose to the LLM. Pydantic `Field(description=...)` conveys field semantics. Keep these distinct — do not copy-paste the tool description into field descriptions or vice versa.

**`api_request_raw` required for empty-body Protect DELETE and merge ops:** `client.api_request()` raises when the controller returns an empty response body (e.g., Protect DELETE automations, merge-group). Use `client.api_request_raw()` instead — it skips JSON decoding and returns `None` on empty. This pattern is used in `packages/unifi-core/src/unifi_core/protect/managers/alarm_manager.py` and `packages/unifi-core/src/unifi_core/protect/managers/recognition_manager.py`. When implementing any Protect DELETE or merge endpoint, default to `api_request_raw` unless you have confirmed the controller always returns a non-empty body.

**`AlarmRulesFacade` — version-transparent facade for dual-backend resources:** When a resource spans two API backends (e.g., the v2 OS-level alarm manager and the legacy automations API), implement a facade class that prefers the v2 path and falls back to legacy on `AlarmManagerPermissionError` or `BadRequest`. Surface the `complete` flag in the MCP `_meta` block so callers know whether v2 or legacy served the result. 5xx/transient errors must NOT be masked — propagate them so real v2 outages remain visible. Reference implementation: `packages/unifi-core/src/unifi_core/protect/managers/alarm_facade.py`.

**SuperAdmin prerequisite for OS-level Protect v2 endpoints:** Some Protect endpoints (e.g., the v2 alarm manager at the OS level) require a SuperAdmin credential on the Protect console. A regular site admin receives `AlarmManagerPermissionError`; the `AlarmRulesFacade` silently falls back to legacy in this case. Always document the SuperAdmin requirement in the tool description and model docstring (`packages/unifi-core/src/unifi_core/protect/managers/alarm_manager_service.py` has the reference error class). Test with a SuperAdmin account to verify the v2 code path is reached.

**Separate Network/Protect user databases — SuperAdmin on one ≠ SuperAdmin on the other:** Network and Protect maintain independent user stores. A SuperAdmin account on the UniFi Network controller (`UNIFI_HOST`) does NOT automatically have SuperAdmin on the Protect console (`UNIFI_PROTECT_HOST`). When documenting credential requirements, be explicit: "SuperAdmin on the Protect console" vs. "SuperAdmin on the Network controller." This distinction also affects end-user deployment instructions.
