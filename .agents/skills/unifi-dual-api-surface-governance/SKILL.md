---
name: myco:unifi-dual-api-surface-governance
description: |
  Apply this skill whenever you are adding, extending, or debugging an MCP tool that
  touches a UniFi feature served by more than one API surface — specifically when a
  feature appears on both the Protect private API (/proxy/protect/api/) and the
  UniFi OS-level v2 service (/api/v2/). This skill covers: mapping which endpoints
  belong to which surface, implementing a version-transparent façade with automatic
  backend selection, handling the SuperAdmin permission requirement for /api/v2/
  endpoints, emitting _meta coverage signals when serving from a degraded backend,
  and fixing empty-body response bugs using api_request_raw. Apply even if the user
  doesn't explicitly ask about API versioning — any time you're touching alarm rules,
  arm/disarm profiles, or a new Protect domain that might have both a legacy
  /proxy/protect/api/ path and a newer /api/v2/ path.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# UniFi Dual API Surface Governance

UniFi Protect features can be served by two (or three) completely separate API
services: the Protect private API at `/proxy/protect/api/`, and the UniFi OS-level
service at `/api/v2/`. These surfaces are independent — different auth requirements,
different ID schemes, different data models, and different coverage. Failing to bridge
them correctly causes agents to see silent data gaps with no signal that anything is
missing. This skill teaches you how to discover surface boundaries, abstract them
behind a stable façade, handle auth and protocol quirks, and signal coverage gaps
explicitly.

## Prerequisites

Before working in this domain:

1. **Identify all API surfaces.** Open the Protect UI in a browser, navigate to the
   feature area (e.g., Alarm Manager, arm/disarm profiles), and capture network
   traffic. UI network calls reveal the actual endpoint paths — not the ones you'd
   assume from existing code.

2. **Understand the three known surfaces for Alarm-related features:**

   | Surface | Base Path | Contents | Auth |
   |---|---|---|---|
   | Protect private API | `/proxy/protect/api/automations` | Legacy rules (Mongo ObjectIDs) | Standard admin |
   | UniFi OS v2 | `/api/v2/alarms/` | Legacy + AI-NL alarms, UUID IDs | **SuperAdmin** |
   | UniFi OS v2 (Protect) | `/api/v2/alarms/protect` | Full ruleset for Protect | **SuperAdmin** |
   | UniFi OS v2 (profiles) | `/api/v2/alarms/profiles` | Arm/disarm profiles | **SuperAdmin** |

3. **Account permissions.** The `/api/v2/*` service requires **SuperAdmin** role.
   Elevate the service account (e.g., `homebridge`) in UniFi OS User Management
   before testing. A 403 from `/api/v2/` means permissions, not routing — a routing
   failure would produce a 404.

4. **Routing v2 calls.** `uiprotect.api_request(api_path="/api/v2/alarms/", url="...")`
   routes to the OS-level service through the existing client. No bespoke HTTP client
   is needed. The `api_path` parameter controls which base the URL is relative to.

## Procedure A: Mapping a New Dual-Surface Feature

When you encounter a Protect UI feature that doesn't match the data your code returns,
suspect a dual-surface gap.

1. **Live comparison test.** Fetch from both surfaces for the same feature type and
   compare record counts and ID formats:
   - Protect private path (e.g., `/proxy/protect/api/automations`) — count records
   - UniFi OS path (e.g., `/api/v2/alarms/protect`) — count records
   - If v2 count > legacy count: v2 has additional data types the legacy API cannot
     represent (e.g., AI natural-language alarms)

2. **Check ID schemes.** If legacy returns Mongo ObjectIDs (24-char hex) and v2
   returns UUIDs (8-4-4-4-12), they are different representations of the same
   underlying data — not duplicate services. Document this in the discovery spore.

3. **Determine subset relationship.** For alarm rules: legacy is a strict subset of
   v2 (52/52 legacy rules appear in v2, plus AI-NL alarms exclusive to v2). Document
   the relationship explicitly — it determines which surface should be preferred and
   which is the safe fallback.

4. **Flag silent gaps.** If the existing tool returns from legacy only and v2 has
   records that legacy cannot represent, this is a correctness issue: agents see a
   partial picture with no signal that anything is missing. Before PR #320,
   `protect_alarm_list_rules` silently omitted all AI-NL alarms.

## Procedure B: Implementing a Version-Transparent Façade

When a feature lives on multiple incompatible API surfaces, the tool name must describe
capability, not implementation. Abstract the version in the backend, not the tool name.

