---
name: myco:extend-unifi-api
description: >-
  Apply this skill when implementing a new UniFi resource type end-to-end across all layers —
  manager class, tool layer, domain models, tests, API REST/GraphQL exposure, and action
  dispatcher integration. Covers: manager CRUD with 405 workarounds, V2 API response
  normalization, domain Pydantic models and field validation, tool modules with preview/confirm
  flow, typed action input models for non-CRUD operations, test suites at both layers, manifest
  generation, Strawberry GraphQL type registration,
  cursor-based pagination for list endpoints, render-hint conventions, HTTP error contracts
  (409 for capability mismatch), ManagerFactory multi-controller concurrency, the multi-surface
  Phase 8 CI gate, field-symmetry migration procedure, update tool fetch-merge-put pattern,
  mutation tool registration, and DISPATCH_ARG_TRANSLATORS action dispatcher wiring. Activates
  for any task that introduces new resource support across the manager/tool/API boundary.
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

**File:** `packages/unifi-core/src/unifi_core/<server>/managers/{resource}_manager.py`

Reference `packages/unifi-core/src/unifi_core/network/managers/dns_manager.py` as the golden pattern. Key naming conventions: method names use the full resource name (e.g., `list_dns_records`, `get_dns_record`, `create_dns_record`). The class constructor takes a `ConnectionManager` directly — not a raw HTTP client. The `@lru_cache` factory function lives in the app's `runtime` module and takes no arguments:

```python
from functools import lru_cache
from unifi_core.network.managers.dns_manager import DnsManager

@lru_cache
def get_dns_manager() -> DnsManager:
    return DnsManager(get_connection_manager())
```

### Step 2 — Check for 405 Endpoints and V2 Response Shapes

**2A: 405 resources (DNS, AP groups, ACL rules, filtering rules)** implement `get_{resource}` via list-and-filter rather than a direct GET-by-ID HTTP call:
```python
async def get_dns_record(self, record_id: str) -> dict:
    records = await self.list_dns_records()
    for record in records:
        if record.get("_id") == record_id:
            return record
    raise UniFiNotFoundError(...)
```

**2B: V2 single-resource responses may be wrapped in lists.** Always check `isinstance(response, list)` BEFORE `isinstance(response, dict)`:
```python
response = await self._connection.request(api_request)
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
             inputSchema={"type": "object", "properties": {"record_id": {"type": "string"}, **_mutable},
                          "required": ["record_id"], "additionalProperties": False},
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

### Step 5-7 — Tests and Manifest Generation

1. Write `test_{resource}_manager.py` and `test_{resource}_tools.py` with live output in PR.
2. Run `make generate` to update manifest. Commit the output.

### Step 8 — Register Action Dispatcher (API-Layer)

**File:** `apps/api/src/unifi_api/services/dispatch_overrides.py`

**Action translators** (arm, disarm, toggle — no nested `rule_data`):
```python
from unifi_core.protect.models._actions import AlarmArmInput
DISPATCH_ARG_TRANSLATORS = {
    "protect_alarm_arm": lambda args, ctx: AlarmArmInput(**args).model_dump(),
}
```

**Update translators** (tools that pass a nested `rule_data: dict`) follow the `_translate_acl_update` pattern. The critical requirement is to **reject** unknown fields rather than silently filter, then run `validate_update_fields()` on the full nested dict:

```python
# Pattern from _translate_acl_update — adapt per resource
rule_data = args.get("rule_data") or {}
unknown = set(rule_data) - MUTABLE_FIELDS
if unknown:
    raise ValueError(f"Unknown or read-only fields: {sorted(unknown)}. Allowed: {sorted(MUTABLE_FIELDS)}")
ok, err = validate_update_fields(rule_data)
if not ok:
    raise ValueError(err)
```

Reference: `_translate_acl_update` in `apps/api/src/unifi_api/services/dispatch_overrides.py` for the full canonical implementation (includes `CLEAR_NETMASK_FIELDS` handling and no-op guard).

Only tools whose arg shapes need reshaping or validation need a translator. Simple CRUD tools that don't use a nested `rule_data` dict do not.

---

## Part 2: API Layer (apps/api/)

### Procedure A: Multi-Surface Phase 8 Requirement

All surfaces must be complete:
1. Strawberry GraphQL type
2. GraphQL Query field
3. REST resource route (`GET /v1/sites/{site_id}/{resource}`)
4. Action dispatcher (`POST /v1/actions/unifi_tool_name`)
5. Regenerate reference docs: `uv run --package unifi-api-server python -m unifi_api.graphql.docgen`
6. Commit updated `apps/api/openapi.json`
7. Commit updated `apps/api/docs/graphql-reference.md`

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
```

