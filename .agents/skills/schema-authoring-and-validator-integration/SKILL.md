---
name: myco:schema-authoring-and-validator-integration
description: |
  Apply this skill when authoring schema dicts in schemas.py, wiring a domain
  schema to UniFiValidatorRegistry, calling registry.validate() on create or
  update code paths, hardening *_UPDATE_SCHEMA entries with additionalProperties,
  or reviewing any PR that touches schemas.py or validator_registry.py — even if
  the user doesn't explicitly ask about validation. Covers: schema dict structure
  and deepcopy inheritance, UniFiValidatorRegistry registration and the
  validated_data capture pattern (registry.validate() returns a 3-tuple —
  always unpack all three), the create-vs-update path defaults rule and
  ResourceValidator blast-radius anti-pattern, additionalProperties: false
  hardening for Layer-2 SDK safety, field name precision (dhcpd_* vs dhcp_*),
  and unit test patterns for schema validation logic.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# UniFi MCP Schema Authoring and Validator Integration

This skill covers the full lifecycle of schema and validator work in the unifi-mcp monorepo: authoring JSON-Schema dicts in `schemas.py`, wiring them to `UniFiValidatorRegistry`, calling the validator correctly on create vs. update paths, hardening update schemas against SDK kwarg-drop, and writing unit tests. These patterns recur for every new tool category and every community PR that adds update tools.

## Prerequisites

- `apps/network/src/unifi_network_mcp/schemas.py` — authoritative home for all network schema dicts.
- `apps/network/src/unifi_network_mcp/validator_registry.py` — `UniFiValidatorRegistry` class and its `_validators` registration dict.
- `packages/unifi-core/src/unifi_core/validators.py` — `ResourceValidator` base class; the `validate()` method here must NEVER inject defaults (see Procedure C).
- Verify UniFi API field names before writing a schema — a wrong field name passes validation but writes silently fail against a live controller with no error returned.

## Procedure A: Authoring Schema Dicts in schemas.py

### A1. Define the base (create) schema

Every domain schema starts from a `<DOMAIN>_SCHEMA` constant. Required fields go in `"required": [...]`; optional fields with sensible defaults include a `"default"` key in their property dict (defaults are only injected on create paths — see Procedure C).

```python
NETWORK_SCHEMA = {
    "type": "object",
    "properties": {
        "name":    {"type": "string"},
        "purpose": {"type": "string", "enum": ["corporate", "guest", "wan", "vlan-only"]},
        "vlan_id": {"type": "integer", "minimum": 1, "maximum": 4094},
        "enabled": {"type": "boolean", "default": True},
    },
    "required": ["name", "purpose"],
}
```

Field type notes:
- JSON Schema primitives: `"string"`, `"integer"`, `"number"`, `"boolean"`, `"array"`, `"object"`.
- Enumerated values → `"enum": [...]`.
- Add `"minimum"`/`"maximum"` for numeric fields whenever bounds are known — omitting them lets invalid values pass through silently.

### A2. Create the UPDATE schema — deepcopy + strip required and defaults

The update schema is derived from the base schema using `copy.deepcopy`, then `"required"` is removed and all `"default"` values are stripped from properties. This is the canonical project pattern (see `WLAN_UPDATE_SCHEMA` and `NETWORK_UPDATE_SCHEMA` in `schemas.py`):

```python
import copy

NETWORK_UPDATE_SCHEMA = copy.deepcopy(NETWORK_SCHEMA)
NETWORK_UPDATE_SCHEMA.pop("required", None)           # no fields are required on update
NETWORK_UPDATE_SCHEMA.pop("allOf", None)              # remove conditional requires if present
for prop in NETWORK_UPDATE_SCHEMA.get("properties", {}):
    NETWORK_UPDATE_SCHEMA["properties"][prop].pop("default", None)  # strip all defaults
```

**Why deepcopy?** Without it, mutating the dict modifies `NETWORK_SCHEMA` too, corrupting every schema that shares the same base object.

```python
# WRONG — mutates NETWORK_SCHEMA for all callers
NETWORK_UPDATE_SCHEMA = NETWORK_SCHEMA
NETWORK_UPDATE_SCHEMA["additionalProperties"] = False  # also modifies create schema!

# CORRECT
NETWORK_UPDATE_SCHEMA = copy.deepcopy(NETWORK_SCHEMA)
NETWORK_UPDATE_SCHEMA["additionalProperties"] = False
```

Alternatively, standalone update schemas (not derived from a deepcopy) should be written as independent dicts with `"additionalProperties": False` set directly (see `DEVICE_RADIO_UPDATE_SCHEMA` in `schemas.py` as an example of this pattern).