**Do NOT** create `protect_alarm_v2_list_rules` alongside `protect_alarm_list_rules`.
This forces agents to reason about API versions (a maintainer concern), and creates
parallel tool families that must be kept in sync forever.

**Do** create a façade class with automatic backend selection. The real implementation
is in `packages/unifi-core/src/unifi_core/protect/managers/alarm_facade.py`:

```python
# alarm_facade.py — simplified structure (see AlarmRulesFacade in the actual file)
class AlarmRulesFacade:
    def __init__(self, service_manager: AlarmManagerService, legacy_manager: AlarmManager):
        self._service = service_manager    # /api/v2/alarms/ via AlarmManagerService
        self._legacy = legacy_manager      # /proxy/protect/api/automations via AlarmManager

    async def list_rules(self) -> tuple[list[dict], bool]:
        try:
            rules = await self._service.list_rules()
        except (AlarmManagerPermissionError, BadRequest):
            rules = None
        if rules:
            return rules, True          # v2 backend: complete coverage
        raw = await self._legacy.list_rules()
        return [alarm_rule_from_legacy(r).model_dump(exclude_none=True) for r in raw], False
        # False signals fallback; tool layer emits _meta coverage key
```

**Canonical model.** The v2 `AlarmRule` model lives in
`packages/unifi-core/src/unifi_core/protect/models/alarm_rules.py`. Key fields:

```python
class AlarmRule(BaseModel):
    id: Optional[str] = Field(...)         # UUID (v2) or ObjectID (legacy)
    title: Optional[str] = Field(...)      # Rule display name
    enabled: Optional[bool] = Field(...)   # v2 only; absent in legacy via exclude_none
    triggers: list[AlarmTrigger] = ...     # v2 trigger model
    actions: list[AlarmAction] = ...
    scope: dict[str, Any] = ...
```

Use `model.model_dump(exclude_none=True)` when serializing legacy-sourced records so
callers see a stable field contract regardless of which backend served the data.

**Internal naming discipline.** Remove `v2` from all internal identifiers:
- `AlarmV2Manager` → `AlarmManagerService`
- `alarm_rule_v2_from_controller` → `alarm_rule_from_controller`

The literal `/api/v2/alarms/` path in routing code is preserved — it's a real URL,
not a naming choice. That distinction matters: URL paths are facts; type and function
names are choices.

**TDD sequence:**
1. Canonical model tests (field presence/absence by backend)
2. Façade routing tests (mock both backends; assert v2 is tried first)
3. Fallback tests (mock v2 to raise `AlarmManagerPermissionError` or `BadRequest`; assert legacy used + `_meta` emitted)
4. Tool wiring tests (assert tool calls façade, not backend directly)
5. Manifest regen → live smoke test with both account permission levels

## Procedure C: Fixing Empty-Body Response Bugs

Protect mutation endpoints (DELETE, some POST) return an **empty body** on success.
`uiprotect`'s `api_request()` unconditionally calls `response.json()`, which throws
`Could not decode JSON` on `b""`. The operation succeeds; the error is spurious.

**Symptom:** A delete or merge operation raises `Could not decode JSON` even though
the entity is actually gone (confirmed by a subsequent fetch returning 404/NotFound).

**Diagnosis.** Probe the endpoint with `api_request_raw` and print the raw response:

```python
resp = await api.api_request_raw("delete", url, raise_exception=False)
print(f"raw_type={type(resp)}  body={resp}")
# None or b"" confirms the empty-body pattern
```

**Fix:**

```python
# Broken: empty response → JSON decode error
await self._api.api_request("delete", url, raise_exception=True)

# Fixed: returns raw bytes, handles empty body cleanly
await self._api.api_request_raw("delete", url, raise_exception=True)
```

This switch is always safe when the caller **discards the response** — specifically
methods that capture a pre-operation preview snapshot and return that, ignoring the
operation's response body entirely.

**Known affected methods (all fixed), in `packages/unifi-core/src/unifi_core/protect/managers/recognition_manager.py`:**
- `apply_delete_known_face` — DELETE `/recognition/face/groups/{id}` — PR #319
- `apply_delete_known_vehicle` — DELETE vehicle group — PR #316
- `apply_merge_known_faces` — POST `/recognition/face/groups/merge` — PR #321

**Audit rule for new endpoints.** Any new `method="delete"` or discarded-response
POST call in a Protect manager must use `api_request_raw`. Probe before shipping.
The empty-body bug class is fully closed for existing methods — don't reopen it.

**Test pattern:** Assert `api_request_raw` is called (not `api_request`). Run the
full protect suite (396+ tests) to confirm no regressions.

