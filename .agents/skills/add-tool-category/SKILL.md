---
name: myco:add-tool-category
description: >-
  Use this skill whenever adding a new UniFi resource type as a supported tool
  category — creating a manager, tool layer, schemas, tests, and wiring
  everything into the manifest and CI. Activates for any PR or task that
  introduces a new manager class (managers/{resource}_manager.py), new tool
  module (tools/{resource}.py), or new UniFi subsystem support, even if the
  user only asks to "add support for X" without specifying each step. Covers:
  manager class with CRUD + lru_cache factory, 405 endpoint workarounds, V2
  API response unwrapping, schema definition and validator registry wiring,
  tool layer with preview/confirm flow and correct ToolAnnotations, test file
  requirements (both layers), manifest regeneration, test_scaffold.py CI
  registration, Protect-package naming conventions, critical endpoint patterns,
  typed action input models for non-CRUD action tools, and
  DISPATCH_ARG_TRANSLATORS API-layer registration for action dispatcher.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Adding a New Tool Category to unifi-mcp

A "tool category" is a new UniFi resource type — DNS records, DHCP leases, alarms, etc. — exposed end-to-end: a manager class that talks to the controller, a schema/validator layer, a tool module that Claude calls, and tests at both layers. Omitting any step silently breaks CI or corrupts data on live controllers.