### A3. Set additionalProperties: False on all *_UPDATE_SCHEMA entries

Every `*_UPDATE_SCHEMA` dict MUST have `"additionalProperties": False`. This is Layer-2 SDK hardening: FastMCP can silently drop unknown kwargs; `additionalProperties: False` causes the validator to reject them instead of passing garbage to the controller.

Create schemas should NOT have `"additionalProperties": False` — they need forward-compatibility as the UniFi API evolves.

**Audit for missing hardening:**
```bash
grep -n "_UPDATE_SCHEMA" apps/network/src/unifi_network_mcp/schemas.py
```
For each update schema found, confirm `"additionalProperties": False` is present. Add it where absent — this is a non-breaking addition for correctly-written callers.

## Procedure B: Registering with UniFiValidatorRegistry

### B1. Register both schemas in validator_registry.py

`UniFiValidatorRegistry` uses a class-level `_validators` dict. Adding a new schema requires **two changes** in `apps/network/src/unifi_network_mcp/validator_registry.py`:

```python
# 1. Add to imports at top
from .schemas import (
    # ... existing imports ...
    NETWORK_SCHEMA,          # ← add
    NETWORK_UPDATE_SCHEMA,   # ← add
)
from .validators import ResourceValidator

# 2. Add entries to _validators dict in the class body
class UniFiValidatorRegistry:
    _validators = {
        # ... existing entries ...
        "network":        ResourceValidator(NETWORK_SCHEMA, "Network"),
        "network_update": ResourceValidator(NETWORK_UPDATE_SCHEMA, "Network Update"),
    }
```

Three things must all be present for registration to be complete:
1. `schemas.py` — schema constant defined ✓
2. `validator_registry.py` — schema constant imported at top ✓
3. `validator_registry.py` — key added to `_validators` dict as `ResourceValidator(SCHEMA, "Label")` ✓

A schema defined but not registered raises `KeyError` at runtime. Gap detection:
```bash
grep -n "NETWORK_SCHEMA\|NETWORK_UPDATE_SCHEMA" \
  apps/network/src/unifi_network_mcp/validator_registry.py
```

### B2. Call the validator — always unpack the 3-tuple

`UniFiValidatorRegistry.validate()` returns a **3-tuple** `(is_valid: bool, error_msg: str | None, validated_data: dict | None)`. It is a transformer, not a guard clause. Unpack all three values and pass `validated_data` downstream — never the raw input.

**Correct pattern** (canonical reference: `update_wlan` in `apps/network/src/unifi_network_mcp/tools/network.py:682`):

```python
is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate("network_update", payload)
if not is_valid:
    return {"success": False, "error": f"Invalid update data: {error_msg}"}

# Use validated_data downstream — NOT payload
result = await network_manager.update_network(network_id, validated_data)
```

**Wrong — the validated_data vs payload NameError:**

```python
# WRONG: third tuple element is captured but original dict passed downstream
is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate("network_update", payload)
if not is_valid:
    return {"success": False, "error": error_msg}
result = await network_manager.update_network(network_id, payload)  # ← BUG: raw input
```

