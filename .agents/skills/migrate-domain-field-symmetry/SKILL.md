---
name: myco:migrate-domain-field-symmetry
description: |
  Use when migrating an existing UniFi resource domain to the shared
  field-symmetry model — even if the user doesn't explicitly ask for
  "field symmetry." Covers the full migration procedure: auditing list/create/update
  field parity gaps, creating models/<domain>.py with DomainBase + submodels,
  implementing field validation, and ensuring field symmetry compliance. Also enforces the critical
  ResourceValidator safety constraint: shared validator defaults are forbidden
  (blast-radius anti-pattern). Reference implementation: acl_manager.py + unifi_core.network.models.acl
  (relocated to packages/unifi-core during the Phase 0 schema bootstrap; PR
  #140 introduced the pattern). Active rollout: 26 network domains remaining
  as of May 2026 (tracked in issue #137). Protect and Access bootstraps run
  in separate Phase 1 and Phase 2 workstreams.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Migrating a UniFi Domain to the Field-Symmetry Model

The field-symmetry rule (AGENTS.md, issue #137) requires that every field name
a `list_*` tool exposes in its output must be accepted under the same name by
the matching `create_*` / `update_*` tool. Violating this causes silent drops
(callers believe a constraint was applied; it wasn't) or spurious validation
errors. The ACL domain was the pilot (PR #140); 26 network domains remain
as of May 2026 (Protect and Access bootstraps tracked separately under Phase 1 and Phase 2).

## Prerequisites

- The domain's existing tools and manager are stable (no open conflicts).
- You know which `list_*` tool is the canonical shape source for this domain.
- `packages/unifi-mcp-shared/src/unifi_mcp_shared/validators.py` is available for
  implementing field validation patterns.

## Procedure 1: Audit the Field Gap

Compare the list tool's output schema against every field accepted by the
matching create/update tools. You want a punch list of mismatches.

1. **Find the list tool's output fields.** Read the tool function or its schema
   to enumerate every top-level field name the list response returns.

   ```bash
   grep -n "list_<domain>" apps/network/src/unifi_network_mcp/tools/<domain>.py
   ```

2. **Find the create/update tool signatures.** Check kwargs and any `*_data`
   dict schemas for accepted field names.

3. **Identify gaps.** A gap is any field the list tool exposes that create/update
   does NOT accept under the same name. Common patterns:

   - List returns flat booleans (`qos_enabled`, `route_enabled`); create expects
     nested dicts (`qos: {...}`, `route: {...}`). → Silent drop.
   - List returns `schedule_mode`; update tool accepts no schedule parameter at
     all. → Silent drop.

4. **Document each gap** as: `<list_field>` → currently mapped to
   `<create_param_or_nested_key>` in create/update.

5. **Check for existing field symmetry tests** to see if validation patterns
   already exist for similar domains. Look for test files that validate field
   acceptance patterns.

## Procedure 2: Create `models/<domain>.py`

Model files live at:
`packages/unifi-core/src/unifi_core/<server>/models/<domain>.py`

The reference implementation is `packages/unifi-core/src/unifi_core/network/models/acl.py` (PR #140). Use this structure:

```python
from pydantic import BaseModel
from typing import Optional

class <Domain>Base(BaseModel):
    """Fields shared between create and update for <Domain>."""
    field_a: Optional[str] = None
    field_b: Optional[bool] = None
    # ... all fields that appear in BOTH create and update

class Create<Domain>(<Domain>Base):
    """Fields required or only valid at creation time."""
    name: str                        # required at create
    some_create_only_field: str      # e.g., network_id

class Update<Domain>(<Domain>Base):
    """Fields accepted on update (all optional — partial updates)."""
    pass  # if no update-only fields, base is sufficient
```

**Key invariants:**
- `<Domain>Base` contains every field that appears in BOTH create and update —
  these are the round-trippable fields from the list output.
- `Create<Domain>` adds required fields and any create-only fields.
- `Update<Domain>` may add update-only fields; most domains need none.
- All `<Domain>Base` fields must be `Optional` with `= None` only —
  never supply non-`None` defaults here (see Gotcha 1 below).

## Procedure 3: Implement Field Validation in the Manager

The manager validates that update calls only send recognized field names.

1. **Implement validation logic** in `managers/<domain>_manager.py` to check
   field names against the model schema:

   ```python
   from ..models.<domain> import Create<Domain>, Update<Domain>

   def _validate_update_fields(self, data: dict, model_class):
       """Validate that update data only contains recognized fields."""
       allowed_fields = set(model_class.model_fields.keys())
       provided_fields = set(data.keys())
       invalid_fields = provided_fields - allowed_fields
       if invalid_fields:
           raise ValueError(f"Invalid fields: {invalid_fields}")
   ```

2. **Add validation at the top of the update method:**

   ```python
   async def update_<domain>(self, <domain>_id: str, data: dict) -> dict:
       self._validate_update_fields(data, Update<Domain>)
       # ... existing fetch-merge-put logic
   ```

3. **Update the create method** to use `Create<Domain>` for input validation
   if it doesn't already:

   ```python
   async def create_<domain>(self, data: dict) -> dict:
       validated = Create<Domain>(**data)
       payload = validated.model_dump(exclude_none=True)
       # ... POST to UniFi API
   ```

4. **Verify the tool layer** passes the flat field names from the list output
   (not nested dicts). The manager's model accepts the flat names and translates
   to whatever the UniFi API expects internally (see Gotcha 2).

## Procedure 4: Create Field Symmetry Tests

Create a test file to validate field symmetry for this domain.

1. **Create test file** at `tests/unit/test_<domain>_field_symmetry.py`:

   ```python
   import pytest
   from unifi_core.<server>.models.<domain> import Update<Domain>

   def test_<domain>_field_symmetry():
       """Test that list output fields are accepted by update."""
       # Get list output fields from your domain
       list_fields = {
           "field_a", "field_b", "field_c"
           # ... enumerate from list_<domain> output
       }
       
       # Get update model fields
       update_fields = set(Update<Domain>.model_fields.keys())
       
       # Check symmetry (allowing for known exceptions)
       missing_in_update = list_fields - update_fields - {
           # Add read-only fields here, e.g.:
           # "id", "created_at", "computed_field"
       }
       
       assert not missing_in_update, f"Fields in list but not update: {missing_in_update}"
   ```

2. **Run the test locally** to confirm it passes:

   ```bash
   pytest tests/unit/test_<domain>_field_symmetry.py -v
   ```

3. **If the test fails,** the gap audit missed a field. Return to Procedure 1,
   find the missing field, and extend the model.

4. **Register the (server, domain) pair in the cross-layer symmetry test.**
   Add an entry to `REGISTERED_PAIRS` in
   `apps/api/tests/unit/test_cross_layer_symmetry.py`. This test checks the
   matching Strawberry type at `unifi_api.graphql.types.<server>.<domain>`
   against the pydantic model's `MUTABLE_FIELDS`, catching MCP↔API drift at
   PR time. The Strawberry type must expose every mutable pydantic field name
   with a compatible type annotation.

   Anchor: `apps/api/tests/unit/test_cross_layer_symmetry.py`

## Gotcha 1 — ResourceValidator Blast Radius (NEVER put defaults in shared validators)

**This is the most critical rule in the entire migration.** PR #146 (community
contributor) was blocked because it injected default values into shared
validator logic used by ALL domain update calls.

**Why this destroys update semantics:** If shared validation sets
`schedule = Schedule()` as a default, then every call to
`update_firewall_policy({"name": "new name"})` silently overwrites `schedule`,
`match_ip_sec`, and `ip_version` with their defaults — even though the caller
only wanted to rename the policy. This is a project-wide regression hiding in a
"helpful" default.

**The rule:** Shared validation logic MUST remain default-free.

| Location | Defaults allowed? |
|----------|------------------|
| `Create<Domain>` | ✅ Yes — creation only |
| `<Domain>Base` | ❌ No — `= None` only |
| `Update<Domain>` | ❌ No — `= None` only |
| Shared validators | ❌ Never |

If you see non-`None` defaults in a `Base` or shared validator during code
review, treat it as a merge blocker.

## Gotcha 2 — Flat Fields vs. Nested API Payloads

Some domains expose flat boolean fields in list output (`qos_enabled`,
`route_enabled`) but the UniFi API expects nested objects
(`{"qos": {"enabled": true}}`). The translation lives in the **manager**, not
the model:

```python
# In the manager, after field validation:
payload = dict(data)
if "qos_enabled" in payload:
    payload["qos"] = {"enabled": payload.pop("qos_enabled")}
if "route_enabled" in payload:
    payload["route"] = {"enabled": payload.pop("route_enabled")}
# ... PUT to UniFi API with payload
```

The model accepts `qos_enabled: Optional[bool] = None`. The manager maps it to
the nested API shape. This keeps the tool contract flat and round-trippable
while encapsulating API complexity in the manager layer.

## Gotcha 3 — Non-Mutable Fields Stay in Test Exceptions Permanently

Fields like `id`, `created_at`, and computed read-only summaries must be
documented as exceptions in field symmetry tests. Do NOT enforce symmetry for
genuinely non-mutable fields — only enforce symmetry for mutable fields that
your new model handles.

## Reference Files

| File | Purpose |
|------|---------|
| `packages/unifi-core/src/unifi_core/network/models/acl.py` | Pilot model (PR #140) |
| `apps/network/src/unifi_network_mcp/managers/acl_manager.py` | Pilot manager wiring |
| `apps/api/tests/unit/test_cross_layer_symmetry.py` | MCP↔API drift gate (REGISTERED_PAIRS) |
| `packages/unifi-mcp-shared/src/unifi_mcp_shared/validators.py` | Shared validator patterns |
| `AGENTS.md` | Governance rule (issue #137) |