Register by importing the type into the appropriate `apps/api/src/unifi_api/graphql/types/<server>/` module and wiring it into the Query field. Verify by running `docgen` (step 5 above) and confirming the type appears in `apps/api/docs/graphql-reference.md`.

### Procedure B.5 — Protect List Tools: Two Valid Patterns

Protect list tools have two valid patterns depending on whether the manager returns a
homogeneous list or a variable-shape envelope:

**Pattern 1 — `kind=list` with `_coerce_list_result` normalization** (recognition tools):
Used for `protect_list_known_faces` and `protect_list_known_license_plates`. The API
routes layer (`apps/api/src/unifi_api/routes/actions.py`) automatically calls
`_coerce_list_result()` for any tool with `kind="list"` — unwraps a single-key dict
envelope into a bare list. Do not manually unwrap in the type or tool layer.

**Pattern 2 — `kind=DETAIL` wrapper** (variable-shape resources like alarm rules):
Used for resources that return either a bare list or a `{items, count}` dict depending on
firmware version. The type's `from_manager_output` classmethod accepts both shapes and
normalizes. Document the firmware versions tested.

**Choosing the pattern:** Use Pattern 1 when the manager returns a consistent single-key
envelope. Use Pattern 2 when firmware may return bare list or dict depending on version.

### Procedure C: Mutation Registration

Mutations are wired via `DISPATCH_ARG_TRANSLATORS` in the action dispatcher (Step 8 in Part 1). There is no separate `MutationHandler` base class or `mutation_registry` module in the codebase — do not create one. All write-path tools flow through the existing actions route in `apps/api/src/unifi_api/services/dispatch_overrides.py`.

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

## Part 3: Field-Symmetry Migration

The field-symmetry rule requires every field name exposed by `list_*` output to be accepted under the same name by the matching `create_*`/`update_*` tool. Use this procedure when migrating an existing domain — even if the user doesn't say "field symmetry." Rollout is complete across all three servers (Network, Protect, Access) as of Phase 4.

### Step FS-1 — Audit the Field Gap

Compare the list tool's output schema against every field accepted by create/update:

```bash
grep -n "list_<domain>" apps/network/src/unifi_network_mcp/tools/<domain>.py
```

For each field the list response returns, verify the create/update tool accepts it under the same name. Common gaps:
- List returns flat booleans (`qos_enabled`); create expects nested dicts (`qos: {...}`) → silent drop.
- List returns `schedule_mode`; update accepts no schedule parameter → silent drop.

### Step FS-2 — Model Structure Invariants

`packages/unifi-core/src/unifi_core/<server>/models/<domain>.py`:

```python
class <Domain>Base(BaseModel):
    field_a: Optional[str] = None   # = None ONLY — no non-None defaults here
    field_b: Optional[bool] = None

class Create<Domain>(<Domain>Base):
    name: str                        # required at creation
    create_only_field: str           # e.g., network_id

class Update<Domain>(<Domain>Base):
    pass  # add update-only fields if needed
```

**Blast-radius rule (hard blocker on review):** Non-`None` defaults in `<Domain>Base` or `Update<Domain>` silently overwrite controller state on every update that doesn't specify the field.

| Location | Non-`None` defaults allowed? |
|----------|------------------------------|
| `Create<Domain>` | ✅ Yes — creation only |
| `<Domain>Base` | ❌ No — `= None` only |
| `Update<Domain>` | ❌ No — `= None` only |

### Step FS-3 — Field Validation Helper

Export from the model file (implement per-domain; no shared validator module):

```python
MUTABLE_FIELDS = frozenset({"field_a", "field_b", ...})

def validate_update_fields(fields: dict) -> tuple[bool, str | None]:
    for name, value in fields.items():
        info = <Domain>Base.model_fields.get(name)
        if info is None: continue
        try: TypeAdapter(info.annotation).validate_python(value, strict=True)
        except ValidationError as e: return False, f"Invalid '{name}': {e.errors()[0]['msg']}"
    return True, None
```

Managers filter to mutable fields inline: `{k: v for k, v in data.items() if k in MUTABLE_FIELDS}`.

### Step FS-4 — Cross-Layer Symmetry Test