This is the **single most common validator mis-wiring bug in community PRs** (confirmed in PRs #123, #126). During any PR review, grep for every `validate(` call and confirm `validated_data` — not the original input variable — is passed to the subsequent API call:

```bash
grep -n "\.validate(" apps/*/src/**/*.py
```

## Procedure C: Create vs. Update Path Defaults — The Blast-Radius Rule

This is the most critical architectural boundary in the validator subsystem.

### The rule

| Code path   | Correct call                                                         | Injects defaults? |
|-------------|----------------------------------------------------------------------|-------------------|
| Create tool | `UniFiValidatorRegistry.validate_and_apply_defaults("key", data)`   | ✅ Yes            |
| Update tool | `UniFiValidatorRegistry.validate("key", data)`                       | ❌ Never          |

### Why — the ResourceValidator blast-radius anti-pattern

`schemas.py` currently contains **37+ `"default":` values** across schema dicts. `ResourceValidator.validate()` — in `packages/unifi-core/src/unifi_core/validators.py` — is called from every update path in the project. If default injection is ever added to `ResourceValidator.validate()`, every update call silently overwrites user-managed fields with schema defaults — even fields the caller never included in the update payload.

This was confirmed as **PR #146 Merge Blocker #1**. Any PR that adds default injection to the shared validator path must be blocked.

```python
# Create path — defaults ARE injected via validate_and_apply_defaults
async def create_network(name: str, purpose: str, **kwargs):
    data = {"name": name, "purpose": purpose, **kwargs}
    is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate_and_apply_defaults(
        "network", data
    )
    if not is_valid:
        return {"success": False, "error": error_msg}
    return await controller.post("/networks", validated_data)

# Update path — defaults are NOT injected; only supplied fields are sent
async def update_network(network_id: str, update_data: dict):
    is_valid, error_msg, validated_data = UniFiValidatorRegistry.validate(
        "network_update", update_data
    )
    if not is_valid:
        return {"success": False, "error": error_msg}
    current = await controller.get(f"/networks/{network_id}")
    merged = deep_merge(current, validated_data)  # see implement-update-tool-fetch-merge-put skill
    return await controller.put(f"/networks/{network_id}", merged)
```

### PR review checklist for this rule

For any PR touching update tools:
1. Does the update handler call `UniFiValidatorRegistry.validate()` (correct) or `validate_and_apply_defaults()` (wrong)?
2. Is `validated_data` — not `payload` — passed downstream?
3. Does the update schema have `"additionalProperties": False`?
4. Does `ResourceValidator.validate()` in `packages/unifi-core/src/unifi_core/validators.py` remain free of default injection?

## Procedure D: Writing Validation Unit Tests

### D1. Schema-level tests (five-test minimum)

For a new schema pair, write at minimum five tests covering both paths:

1. Valid create payload → `validate_and_apply_defaults` accepts, defaults injected for omitted optional fields
2. Valid update payload → `validate` accepts, defaults NOT present in `validated_data`
3. Invalid type for a field → `validate` rejects (`is_valid == False`, `validated_data is None`)
4. Unknown field in update payload → `validate` rejects (`additionalProperties: False`)
5. Missing required field in create payload → `validate` rejects

```python
def test_network_create_injects_defaults():
    data = {"name": "Home", "purpose": "corporate"}
    is_valid, error, validated_data = UniFiValidatorRegistry.validate_and_apply_defaults(
        "network", data
    )
    assert is_valid
    assert validated_data["enabled"] is True  # default injected

def test_network_update_no_default_injection():
    data = {"name": "Home-Updated"}
    is_valid, error, validated_data = UniFiValidatorRegistry.validate("network_update", data)
    assert is_valid
    assert "enabled" not in validated_data   # NOT injected on update path

def test_network_update_rejects_unknown_field():
    data = {"name": "Home-Updated", "not_a_real_field": "x"}
    is_valid, error, validated_data = UniFiValidatorRegistry.validate("network_update", data)
    assert not is_valid
    assert validated_data is None
```

### D2. validate_update_fields() tests (models/acl.py pattern)

For Pydantic-backed update tools, `validate_update_fields()` in `packages/unifi-core/src/unifi_core/network/models/acl.py` is the reference template. Write at minimum three tests:

1. Valid update dict → passes without raising
2. Wrong type for a field → raises `ValueError`
3. Unknown field name → raises `ValueError`

## Cross-Cutting Gotchas

### dhcpd_* vs dhcp_* prefix — silent write failure

DHCP-related schema fields use `dhcpd_` prefix (with a 'd'), **not** `dhcp_`. Using the wrong prefix passes validation but the controller receives an unrecognized field and silently ignores it — DHCP configuration never updates, no error returned.

```python
# CORRECT — matches UniFi API
"dhcpd_enabled":   {"type": "boolean"},
"dhcpd_start":     {"type": "string"},
"dhcpd_stop":      {"type": "string"},
"dhcpd_leasetime": {"type": "integer"},

# WRONG — silently fails against live controller
"dhcp_enabled":    {"type": "boolean"},  # missing 'd'
```

This latent bug was caught in PR #131 review. Always verify field names against the UniFi API before authoring a schema — grep known-working schemas or check a live controller response.

### validated_data vs payload NameError is the top community PR catch

For every `validate(` call in a PR, confirm:
1. All three return values are unpacked: `is_valid, error_msg, validated_data = ...`
2. `is_valid` is checked before proceeding
3. `validated_data` — not the original variable — reaches the API call

### Schema definition ≠ schema registration

These are always two separate changes in two separate files. A PR is not complete until both `schemas.py` (constant defined) and `validator_registry.py` (imported and added to `_validators`) are updated.

### Defaults in schemas.py are create-path-only

The `"default"` values in `schemas.py` are only injected when `validate_and_apply_defaults()` is explicitly called. `ResourceValidator.validate()` does not inject them. This is intentional — don't change it.
