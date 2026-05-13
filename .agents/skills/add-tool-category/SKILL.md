---
name: myco:add-tool-category
description: >
  Use this skill whenever adding a new UniFi resource type as a supported tool category
  — creating a manager, tool layer, schemas, tests, and wiring everything into the
  manifest and CI. Activates for any PR or task that introduces a new manager class
  (managers/{resource}_manager.py), new tool module (tools/{resource}.py), or new
  UniFi subsystem support, even if the user only asks to "add support for X" without
  specifying each step. Covers: manager class with CRUD + lru_cache factory, 405
  endpoint workarounds, schema definition and validator registry wiring, tool layer
  with preview/confirm flow and correct ToolAnnotations, test file requirements (both
  layers), V2 API response unwrapping, manifest regeneration, test_scaffold.py CI
  registration, and Protect-package naming conventions.
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
- Understand `UniFiValidatorRegistry.validate()` usage patterns (covered in Step 3).

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

## Step 3 — Define Schemas and Register the Validator

**File:** `apps/{package}/schemas.py`

```python
DNS_RECORD_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "record_type": {"type": "string", "enum": ["A", "AAAA", "CNAME", "MX", "TXT"]},
        "key": {"type": "string"},
        "value": {"type": "string"},
        "ttl": {"type": "integer", "minimum": 0},
        "enabled": {"type": "boolean"},
    },
    "required": ["record_type", "key", "value"],
}

DNS_RECORD_UPDATE_SCHEMA = {
    "type": "object",
    "properties": {
        # Same fields, all optional for partial updates
        "record_type": {"type": "string"},
        "key": {"type": "string"},
        "value": {"type": "string"},
        "ttl": {"type": "integer", "minimum": 0},
        "enabled": {"type": "boolean"},
    },
    "minProperties": 1,
}
```

**File:** `apps/{package}/validator_registry.py` — register both schemas:

```python
from .schemas import DNS_RECORD_CREATE_SCHEMA, DNS_RECORD_UPDATE_SCHEMA

class UniFiValidatorRegistry:
    def __init__(self):
        self._validators = {
            # ... existing entries ...
            "dns_record_create": DNS_RECORD_CREATE_SCHEMA,
            "dns_record_update": DNS_RECORD_UPDATE_SCHEMA,
        }
```

### Validator Registry Usage Pattern

The `UniFiValidatorRegistry` provides schema validation and normalization for UniFi controller parameters. The key insight is that `registry.validate()` returns a coerced, normalized dict — not a boolean — and using the original parameters bypasses this normalization silently.

#### Procedure A: Implement Validation Pattern

The core validation pattern has 4 steps:

```python
# 1. Call registry.validate() on raw input params
validated_data = self.registry.validate(tool_name, params)

# 2. The returned dict is coerced/normalized — capture it as validated_data
# (validated_data may differ from params due to type coercion, defaults, etc.)

# 3. Pass validated_data to API layer — NOT the original params
response = await self.api_client.update_device(validated_data)

# 4. Validation errors are raised automatically before this point
```

**Critical gotcha:** `registry.validate()` does NOT return `True`/`False`. It returns a dict. Using `params` after validation bypasses normalization entirely.

**Verification heuristic:** After the `.validate()` call, scan for any downstream reference to `params`. If `params` appears in API calls after step 1, the bug is present.

#### Procedure B: Handle Validation Errors

Validation errors surface automatically, but you may want to add context:

```python
try:
    validated_data = self.registry.validate("update_device", params)
    response = await self.api_client.update_device(validated_data)
    return response
except ValidationError as e:
    # Add tool-specific context if helpful
    raise ValueError(f"Invalid device update parameters: {e}")
```

The registry will raise detailed validation errors before any API call is made.

#### Procedure C: Debug Normalization Differences

If you suspect normalization is changing your data unexpectedly:

```python
# Log the difference between input and normalized output
validated_data = self.registry.validate(tool_name, params)
if validated_data != params:
    logger.debug(f"Validation normalized: {params} -> {validated_data}")

# Continue with validated_data
response = await self.api_client.call_endpoint(validated_data)
```

Common normalizations:
- String IDs converted to appropriate types
- Missing optional fields filled with defaults
- Enum values standardized to expected case

**Critical — always capture `validated_data`:**

```python
# CORRECT
validated_data = registry.validate("dns_record_create", raw_args)
manager.create(validated_data)

# WRONG — silent data corruption, recurring error in PRs #123 and #126
registry.validate("dns_record_create", raw_args)
manager.create(raw_args)   # ← uses unvalidated original dict
```

The return value of `registry.validate()` is the coerced, validated dict. Discarding it and using the raw input bypasses all schema enforcement.

**Tool name matching:** The `tool_name` passed to `.validate()` must exactly match the registered schema name in `validator_registry.py`.

**ResourceValidator Blast Radius — NEVER Add Schema Defaults:**

