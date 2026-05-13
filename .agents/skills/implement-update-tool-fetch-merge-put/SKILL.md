---
name: myco:implement-update-tool-fetch-merge-put
description: >
  Use this skill whenever you are implementing or fixing an update_* tool in unifi-mcp. It covers the mandatory fetch-merge-put pattern, deep_merge semantics, V2 API response gotchas, the confirm double-fetch design, LLM UX requirements for dict params, and when flat params are appropriate instead. Applies even if the user only says "add an update tool for X" without specifying the implementation approach — the pattern is required for all update tools in this project.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Implementing an Update Tool: The Fetch-Merge-Put Pattern

All update tools in unifi-mcp follow the **fetch-merge-put** pattern. Skipping the fetch step causes silent data loss — the PUT wipes every field not included in the payload. Five tools shipped with this bug (issue #113) before the pattern was standardized. This skill teaches you how to do it right.

## Prerequisites

- The resource's manager already has a `get_<resource>_by_id` method. If not, write it first (check the V2 API gotcha below before you do).
- `deep_merge` is importable from `unifi-core`. Tests for merge behavior live in `packages/unifi-core/tests/test_merge.py` — run them after any merge logic change.
- The create tool for this resource already exists. Update tools assume the object exists; if it doesn't, the caller should use create, not update.
- The field symmetry rule (issue #137) requires `update_data` to accept all field names and compatible types from the read surface. Field symmetry validation is enforced via test patterns in the test layer.

## Steps

### 1. Read the golden path reference first

Before writing any code, read `network_manager.py:update_network`. It is the canonical implementation of the pattern. Let it orient your mental model before you look at the resource you're adding.

### 2. Implement the four-step pattern

```python
async def update_<resource>(self, resource_id: str, update_data: dict) -> dict:
    # 1. Fetch current state
    current = await self.get_<resource>_by_id(resource_id)
    if not current:
        raise ValueError(f"<Resource> {resource_id} not found")

    # 2. Deep-copy before mutating (protects the cached response)
    import copy
    base = copy.deepcopy(current)

    # 3. Merge caller's partial dict over the base
    merged = deep_merge(base, update_data)

    # 4. PUT the fully-merged object
    return await self._connection.put(f"<endpoint>/{resource_id}", merged)
```

All four steps are required. The deep copy in step 2 is not optional — mutating the cached object in-place corrupts subsequent reads within the same session.

### 3. Understand deep_merge semantics

`deep_merge` has deliberate rules about what it recurses into:

| Value type | Behavior |
|------------|----------|
| `dict` | Merged recursively — sibling keys are preserved |
| `scalar` | Replaced — caller's value wins |
| `list` | Replaced entirely — not element-merged |
| `None` | Replaced — cannot distinguish "clear this field" from "I didn't specify it" |

The list replacement rule is intentional: merging lists would require knowing whether the caller means "append" or "replace," which is ambiguous at the API boundary. If your resource has list fields that need partial updates, document that the caller must pass the full desired list.

### 4. Handle the V2 API response envelope

Some UniFi endpoints (especially newer ones) wrap responses in a `data` list:

```json
{ "data": [ { ...actual object... } ] }
```

If your `get_<resource>_by_id` doesn't unwrap this envelope, `deep_merge` will try to merge against the wrapper dict — the PUT will fail or corrupt data. Check the raw response shape in the controller before assuming the object is at the top level. The fix is to unwrap in the getter:

```python
response = await self._connection.get(f"<endpoint>/{resource_id}")
items = response.get("data", [response])  # normalize both shapes
return items[0] if items else None
```

### 5. Implement the MCP tool with dict params

The MCP tool wrapping the manager method must use a `dict`-typed `update_data` parameter, not individual keyword args. This is an LLM UX requirement: LLMs handle partial updates far better when they can pass a single dict of only what's changing, rather than being forced to specify every field.

```python
@mcp.tool()
async def update_<resource>(
    resource_id: str,
    update_data: dict,
    confirm: bool = False,
) -> str:
    """
    Update a <resource>. Pass only the fields you want to change in update_data.
    The tool fetches current state and merges your changes — fields you omit are preserved.

    Set confirm=True to apply the change, or omit it to preview what would change.
    """
    ...
```

Include the "pass only fields you want to change" language in the docstring. The LLM reads docstrings to understand how to call the tool.

### 6. Enforce field symmetry: update_data must match read-surface fields

The `update_data` dict must accept **all field names and compatible types** that the resource's
read-surface tools (`list_*`, `get_*`) expose. If a field appears in the read surface but is
absent from `update_data`, the tool silently cannot update that field — a hidden capability gap.

Field symmetry validation is enforced via test patterns in the test layer. A test failure means your
update tool has a field symmetry gap. Fix it before opening the PR.

How to check: read the `list_<resource>` and `get_<resource>` return fields, then confirm each
one either (a) appears in `update_data`, or (b) is documented as intentionally read-only with
a comment explaining why (e.g., server-assigned fields like `id` or `created_at`).

**Known current violations (as of issue #137):**
- `update_content_filter`: does not handle `schedule_mode`, which is returned by the list surface.
- `create_oon_policy`: the list surface (`list_oon_policies`) exposes `qos_enabled` and `route_enabled` as flat booleans, but `create_oon_policy` expects them as nested `qos`/`route` dicts — a structural shape mismatch, not just a missing field.

Issue #137 tracks remediation of these violations.

**CI rollout — allow-list in test patterns:** When adding field symmetry tests for a new resource domain, document any pre-existing violations with a comment linking the tracking issue — do not block CI on legacy gaps.

### 7. Add additionalProperties: false to the UPDATE_SCHEMA entry

Every `*_UPDATE_SCHEMA` entry in the schema definitions must include `"additionalProperties": false`.
This is Layer-2 hardening against the ArgModelBase silent-drop vulnerability: FastMCP's
`ArgModelBase` is missing `model_config = ConfigDict(extra="forbid")`, so extra keys passed to
a tool are silently dropped before your validator sees them. The schema-level restriction closes
this gap at the transport boundary.

```python
# In schema definitions
NETWORK_UPDATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,   # ← required on every update schema
    "properties": {
        "network_id": {"type": "string"},
        "update_data": {"type": "object"},
        "confirm": {"type": "boolean"},
    },
    "required": ["network_id", "update_data"],
}
```

This applies to all update schemas, including existing ones. When patching managers for issue #113
or any future batch fix, add `additionalProperties: false` to each schema entry at the same time.

### 8. Implement the confirm preview using a delta, not the merged result

The `confirm=False` preview must show **what is changing**, not the full merged object. The full object is noise — the caller already knows the current state. Show the delta:

```python
if not confirm:
    current = await manager.get_<resource>_by_id(resource_id)
    # Show only the keys the caller is changing
    preview = {k: {"before": current.get(k), "after": v}
               for k, v in update_data.items()}
    return f"Preview (pass confirm=True to apply):\n{json.dumps(preview, indent=2)}"
```

This is a deliberate design decision, not an oversight. The confirm flow does a second fetch (double-fetch) even though the apply path also fetches — that's intentional to ensure the preview reflects live controller state, not stale cache.

### 9. Patch all managers for a new utility

If you're adding or changing merge behavior that affects multiple managers, check documentation for the list of managers that implement update tools. All managers with update tools should be patched in the same PR — partial patches leave the codebase inconsistent.

## Validator Pitfall: Schema Defaults in Shared Validators

The `ResourceValidator.validate()` shared base method is a **blast-radius risk** for update tools. If a PR injects schema defaults into this shared method, every update tool that calls `.validate()` will silently overwrite fields the caller intentionally omitted — exactly the data-loss bug the fetch-merge-put pattern was designed to prevent.

**Example of the failure mode:**

```python
# DANGEROUS: defaults injected into shared validator
class ResourceValidator:
    def validate(self, data: dict) -> dict:
        data.setdefault("create_allow_respond", False)  # ← blast radius
        data.setdefault("schedule", {"mode": "ALWAYS"})  # ← blast radius
        return data
```

With this code, `update_firewall_policy({"name": "new"})` would silently inject
`create_allow_respond: False` and `schedule: {"mode": "ALWAYS"}` — overwriting whatever the
controller currently has, regardless of what the caller specified.

**The rule:** Schema defaults must **never** live in the shared base validator. Defaults belong
exclusively in:
- Create-specific code paths (a separate `create` method or subclass override), or
- An explicit opt-in method such as `validate_and_apply_defaults()` that update tools do not call.

When reviewing a PR that modifies `ResourceValidator` or any shared validator class, check whether
defaults are being added to a code path that update tools share. If so, this is a **hard blocker**:
the blast radius spans all 37+ default-using properties and all three app packages.

This pitfall emerged from PR #146 review. It is structurally independent of the `additionalProperties`
gate (Step 7) — both protections are needed.

## Create vs. Update Asymmetry

Update tools use dict params. Create tools use flat keyword params. This is intentional:

- **Create**: The caller is specifying a complete object from scratch. Flat params with defaults make the required fields clear and the optional ones discoverable.
- **Update**: The caller is expressing a delta. A dict is the natural representation of "change these specific things."

Don't mirror the create tool's signature when building the update tool. They're solving different problems.

## Regression Test Standard

Every update tool must have a test that verifies non-passed fields are preserved after the update. The pattern:

```python
def test_update_preserves_unspecified_fields():
    original = {"name": "original", "vlan": 10, "notes": "keep me"}
    mock_get.return_value = original
    await manager.update_<resource>("id-1", {"name": "new-name"})
    put_payload = mock_put.call_args[1]["json"]
    assert put_payload["vlan"] == 10       # preserved
    assert put_payload["notes"] == "keep me"  # preserved
    assert put_payload["name"] == "new-name"  # updated
```

This test pattern catches the original bug class (PUT without fetch) at the test level.

## Established Pattern: Shared-Field-Models

The shared-field-models pattern defines resource fields once in a shared Pydantic base model that is imported by create, update, list, and read tools alike. This makes field symmetry structurally enforced rather than test-enforced. The ACL domain serves as the reference implementation.

**What the reference implementation produced (ACL pattern):**

- A validation helper lives in the manager/models layer (~20 lines). The model layer owns type enforcement.
- Tool layer calls the validation helper before any processing (+6 lines). Tool files stay thin; validation logic stays in models.
- Type-validation tests cover the helper directly.

When implementing update tools for new resource domains, consider the shared-model pattern rather
than inline schema dicts — particularly for complex resources with many fields. The ACL reference should be used as the concrete pattern, not just the issue description. Inline schema dicts remain acceptable for simple resources or incremental fixes.