## Procedure D: Emitting `_meta` Coverage Signals

When a tool serves from a degraded backend (partial data), signal this explicitly in
the response rather than silently omitting records.

**Convention.** Use the project's `com.github.sirkirby.unifi-mcp/` reverse-DNS
namespace for `_meta` keys. The alarm coverage constant, defined in
`apps/protect/src/unifi_protect_mcp/tools/alarm.py`:

```python
_ALARM_COVERAGE_META = "com.github.sirkirby.unifi-mcp/alarm-coverage"
_ALARM_COVERAGE_NOTICE = (
    "Showing legacy Protect automations: the UniFi-OS Alarm Manager (/api/v2/alarms) "
    "returned no rules or is unavailable on this console, so AI-powered alarms "
    "(where supported) are not included."
)
```

**Where to emit.** In the tool layer's helper function, merge `_meta` into the
serialized response when the façade signals incomplete coverage (`complete=False`):

```python
def _with_alarm_coverage_meta(result: dict, complete: bool) -> dict:
    if not complete:
        result["_meta"] = {_ALARM_COVERAGE_META: {"complete": False, "reason": _ALARM_COVERAGE_NOTICE}}
    return result
```

Call this wrapper on every tool that returns alarm rule data:

```python
return _with_alarm_coverage_meta({"success": True, "data": {"rules": rules, "count": len(rules)}}, complete)
```

**What `_meta` communicates to agents:**
- Key `com.github.sirkirby.unifi-mcp/alarm-coverage` → `{"complete": False, "reason": <human-readable notice>}`
- Absence of `_meta` → v2 backend used; full coverage assumed (do not emit `_meta` for v2 responses)

**When NOT to emit `_meta`.** SuperAdmin v2 responses omit `_meta` entirely.
Only emit it when coverage is genuinely incomplete. Never fabricate a `_meta` key
to explain a legitimate error — that's a different code path.

## Procedure E: SuperAdmin Elevation and Graceful Degradation

The `/api/v2/` service permission boundary is a security constraint, not a bug.

**Elevation steps:**
1. Log in to UniFi OS console as an account with existing SuperAdmin access
2. Navigate to Users → find the MCP service account (e.g., `homebridge`)
3. Change role to **SuperAdmin**
4. Log out and back in with the service account to mint a fresh session token
5. Re-test: `GET /api/v2/alarms/profiles` should now return 200

**Security implication — document clearly:** SuperAdmin has full blast-radius across
the UniFi OS console, not just Protect. Recommendation: use a dedicated SuperAdmin
service account for alarm-v2 operations rather than reusing the general homebridge
credential. Never silently assume the operator understands this.

**Graceful degradation is non-negotiable.** The façade's `AlarmManagerPermissionError`
and `BadRequest` catch ensures the MCP server remains fully functional with legacy
alarm coverage even without SuperAdmin. Never make SuperAdmin a hard requirement —
make it the path to full coverage, with the `_meta` signal marking the difference.

**Distinguishing 403 from 404:**
- `403 Forbidden` from `/api/v2/` → permission boundary (account needs elevation)
- `404 Not Found` → routing failure (wrong path or service unavailable)
- Do not mistake a 403 for a routing or header problem — confirm account role before
  investigating headers.

## Cross-Cutting Gotchas

**Silent gaps are worse than explicit errors.** An agent listing alarm rules from
the legacy backend and receiving 52 results has no idea it's missing AI-NL alarms.
Always emit `_meta` when coverage is partial — never let incomplete results look
complete.

**Never let v2 appear in tool names or user-visible identifiers.** The moment you
expose `_v2_` in a tool name, every future API version forces a new tool family. The
façade pattern exists precisely to prevent this. Internal code may reference v2 paths
(they're URLs — facts), but the public MCP tool surface must be version-agnostic.

**Test both permission levels explicitly.** The façade's fallback path is only
exercised when SuperAdmin is absent. In CI, mock `AlarmManagerPermissionError` or
`BadRequest` for fallback tests — don't assume real credentials will always be
SuperAdmin.

**Apply `api_request_raw` proactively.** Before shipping any new DELETE or
discarded-response POST endpoint in a Protect manager, check whether the controller
returns an empty body on success. Probe with `api_request_raw` first if uncertain.

**Future surface candidates.** Arm/disarm profiles (`/api/v2/alarms/profiles`) are
the next candidate for dual-surface exposure if a legacy Protect path is ever added.
The same façade pattern applies: map the surfaces, determine subset relationship,
implement version-transparent backend selection with graceful degradation.