Schema defaults in `UniFiValidatorRegistry` create a blast radius across all tools. If a shared validator injects defaults, update tools that intentionally omit fields will overwrite existing data with those defaults, causing silent data loss. This affects 37+ properties across all three app packages.

```python
# NEVER DO THIS in shared schemas registered with UniFiValidatorRegistry
BAD_SCHEMA = {
    "type": "object",
    "properties": {
        "enabled": {"type": "boolean", "default": True},  # ← FORBIDDEN - blast radius
        "priority": {"type": "integer", "default": 1},    # ← FORBIDDEN - blast radius
    }
}

# Instead, handle defaults in tool-specific logic
def create_firewall_rule(enabled: bool = True, priority: int = 1, ...):
    data = {"enabled": enabled, "priority": priority, ...}
    validated_data = registry.validate("firewall_rule_create", data)
```

This constraint affects 37+ properties across all three app packages (network, protect, access). Discovered during PR #146 review when a schema default silently overwrote existing firewall rule data.

**Impact scope:** The shared `ResourceValidator.validate()` method is called by update tools in all manager classes. Any schema defaults would apply to every update operation across the entire project, not just the specific tool that needs the default.

## Step 4 — Create the Tool Module

**File:** `apps/{package}/tools/{resource}.py`

```python
from mcp.types import Tool, ToolAnnotations
from ..runtime import get_dns_manager

def get_tools() -> list[Tool]:
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
            inputSchema=DNS_RECORD_CREATE_SCHEMA,
            annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False),
        ),
        Tool(
            name="network_dns_record_update",
            description="Update an existing DNS record. Fetches current state and merges.",
            inputSchema={**DNS_RECORD_UPDATE_SCHEMA, "required": ["record_id"]},
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
make manifest
```

This regenerates `CATEGORY_MAP` and `TOOL_MODULE_MAP` entries. After running:

1. Verify your new category appears in the manifest header.
2. Confirm the tool count in the manifest header incremented by the number of tools you added.
3. Commit the updated manifest along with the rest of your changes.

**Do this before opening the PR.** A stale manifest causes tool-count assertion failures in CI.

## Naming Conventions

**Network/Access packages:** `{package}_{resource}_{verb}` — e.g., `network_dns_record_create`, `network_firewall_rule_delete`.

**Protect package:** `protect_{noun}_{verb}` — the noun identifies the managed subsystem. Examples: `protect_alarm_arm`, `protect_alarm_disarm`, `protect_alarm_list`, `protect_alarm_profiles`. Canonical reference: `managers/alarm_manager.py` (PR #133).

Manager class: `{Resource}Manager` (PascalCase). Factory function: `get_{resource}_manager` with `@lru_cache(maxsize=None)`.

## Cross-Cutting Gotchas

**`validated_data` capture** — the most common community contributor error (PRs #123, #126). `registry.validate()` returns the validated dict. Always assign and use that return value; never pass the raw input dict downstream. **Review gate:** This pattern is now a formal requirement in community PR reviews. Any tool using `UniFiValidatorRegistry` must follow the 4-step validation pattern.

**Silent failure mode** — Using original `params` instead of `validated_data` produces no Python error but sends unnormalized data to the UniFi controller. Two community contributors (PRs #123, #126) made this identical mistake.

**`args: dict` parameter pattern** — silently drops all named kwargs in FastMCP. Always use explicit named parameters in tool handlers.

**`test_scaffold.py` registration** — absent from most verbal golden-path descriptions but mandatory. Causes CI failure if skipped.

**405 is not a permissions or ID problem** — On a `GET /{resource}/{id}` call, a 405 means the endpoint doesn't support the operation at all. Don't debug auth headers or ID formatting — switch to `list() + filter` immediately.

**V2 list wrapping on single-resource fetches** — V2 responses can return a list even for single-object fetches. Always check `isinstance(response, list)` before returning from `get_by_id`. The list branch must come before the dict branch.

**Manifest must be committed** — `make manifest` output is not auto-generated in CI. The regenerated manifest file must be in the PR commit.

**Silent creation failures exist** — The controller sometimes returns 200 on a malformed POST without creating the resource. Check for missing required fields before looking for a network or auth issue.

**Zone-matrix endpoint aliasing** — `/firewall/zones` returns 404; use `/firewall/zone-matrix` instead. This is the correct endpoint for firewall zone policy matrices.

**Forget-client requires `macs` array** — the `forget-sta` endpoint requires `"macs": [mac_address]`, not `"mac": mac_address`. Always pass an array even for single clients.

**Firewall policy required fields** — zone-based firewall policies require `schedule: {"mode": "ALWAYS"}` on all policies (even ALLOW), and `create_allow_respond: False` on BLOCK/REJECT policies. Omitting these causes silent non-creation or controller errors.

**Firmware-version field variation** — Some response fields behave differently across firmware versions. If a bug report describes unexpected field values and the reporter is on a specific firmware version, treat firmware variation as a likely cause before assuming a code bug. Request the firmware version string and a sample of the affected response payload for diagnosis.