Register the `(server, domain)` pair in `apps/api/tests/unit/test_cross_layer_symmetry.py` (`REGISTERED_PAIRS`). This gate checks that the Strawberry type at `unifi_api.graphql.types.<server>.<domain>` exposes every `MUTABLE_FIELDS` name with a compatible annotation, catching MCP↔API drift at PR time.

### Field-Symmetry Gotchas

**Flat → nested translation:** List exposes `qos_enabled: bool`; UniFi API expects `{"qos": {"enabled": true}}`. Translation lives in the **manager**, not the model — model stays flat, manager maps to nested shape before the PUT.

**Non-mutable test exceptions are permanent:** Fields like `id`, `created_at`, computed summaries must be documented as exceptions in symmetry tests. Do NOT enforce symmetry for genuinely non-mutable fields.

**Reference files:** `packages/unifi-core/src/unifi_core/network/models/acl.py` (ACL model reference, `MUTABLE_FIELDS` + validation), `packages/unifi-core/src/unifi_core/network/managers/acl_manager.py` (ACL manager, fetch-merge-put without manager-level validator), `AGENTS.md` (governance rule).

---

## Part 4: Update Tool — Fetch-Merge-Put Deep-Dive

All `update_*` tools use the fetch-merge-put pattern. Skipping the fetch step causes silent data loss — the PUT wipes every field not in the payload. Read `packages/unifi-core/src/unifi_core/network/managers/dns_manager.py` as a reference.

### Four-Step Pattern

```python
async def update_dns_record(self, record_id: str, update_data: dict) -> dict:
    # 1. Fetch current state
    current = await self.get_dns_record(record_id)
    if not current: raise ValueError(f"Record {record_id} not found")
    # 2. Deep-copy before mutating (protects cached response)
    import copy; base = copy.deepcopy(current)
    # 3. Merge caller's partial dict over the base
    merged = {**base, **update_data}
    # 4. PUT the fully-merged object
    return await self._connection.put(f"<endpoint>/{record_id}", merged)
```

### deep_merge Semantics

| Value type | Behavior |
|------------|----------|
| `dict` | Merged recursively — sibling keys preserved |
| `scalar` | Replaced — caller's value wins |
| `list` | Replaced entirely — not element-merged |
| `None` | Replaced — cannot distinguish "clear" from "not specified" |

### Update Tool Requirements

**`additionalProperties: false` on every update tool's `inputSchema`** — closes the ArgModelBase silent-drop vulnerability (FastMCP drops extra keys before validation). Set inline on the Tool definition (see Step 4 example above).

**`update_data: dict` param** — LLM UX requirement. Include "pass only fields you want to change; omitted fields are preserved" in the docstring.

**Delta preview, not full merged result:**
```python
if not confirm:
    current = await manager.get_dns_record(resource_id)
    preview = {k: {"before": current.get(k), "after": v} for k, v in update_data.items()}
    return f"Preview (pass confirm=True to apply):\n{json.dumps(preview, indent=2)}"
```
The double-fetch is intentional — ensures preview reflects live controller state, not stale cache.

### Create vs. Update Asymmetry

Update tools use `update_data: dict`. Create tools use flat keyword params. Do not mirror the create tool signature when building the update tool — they solve different problems (full spec vs. delta).

### Regression Test Standard

Every update tool must verify non-passed fields are preserved after the update:
```python
# mock_get returns {"name": "original", "vlan": 10, "notes": "keep me"}
await manager.update_dns_record("id-1", {"name": "new-name"})
payload = mock_put.call_args[1]["json"]
assert payload["vlan"] == 10            # preserved
assert payload["notes"] == "keep me"   # preserved
assert payload["name"] == "new-name"   # updated
```

---

## Naming Conventions

Network/Access: `{package}_{resource}_{verb}` (e.g., `network_dns_record_create`)
Protect: `protect_{noun}_{verb}` (e.g., `protect_alarm_arm`)
Manager class: `{Resource}Manager`. Factory: `get_{resource}_manager` with `@lru_cache`.
Manager methods: `list_{resource}s()`, `get_{resource}(id)`, `create_{resource}(data)`, `update_{resource}(id, updates)`.

---

## Cross-Cutting Gotchas

**Never use `args: dict`** — silently drops named kwargs. Use explicit parameters.

**405 ≠ auth issue** — switch to `list() + filter` immediately.

**V2 list wrapping** — check `isinstance(response, list)` BEFORE dict; list branch first.

**Manifest must be committed** — `make generate` output is not auto-generated in CI.

