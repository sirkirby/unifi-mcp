---
name: myco:unifi-api-endpoint-patterns
description: >-
  Apply this skill when implementing or debugging a UniFi resource manager, adding a new tool category, reviewing community PRs that touch manager code, or troubleshooting unexpected API responses. Covers five recurring API behavior patterns every manager author must know: (1) 405 Method Not Allowed on GET-by-ID for specific resource types and the list-then-filter workaround, (2) V2 endpoint response shape normalization where single-resource GETs return a list, (3) resource-specific required fields that silently reject creation without non-obvious parameters, (4) zone-matrix endpoint aliasing where /firewall/zones returns 404 but /firewall/zone-matrix is correct, and (5) firmware-version field variation. Activate this skill even if the user doesn't explicitly ask about API quirks — any time a new manager is being built or a get_*_by_id or create_* method is being written.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# UniFi Controller API Endpoint Patterns

When building or maintaining resource managers in this project, the UniFi controller API has several non-obvious behaviors that are not discoverable by reading the code alone. These patterns appear across multiple resource types and firmware versions. Every new manager author encounters them — usually by debugging a silent failure or an unexpected HTTP status code.

## Prerequisites

- You're working in the `managers/` directory, adding or modifying a resource manager.
- You understand the basic `_request` / `_get` / `_post` call conventions from an existing manager (e.g., `packages/unifi-core/src/unifi_core/network/managers/network_manager.py`).
- You know whether the target resource lives on a V1 or V2 API endpoint. V2 uses `/v2/api/site/{site}/...`; legacy V1 uses `/api/s/{site}/rest/...`. Check existing managers to see which path the resource type uses.
- Confirm whether the endpoint is V1 or V2 — the signal is `ApiRequestV2` from `aiounifi.models.api`. V1 methods use plain dict-based requests; V2 methods construct an `ApiRequestV2` object.

## Procedure A: GET-by-ID for New Resource Types — Test for 405 First

Some UniFi resource types return `405 Method Not Allowed` on `GET /resource/{id}`. This is not a permissions error and not a bad ID — the endpoint simply does not support individual lookup. Confirmed affected types:

- DNS records (`managers/dns_manager.py`)
- AP groups
- Content filtering
- ACL rules (`managers/acl_manager.py`)

**The list-then-filter workaround** — fetch all resources and find by `_id`:

```python
def get_dns_record_by_id(self, record_id: str) -> dict | None:
    """GET /dns/{id} returns 405; list all and filter instead."""
    records = self.list_dns_records()
    return next((r for r in records if r.get("_id") == record_id), None)
```

When adding any new resource type, verify `GET /{resource}/{id}` succeeds before implementing a direct lookup. If you get 405, implement `list_*` first and build `get_*_by_id` on top of it. This is a permanent API characteristic of these resource types — not a transient bug, not a firmware issue.

If you see 405 during development, switch to the list-then-filter pattern immediately rather than debugging auth or headers.

## Procedure B: V2 Endpoint Response Shape Normalization

V2 endpoints are preferred for new managers. However, single-resource GETs on V2 endpoints often return the resource wrapped in a **list** rather than a plain dict. A `get_*_by_id` method that doesn't handle this will silently return `None` for valid IDs — which looks like a "not found" bug rather than a shape mismatch.

### B1: Understanding the V2 Response Shape

V2 single-resource GET endpoints return the resource wrapped in a **one-element list**, not a dict like V1 endpoints. The shapes differ by API version rather than resource type. Because the shapes differ, every V2 `get_*_by_id` implementation must explicitly unwrap the list — omitting this produces a silent failure where an existing resource appears as "not found" with no exception or log noise.

**Standard V2 URL patterns:**
```
/v2/api/site/{self.site}/{resource}/         # list → returns [item1, item2, ...]
/v2/api/site/{self.site}/{resource}/{id}     # get-by-id → returns [item] (single-element list!)
```

Three production bugs shared this root cause: `get_acl_rule_by_id`, `get_client_group_by_id`, and `get_oon_policy_by_id` (all fixed in commit `30f6421`).

### B2: Implement a New V2 get_by_id Method

1. **Import `ApiRequestV2`** at the top of the manager file:
   ```python
   from aiounifi.models.api import ApiRequestV2
   ```

2. **Call the V2 endpoint** using `ApiRequestV2` and capture the raw response:
   ```python
   api_request = ApiRequestV2(method="get", path=f"/<resource-path>/{resource_id}")
   response = await self._connection.request(api_request)
   ```

3. **Unwrap using the three-branch pattern** — list branch first, dict branch second, error last:
   ```python
   if isinstance(response, list) and response:
       return response[0]
   if isinstance(response, dict):
       return response
   return {\"error\": \"not found\"}
   ```