**Golden-path reference implementation:** `managers/dns_manager.py` + `tools/dns.py` + `test_dns_manager.py` + `test_dns_tools.py` (PR #128).

## Prerequisites

- Understand which UniFi package owns the resource: `unifi-network-mcp` vs. `unifi-protect-mcp` vs. `unifi-access-mcp`. Directory structure and naming conventions differ by package.
- Know whether the resource's GET-by-ID endpoint returns 405 (see Step 2).
- Understand key API endpoint patterns: V2 vs V1, response shape normalization, 405 workarounds, and resource-specific required fields (see Cross-Cutting Gotchas).
- Review `implement-update-tool-fetch-merge-put` skill before writing any update method.
- Have a live controller available for final validation output in the PR description.

## Step 1 — Create the Manager Class

**File:** `apps/{package}/managers/{resource}_manager.py`

```python
from functools import lru_cache
from .base_manager import BaseManager

class DnsManager(BaseManager):
    def list(self) -> list[dict]:
        return self.client.get("/v2/api/site/{site}/dns/record")

    def get_by_id(self, record_id: str) -> dict | None:
        # 405 resources: use list() + filter (see Step 2)
        records = self.list()
        return next((r for r in records if r["_id"] == record_id), None)

    def create(self, data: dict) -> dict:
        return self.client.post("/v2/api/site/{site}/dns/record", data)

    def update(self, record_id: str, updates: dict) -> dict:
        # Always fetch-merge-put — see implement-update-tool-fetch-merge-put skill
        existing = self.get_by_id(record_id)
        merged = {**existing, **updates}
        return self.client.put(f"/v2/api/site/{{site}}/dns/record/{record_id}", merged)

    def delete(self, record_id: str) -> dict:
        return self.client.delete(f"/v2/api/site/{{site}}/dns/record/{record_id}")


@lru_cache(maxsize=None)
def get_dns_manager(client) -> DnsManager:
    return DnsManager(client)
```

Add an alias in `runtime.py` so tools can import via the runtime module:

```python
from .managers.dns_manager import get_dns_manager
```

**Idempotency guards:** For state-dependent operations (arm/disarm, enable/disable) add a pre-flight check that returns a clear message instead of hitting the API when the state is already what the caller requested. This prevents controller 400 errors. Reference: `managers/alarm_manager.py` (PR #133) — `already_armed` / `already_disarmed` guards.

## Step 2 — Check for 405 Endpoints and Normalize V2 Response Shapes

### 2A: 405 Method Not Allowed on GET-by-ID

Some UniFi GET-by-ID endpoints return HTTP 405. **Do NOT call a get-by-ID endpoint for these types.** Instead, use `list()` + filter by `_id`.

Known 405 resources: DNS records, AP groups, content filtering rules, ACL rules.

Pattern for any suspected 405 resource:

```python
def get_by_id(self, resource_id: str) -> dict | None:
    return next(
        (r for r in self.list() if r.get("_id") == resource_id),
        None
    )
```

If you're unsure, test the endpoint directly. If it returns 405, use the list+filter pattern. See `acl_manager.py` and `dns_manager.py` for reference.

### 2B: V2 API Response Shape — List Wrapping on Single-Resource Fetches

V2 endpoints sometimes wrap single-resource responses in a **one-element list**, not a plain dict. This is distinct from the list endpoint behavior. A `get_by_id` method that doesn't handle this will silently return `None` for valid IDs.

```python
# Pattern: check for list first, then dict
response = self.client.get(f"/v2/api/site/{{site}}/resource/{id}")
if isinstance(response, list):
    return response[0] if response else None
return response
```

**Branch order matters:** Always check `isinstance(response, list)` before checking `isinstance(response, dict)`. The list branch must come first, or a future edit might accidentally reintroduce the bug.

Three production bugs shared this root cause: `get_acl_rule_by_id`, `get_client_group_by_id`, and `get_oon_policy_by_id` (fixed in commit `30f6421`).

## Step 3 — Define the Domain Pydantic Model

**File:** `packages/unifi-core/src/unifi_core/<server>/models/<domain>.py`

All field definitions, mutability metadata, and controller translation helpers live here. The model is imported by both the MCP tool layer and the API server — keeping field names in one place.

```python
from pydantic import BaseModel
from typing import Optional, FrozenSet

class DnsRecord(BaseModel):
    # Read-only fields (controller-assigned)
    id: Optional[str] = None  # json_schema_extra={"mutable": False} marks read-only
    created_at: Optional[str] = None

    # Mutable fields (default mutability)
    record_type: Optional[str] = None
    key: Optional[str] = None
    value: Optional[str] = None
    ttl: Optional[int] = None
    enabled: Optional[bool] = None

    model_config = {"populate_by_name": True}

MUTABLE_FIELDS: FrozenSet[str] = frozenset({
    "record_type", "key", "value", "ttl", "enabled",
})
READ_ONLY_FIELDS: FrozenSet[str] = frozenset({"id", "created_at"})

def from_controller(raw: dict) -> DnsRecord:
    return DnsRecord(**{k: raw.get(k) for k in DnsRecord.model_fields})

def to_controller_create(model: DnsRecord) -> dict:
    return model.model_dump(exclude_none=True, exclude=READ_ONLY_FIELDS)

def to_controller_update(fields: dict) -> dict:
    invalid = set(fields) - MUTABLE_FIELDS
    if invalid:
        raise ValueError(f"Read-only or unknown fields: {invalid}")
    return fields
```

**Anchor:** `packages/unifi-core/src/unifi_core/network/models/acl.py`

In the tool layer:
- Create tools: validate caller args, call `to_controller_create()`, pass result to manager.
- Update tools: call `to_controller_update(fields)` to reject read-only/unknown keys, then pass to manager's fetch-merge-put.
- List/get tools: `from_controller(raw).model_dump()` for normalized output.

## Step 4 — Create the Tool Module

**File:** `apps/{package}/tools/{resource}.py`

Tool `inputSchema` is derived from the pydantic model — no separate JSON schema dicts needed.

```python
from mcp.types import Tool, ToolAnnotations
from ..runtime import get_dns_manager
from unifi_core.network.models.dns_record import DnsRecord, MUTABLE_FIELDS

def get_tools() -> list[Tool]:
    # Derive a mutable-only schema for the update inputSchema
    _mutable_props = {
        k: v for k, v in DnsRecord.model_json_schema()["properties"].items()
        if k in MUTABLE_FIELDS
    }
    return [
        Tool(
            name="network_dns_record_list",
            description="List all DNS records on the UniFi controller.",
            inputSchema={"type": "object", "properties": {}},
            annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
        ),
        Tool(
            name="network_dns_record_create",
            description="Create a new DNS record. Returns a preview; requires confirmation.",
            inputSchema=DnsRecord.model_json_schema(),
            annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False),
        ),
        Tool(
            name="network_dns_record_update",
            description="Update an existing DNS record. Fetches current state and merges.",
            inputSchema={
                "type": "object",
                "properties": {"record_id": {"type": "string"}, **_mutable_props},
                "required": ["record_id"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True),
        ),
        Tool(
            name="network_dns_record_delete",
            description="Delete a DNS record by ID. Irreversible.",
            inputSchema={"type": "object", "properties": {"record_id": {"type": "string"}}, "required": ["record_id"]},
            annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False),
        ),
    ]
```

**ToolAnnotations guide:**
| Operation | destructiveHint | idempotentHint |
|-----------|----------------|----------------|
| read/list | False | True |
| create    | False | False |
| update    | False | True |
| delete    | True  | False |

**Explicit named params — do NOT use `args: dict | None = None`:**

FastMCP maps `tools/call` arguments to Python function parameters by name. Using `args: dict` as a catch-all silently drops all named kwargs. Always use explicit named parameters:

```python
# CORRECT
async def handle_dns_record_create(record_type: str, key: str, value: str, ttl: int = 300) -> str:
    ...

# WRONG — silently drops all arguments
async def handle_dns_record_create(args: dict | None = None) -> str:
    ...
```

**Preview/confirm flow:** All mutating tools (create, update, delete) must present a preview and require explicit confirmation before executing. Follow the established pattern in `tools/dns.py`.

## Step 4.5 — Typed Action Input Models for Non-CRUD Action Tools

If your resource includes action tools (non-CRUD operations like "arm", "disarm", "toggle" state), define typed input models to enable full schema discovery and validation. This pattern is critical for action dispatcher integration (Step 8).

**File:** `packages/unifi-core/src/unifi_core/<server>/models/_actions.py`

Define a Pydantic model class for each action tool's input schema:

```python
from pydantic import BaseModel, Field
from typing import Optional

# Example for an alarm manager with arm/disarm/toggle actions
class AlarmArmInput(BaseModel):
    """Input schema for the alarm_arm action tool."""
    alarm_id: str = Field(..., description="The unique ID of the alarm to arm")
    override_armed_status: Optional[bool] = Field(
        None, description="If true, arm even if already armed"
    )

class AlarmDisarmInput(BaseModel):
    """Input schema for the alarm_disarm action tool."""
    alarm_id: str
    require_confirmation: Optional[bool] = Field(
        None, description="Require user confirmation before disarming"
    )

class AlarmToggleInput(BaseModel):
    """Input schema for the alarm_toggle action tool."""
    alarm_id: str
```

Then, in the tool module, reference these models in the tool's `inputSchema`:

```python
from unifi_core.protect.models._actions import AlarmArmInput

def get_tools() -> list[Tool]:
    return [
        Tool(
            name="protect_alarm_arm",
            description="Arm the alarm system.",
            inputSchema=AlarmArmInput.model_json_schema(),
            annotations=ToolAnnotations(destructiveHint=False),
        ),
        # ... more tools
    ]
```

Action tools with explicit typed models are discoverable by the action dispatcher (Step 8) and participate in schema validation without requiring a Pydantic base model for the resource itself.

## Step 5 — Write Tests for Both Layers

Both test files are required. PRs missing either are blocked at review.

**Manager tests:** `apps/{package}/tests/test_{resource}_manager.py`

Test CRUD against a mocked client. Include edge cases: resource not found, 405 fallback behavior, idempotency guard (returns early message, does not call API).

**Tool tests:** `apps/{package}/tests/test_{resource}_tools.py`

Test the full tool invocation path: schema validation, preview rendering, confirmation flow, and error handling. Use `pytest` fixtures matching the project pattern.

**PR description requirement:** Include live-controller output (tool response from a real controller) as a permanent evidence record. Screenshots or copy-pasted terminal output both acceptable.

## Step 6 — Register in test_scaffold.py

**This step is easy to miss and causes CI failure.**

Your package has a `test_scaffold.py` that maintains a hardcoded list of registered tool categories. Adding a new category without registering it here causes the scaffold test to fail with a confusing error unrelated to your new code.

**File:** `apps/{package}/tests/test_scaffold.py` (where {package} is the resource package: network, protect, or access)

Find the category list and add your new category:

```python
REGISTERED_CATEGORIES = [
    "firewall",
    "dns",        # ← add your new category here
    "dhcp",
    # ...
]
```

The registration string must match the key used in `CATEGORY_MAP` (see Step 7). Discovered as missing from the established golden path during PR #133 (AlarmManager CI failure).

## Step 7 — Regenerate the Manifest

```bash
make generate
```

This regenerates the manifest and validates your new category against CI gates. The build output includes:

1. Tool count summary — verify your new tools are included.
2. Validator registry check — ensures all Pydantic models register correctly.
3. Category membership — confirms your new manager is discoverable.

After running:

1. Verify your new category appears in the manifest header.
2. Confirm the tool count in the manifest header incremented by the number of tools you added.
3. Commit the updated manifest files along with the rest of your changes.

**Do this before opening the PR.** A stale manifest causes tool-count assertion failures in CI.

For build/check cycles, use `make check-generated` to validate without regenerating, and `make ci` to run the full pre-commit gate locally.

## Step 8 — Register in Action Dispatcher (API-Layer Only)

If your new category includes action tools (non-CRUD operations like arm, disarm, toggle) **and** the unifi-api layer needs to support those tools, register a `DISPATCH_ARG_TRANSLATORS` entry in the action dispatcher service.

**File:** `apps/api/src/unifi_api/services/dispatch_overrides.py`

```python
from unifi_core.protect.models._actions import AlarmArmInput, AlarmDisarmInput
from unifi_core.protect.managers.alarm_manager import get_alarm_manager

DISPATCH_ARG_TRANSLATORS = {
    # ... existing entries
    "protect_alarm_arm": lambda args, ctx: AlarmArmInput(**args).model_dump(),
    "protect_alarm_disarm": lambda args, ctx: AlarmDisarmInput(**args).model_dump(),
}
```

This registration allows the `/v1/actions/` endpoint to validate and translate caller arguments before passing them to the tool handler. Without this registration, action tools via `/v1/actions/` will fail with a silent arg-shape mismatch (TypeError) that unit tests do not catch.

**Scope:** Only action tools (arm, disarm, toggle, etc.) need `DISPATCH_ARG_TRANSLATORS` entries. CRUD tools (create, read, update, delete) do not use the action dispatcher.

**Reference:** `apps/api/src/unifi_api/services/dispatch_overrides.py` and `extend-unifi-api` skill, Procedure C.

## Naming Conventions

**Network/Access packages:** `{package}_{resource}_{verb}` — e.g., `network_dns_record_create`, `network_firewall_rule_delete`.

**Protect package:** `protect_{noun}_{verb}` — the noun identifies the managed subsystem. Examples: `protect_alarm_arm`, `protect_alarm_disarm`, `protect_alarm_list`, `protect_alarm_profiles`. Canonical reference: `managers/alarm_manager.py` (PR #133).

Manager class: `{Resource}Manager` (PascalCase). Factory function: `get_{resource}_manager` with `@lru_cache(maxsize=None)`.

## Cross-Cutting Gotchas

**`args: dict` parameter pattern** — silently drops all named kwargs in FastMCP. Always use explicit named parameters in tool handlers.

**`test_scaffold.py` registration** — absent from most verbal golden-path descriptions but mandatory. Causes CI failure if skipped.

**405 is not a permissions or ID problem** — On a `GET /{resource}/{id}` call, a 405 means the endpoint doesn't support the operation at all. Don't debug auth headers or ID formatting — switch to `list() + filter` immediately.

**V2 list wrapping on single-resource fetches** — V2 responses can return a list even for single-object fetches. Always check `isinstance(response, list)` before returning from `get_by_id`. The list branch must come before the dict branch.

**Manifest must be committed** — `make generate` output is not auto-generated in CI. The regenerated manifest files must be in the PR commit.

**Make target restructure** — The build toolchain now uses `make generate` (replaces `make manifest`), `make check-generated` for validation-only runs, and `make ci` for full pre-commit gate execution. Update any scripts or automation that reference the old `make manifest` target.

**Silent creation failures exist** — The controller sometimes returns 200 on a malformed POST without creating the resource. Check for missing required fields before looking for a network or auth issue.

**Zone-matrix endpoint aliasing** — `/firewall/zones` returns 404; use `/firewall/zone-matrix` instead. This is the correct endpoint for firewall zone policy matrices.

**Forget-client requires `macs` array** — the `forget-sta` endpoint requires `"macs": [mac_address]`, not `"mac": mac_address`. Always pass an array even for single clients.

**Firewall policy required fields** — zone-based firewall policies require `schedule: {"mode": "ALWAYS"}` on all policies (even ALLOW), and `create_allow_respond: False` on BLOCK/REJECT policies. Omitting these causes silent non-creation or controller errors.

**Firmware-version field variation** — Some response fields behave differently across firmware versions. If a bug report describes unexpected field values and the reporter is on a specific firmware version, treat firmware variation as a likely cause before assuming a code bug. Request the firmware version string and a sample of the affected response payload for diagnosis.

**Action dispatcher arg-shape mismatch** — Without a registered `DISPATCH_ARG_TRANSLATORS` entry, action tools invoked via `/v1/actions/` fail silently with TypeError when the LLM produces argument names that don't match the API caller's expectation. Always test action tools both via MCP and via the `/v1/actions/` endpoint (if applicable) before merging. Live smoke testing catches this failure class when unit tests miss it.