**Make targets:** `make generate`, `make check-generated`, `make ci` (not `make manifest`).

**Dependency rule:** Never import `unifi-mcp-shared` from `apps/api/` (circular imports).

**Multi-surface mandatory Phase 8+** — incomplete PRs merge-blocked by CI.

**Release tag policy:** No `api/*` tags before Phase 7.

**Silent creation failures:** Controller may return 200 without creating; check required fields.

**Zone endpoint:** Use `/firewall/zone-matrix` not `/firewall/zones` (404).

**forget-client needs array:** `"macs": [mac]` not `"mac": mac`.

**Firewall policy required:** `schedule: {"mode": "ALWAYS"}` and `create_allow_respond: False` on BLOCK/REJECT.

**Firmware variation:** Different versions return different field shapes; request firmware version with bug reports.

**Action dispatcher arg-mismatch:** Without DISPATCH_ARG_TRANSLATORS, action tools fail silently. Test both MCP and `/v1/actions/` paths.

**V2 ObjectID vs. Integration UUID:** ObjectIDs are controller-local; if implementing cross-controller queries, use Integration UUID path instead. Test against multi-controller setups.

**Pass-through test pattern:** For tools that pass raw manager output to API without transformation, validate shape compatibility with Strawberry type expectations via snapshot or schema-compliance tests.

**`_coerce_list_result` for kind=list action tools:** `apps/api/src/unifi_api/routes/actions.py` automatically calls `_coerce_list_result()` for any action tool whose type has `kind="list"`. It unwraps single-key dict envelopes to a bare list; bare lists pass through. If your manager returns a multi-key dict, `_coerce_list_result` will raise — ensure output is a bare list or single-key envelope.

**api-actions phase uses a curated 6-tool sample:** `API_ACTIONS_SAMPLE` in `scripts/live_smoke.py` is hardcoded to 6 tools. New tools are NOT automatically included. Explicitly append to `API_ACTIONS_SAMPLE` to add api-actions smoke coverage.

**Tool description vs. Pydantic Field description:** Keep distinct — do not copy-paste tool description into field descriptions.

**`api_request_raw` required for empty-body Protect DELETE and merge ops:** `client.api_request()` raises when the controller returns an empty response body. Use `client.api_request_raw()` instead. Reference: `packages/unifi-core/src/unifi_core/protect/managers/alarm_manager.py`.

**`AlarmRulesFacade` — version-transparent facade for dual-backend resources:** When a resource spans two API backends, implement a facade that prefers v2 and falls back to legacy on `AlarmManagerPermissionError` or `BadRequest`. Surface the `complete` flag in `_meta`. 5xx/transient errors must NOT be masked. Reference: `packages/unifi-core/src/unifi_core/protect/managers/alarm_facade.py`.

**SuperAdmin prerequisite for OS-level Protect v2 endpoints:** Some endpoints require SuperAdmin on the Protect console. Regular site admins receive `AlarmManagerPermissionError`; `AlarmRulesFacade` falls back silently. Always document this requirement in tool descriptions.

**Separate Network/Protect user databases:** SuperAdmin on the Network controller does NOT automatically mean SuperAdmin on the Protect console. Be explicit about which system the credential requirement applies to.

**Facade migration — audit ALL call sites:** When migrating a service handler to a facade, audit EVERY call site: action dispatcher (`apps/api/src/unifi_api/services/dispatch_overrides.py`), GraphQL query/mutation fields, and any routing table entries. Missing one leaves old code silently routing to the pre-migration target. (Ref: PR #335 alarm facade migration where dispatcher kept routing to legacy `alarm_manager` after the facade was introduced.)

**Cross-package combined pytest run hits conftest collision:** Running `uv run pytest packages/ apps/` causes pytest to load conflicting conftest files from different packages and fail. Run per-package instead: `uv run pytest packages/unifi-core` or `uv run pytest apps/network`.

**Update translators must reject unknown fields — never filter silently:** When a dispatch translator handles a tool that uses a nested `rule_data: dict`, check `set(rule_data) - MUTABLE_FIELDS` and raise `ValueError` on unknown fields. Then run `validate_update_fields(rule_data)` on the full dict before returning. Silent filtering (e.g., `{k: v for k, v in rule_data.items() if k in MUTABLE_FIELDS}`) masks caller errors and hides field-name mismatches. Reference: `_translate_acl_update` in `apps/api/src/unifi_api/services/dispatch_overrides.py`.