4. **Do not** write only the dict branch. The most common V2 shape is a list, and omitting the list check produces a silent failure — a valid resource returns `{\"error\": \"not found\"}` with no warning.

5. **Complete method skeleton** (from `managers/network_manager.py`):

   ```python
   async def get_widget_by_id(self, widget_id: str) -> Dict[str, Any]:
       \"\"\"Get a single widget by ID (V2 endpoint — response is a list, unwrap to dict).\"\"\"
       if not await self._connection.ensure_connected():
           raise ConnectionError(\"Not connected to controller\")

       api_request = ApiRequestV2(method=\"get\", path=f\"/widgets/{widget_id}\")
       try:
           response = await self._connection.request(api_request)
       except Exception:
           response = None

       if isinstance(response, list) and response:
           return response[0]
       if isinstance(response, dict):
           return response
       raise UniFiNotFoundError(\"widget\", widget_id)
   ```

6. **Test both code paths**: Pass a real ID → expect the resource dict returned. Pass a nonexistent ID → expect `{\"error\": \"not found\"}`, not an exception.

### B3: Fix an Existing V2 get_by_id with a Silent Failure

When a `get_*_by_id` method returns nothing (or `{\"error\": \"not found\"}`) for a resource that actually exists, the root cause is almost always a missing list-unwrap.

1. **Locate the method** in `packages/unifi-core/src/unifi_core/network/managers/<domain>_manager.py`

2. **Identify the faulty pattern** — a dict-only check with no list branch:
   ```python
   # BROKEN — misses the V2 list shape entirely
   if isinstance(response, dict):
       return response
   return {\"error\": \"not found\"}
   ```

3. **Insert the list branch above the dict branch**:
   ```python
   # FIXED
   if isinstance(response, list) and response:
       return response[0]
   if isinstance(response, dict):
       return response
   return {\"error\": \"not found\"}
   ```

4. **Verify the method uses `ApiRequestV2`** — if it does, the response will be a list for V2 endpoints. If the method falls back to listing all resources and filtering by ID (the 405 workaround pattern used by `get_acl_rule_by_id`), the isinstance pattern does not apply; the list returned is the full collection, not the V2 single-resource wrapper.

5. **Confirm with a live or mock test** that the resource is returned correctly after the fix.

### B4: Audit All V2 get_by_id Methods

Run this audit when onboarding to the codebase, after adding new tool files, or when a silent-failure regression is suspected.

1. **Find all get_by_id methods in the managers directory**:
   ```bash
   grep -rn \"def get_.*_by_id\" packages/unifi-core/src/
   ```

2. **Identify which ones use ApiRequestV2 (V2 endpoints)**:
   ```bash
   grep -B 30 \"def get_.*_by_id\" packages/unifi-core/src/ -r | grep \"ApiRequestV2\"
   ```

3. **Check each V2 method for the list-unwrap branch**:
   ```bash
   grep -A 20 \"def get_.*_by_id\" packages/unifi-core/src/ -r | grep \"isinstance.*list\"
   ```
   A V2 method with no matching result is at risk.

4. **Fix each at-risk method** using B3 above.

5. **Commit with a clear message** referencing the pattern, e.g.:
   ```
   fix: add V2 list-unwrap to get_by_id methods (client_group, oon_policy)
   ```

## Procedure C: Zone-Based Firewall Policy — Required Fields on Create

Zone-based firewall policies silently reject creation if non-obvious required fields are missing. The controller returns 200 but does not create the resource. Firmware 5.x behavior, validated on UDM Pro hardware (PR #146).

The required-fields enforcement lives in `apps/network/src/unifi_network_mcp/tools/firewall.py` (lines ~349-351) and their defaults are defined in `apps/network/src/unifi_network_mcp/schemas.py`. The manager's `create_firewall_policy` method in `managers/firewall_manager.py` makes the API call after these fields are validated and filled.

**`schedule` is required on ALL policies**, including ALLOW:

```python
payload = {
    \"name\": name,
    \"action\": action,   # \"ALLOW\", \"BLOCK\", or \"REJECT\"
    \"schedule\": {\"mode\": \"ALWAYS\"},   # ← required even for ALLOW policies
    # ... other fields
}
```

**`create_allow_respond` must be `False` on BLOCK and REJECT policies:**

```python
if action in (\"BLOCK\", \"REJECT\"):
    payload[\"create_allow_respond\"] = False
```

Omitting `create_allow_respond: False` on a BLOCK/REJECT policy raises `FirewallPolicyCreateRespondTrafficPolicyNotAllowed` from the controller. Omitting `schedule` causes a silent non-creation with no clear error message.

Neither field is documented in Ubiquiti's public API reference. They were discovered through real-hardware UDM Pro testing by a community contributor.

## Procedure D: Forget-Client Endpoint — `macs` Array, Not `mac` String

The `unifi_forget_client` tool maps to the `forget-sta` controller endpoint. That endpoint requires `\"macs\"` as an **array**, not `\"mac\"` as a string. Reference: `managers/client_manager.py` (line ~215), PR #143.

```python
# WRONG — silently fails or errors
payload = {\"mac\": mac_address}

# CORRECT — matches forget-sta endpoint spec
payload = {\"macs\": [mac_address]}
```

When reviewing any community PR that touches client-management tools or constructs a `forget-sta` request, verify the payload key is `\"macs\"` (plural) and the value is an array, even when forgetting a single client.

## Procedure E: Firewall Zone Matrix Endpoint — /firewall/zone-matrix Alias

The `/firewall/zones` endpoint returns `404 Not Found`, but the correct endpoint is `/firewall/zone-matrix`. Both paths refer to the same resource — the zone matrix defines how traffic flows between firewall zones (LAN, WAN, Guest, etc.). This is not a version mismatch or a typo; the zones endpoint was never publicly surfaced. Always use `/firewall/zone-matrix`.

**Canonical pattern** (from Session 17):

```python
def get_firewall_zone_matrix(self) -> dict:
    \"\"\"Fetch firewall zone traffic flow matrix.
    
    Note: /firewall/zones returns 404; the correct path is /firewall/zone-matrix.
    \"\"\"
    return self._get(f\"/v2/api/site/{self.site}/firewall/zone-matrix\")
```

If you see a `404` on any firewall-adjacent endpoint, check whether the correct path uses a different suffix (e.g., `-matrix`, `-config`, `-status`). Ubiquiti's controller often exposes multiple endpoint paths for related resources.

## Procedure F: Firmware-Version Field Variation

Some response fields behave differently across firmware versions. This is distinct from the endpoint-level patterns above — the endpoint works, but field values are wrong or missing on specific firmware builds.

**Known open issue:**
- **`is_wired` detection** — incorrect on firmware 10.2.104 (Issue #114). Cannot be fully reproduced without `/stat/sta` data from an affected controller.

When a bug report describes unexpected field values (boolean flips, missing fields, unexpected types) and the reporter is on a specific firmware version, treat firmware variation as a likely cause before assuming a code bug. Ask for:
1. The firmware version string
2. A redacted sample of the `/stat/sta` payload from the affected device

Do not ship a workaround for firmware-specific behavior without a reproduction payload — the fix may mask correct behavior on other versions.

## Cross-Cutting Gotchas

**Prefer V2 endpoints for new managers.** Default to `/v2/api/site/{site}/...` where the resource type has a V2 path. Only fall back to legacy `/api/s/{site}/rest/...` if V2 isn't available.

**405 is not a permissions or ID problem.** On a `GET /{resource}/{id}` call, a 405 means the endpoint doesn't support the operation at all. Don't debug auth headers or ID formatting — switch to `list() + filter` immediately.

**Silent creation failures exist.** The controller sometimes returns 200 on a malformed POST without creating the resource. If a create operation succeeds but the resource never appears, check for missing required fields before looking for a network or auth issue. Zone firewall `schedule` is a known example.

**404 often means wrong endpoint path.** Check whether the resource is surfaced under a different path suffix (matrix, config, status, policy, etc.) before assuming the resource type is unsupported.

**Silent failure with no signal — Checking only `isinstance(response, dict)` when V2 returns a list causes the method to fall through to `{\"error\": \"not found\"}`. There is no exception, no log noise — just a wrong result. This is why the bug survived undetected until explicit testing.

**Empty list means not found.** V2 may return `[]` for a nonexistent resource ID. The guard `response[0] if response else {\"error\": \"not found\"}` (or `and response` in the condition) handles this safely without raising an `IndexError`.

**Branch order is load-bearing.** The list check must come before the dict check. A list is never a dict, so the order doesn't cause logical overlap, but accidentally reversing the branches in a future edit would silently reintroduce the bug.

**V1 vs V2 determination.** The canonical signal is `ApiRequestV2` usage, not the URL path. If the manager imports and uses `ApiRequestV2(method=\"get\", ...)`, the endpoint is V2 and the response will be a list. Plain dict-based V1 requests return a dict directly.

**The 405 workaround pattern is different.** `get_acl_rule_by_id` in `acl_manager.py` does not use `ApiRequestV2` for the by-ID call because `GET /acl-rules/{id}` returns 405. Instead it calls `get_acl_rules()` (which returns the full list) and filters by ID. Do not apply the V2 isinstance pattern to 405-workaround methods.

**Validate with real hardware early.** Several of these patterns were only discovered through community contributor testing on physical UDM Pro hardware. For new resource types — especially firewall, routing, or policy resources — request community hardware validation before declaring the implementation stable.
