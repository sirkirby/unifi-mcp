---
name: myco:protect-alarm-facade
description: |
  Use this skill when implementing or extending Protect Alarm Manager features that
  span the dual API surfaces (/api/v2/alarms/ vs /proxy/protect/api/automations),
  when designing or extending AlarmRulesFacade with new operations, when routing
  alarm rule mutations by ID family (UUIDv7 to v2 service, 24-hex Mongo ObjectID to
  legacy automations), when writing alarm rule serializers that must translate between
  legacy (name/conditions/enable) and v2 (title/triggers/enabled) vocabularies, when
  adding delete or merge operations that discard response bodies (use api_request_raw),
  when preserving the require_non_empty_actions guard through any refactor, when
  planning phased delivery of read-only vs mutation capabilities, or when preparing to
  implement mutations against an unknown endpoint (capture-first). Apply even if the
  user doesn't explicitly ask about dual surfaces or facade design — any Protect alarm
  rule CRUD work activates this skill.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Protect Alarm Manager Facade: Dual-Surface Design and Mutation Safety

Protect's Alarm Manager is served by two completely separate API services on different
paths. `AlarmRulesFacade` abstracts this complexity: it selects the best available
backend at call time, normalizes to a canonical model, and gives callers a single stable
interface. This skill covers every phase of that work — from discovering the surfaces to
implementing safe mutations with the invariants that prevent live UI breakage.

## Prerequisites

- **SuperAdmin credentials** are required to reach the `/api/v2/alarms/` UniFi OS
  service. Regular admin or viewer accounts receive a `PermissionError`. This is a
  genuine security constraint, not a uiprotect bug.
- **Capture before Phase 3 mutations**: v2 create/update/delete request shapes are
  unknown until captured from a live console. Do not implement against assumed shapes —
  capture the raw HTTP exchange first (see Procedure 7).
- Familiarity with the `uiprotect` client methods: `api_request()` and
  `api_request_raw()`.

## Procedure 1: Dual-Surface Discovery

When you encounter a Protect feature that may span legacy and UniFi OS APIs, map both
surfaces before writing any code. Confirm the contents, auth requirements, and ID
format for each.

**The two alarm surfaces:**

| Path | Service | Contents | ID format |
|---|---|---|---|
| `/proxy/protect/api/automations` | Protect private API | Legacy rules only (~52 automation rules) | 24-hex Mongo ObjectID |
| `/api/v2/alarms/` | UniFi OS service | All rules + AI-NL alarms + arm profiles | UUIDv7 (36-char) |
| `/api/v2/alarms/protect` | UniFi OS service | Full rules superset for Protect | UUIDv7 |
| `/api/v2/alarms/profiles` | UniFi OS service | Arm/disarm profiles | UUIDv7 |
| `/proxy/protect/api/automationManager/external/...` | Protect private | Automation rules view | Mongo ObjectID |

**Critical data asymmetry:** The legacy API is a strict subset of v2. Every legacy rule
appears in v2, but v2 adds AI natural-language alarms (e.g., "Dog Poop") that the legacy
API cannot represent. Before PR #320, `protect_alarm_list_rules` silently omitted all
AI-NL alarms — agents saw a partial picture with no signal.

**Routing v2 calls:** Use the existing uiprotect client — no bespoke HTTP client needed:

```python
await self._api.api_request(api_path="/api/v2/alarms/", url="...")
```

**Verify with a live round-trip before committing to a schema.** A live check on a
v2-migrated console confirmed the asymmetry: 53 UUIDv7 rules on v2, 52 Mongo ObjectID
rules on legacy (one AI-NL rule exists only in v2).

**Next dual-surface candidate:** Arm/disarm profiles (`/api/v2/alarms/profiles`) follow
the same pattern. Apply this same procedure when implementing profile tools.

## Procedure 2: AlarmRulesFacade Design

When a feature's data lives on multiple incompatible API surfaces, use a **façade with
automatic backend selection** — never version-named tools. MCP tools describe capability,
not implementation. Version leaks are a maintainer concern, not a caller concern.

**Facade selection logic:**

```
protect_alarm_list_rules / protect_alarm_get_rule
        ↓
  AlarmRulesFacade          ← version-transparent entry point
   ├── tries AlarmManagerService (v2: /api/v2/alarms/)
   │   ├── SuperAdmin → full data (legacy + AI-NL alarms) → complete=True
   │   ├── PermissionError (403) → falls back to legacy
   │   └── success=True AND rules=[] → ALSO falls back (unmigrated console)
   └── falls back to legacy automations (/proxy/protect/api/automations)
        → legacy rules only, emits _meta coverage signal
```

> **Gotcha — "200 OK + empty list" must also trigger fallback (PR #334):** A fallback
> keyed only on HTTP error codes misses unmigrated consoles where v2 returns `HTTP 200
> []`. PR #320 had this bug: the facade saw `[]`, treated it as "v2 has zero rules", and
> never queried legacy. The fix (PR #334, commit `557e267`): if `success=True AND
> rules=[]`, also fall back. Always consider whether "success but empty" should trigger
> degradation alongside error codes.

**Three-state console coverage after the fix:**
- SuperAdmin + migrated: v2 returns rules → serve v2 (`complete=True`)
- SuperAdmin + unmigrated: v2 returns `200 []` → fall back to legacy (52 rules)
- Non-SuperAdmin: v2 returns `403` → fall back to legacy

**Coverage signal (emitted on legacy fallback only):**

```python
{"_meta": {"io.unifi-mcp/alarm-rules/backend": "legacy",
            "io.unifi-mcp/alarm-rules/coverage": "partial"}}
```

Uses the project's `io.*` reverse-DNS namespace convention. SuperAdmin v2 responses
omit `_meta` entirely. This pattern is established for any tool that may silently serve
partial data due to backend limitations.

**Canonical model:** `AlarmRule` normalizes from either backend. Fields present only in
v2 (`enabled`, `created_at`, UUID `id`) are excluded via `exclude_none` when sourced
from legacy. Callers see a stable field contract regardless of backend.

**Internal naming rule — strip `v2` from all internal identifiers:**
- `AlarmV2Manager` → `AlarmManagerService`
- `alarm_rule_v2_from_controller` → `alarm_rule_from_controller`

The literal `/api/v2/alarms/` path in routing code is preserved — it's a real URL, not
a naming choice. Version names in class names or tool names force callers to reason about
API internals and create parallel families that must stay in sync.

**Why not `protect_alarm_v2_list_rules`:** It leaks implementation to agents, creates a
naming obligation to add `protect_alarm_v2_*` variants for every operation, and breaks
the principle that tools describe capability not backend version.

## Procedure 3: Mutation Routing by ID Family

Phase 3 extends `AlarmRulesFacade` to own **all CRUD mutations**. No mutation tool
bypasses the facade. Routing is deterministic at call time based on the ID format the
agent passes back from a prior `list`/`get`.

**ID family → backend mapping:**

| ID format | Example | Backend |
|---|---|---|
| UUIDv7 (36-char) | `019e89f0-8fc0-7141-9a64-7eb3f5746148` | v2 UniFi OS service (`/api/v2/alarms/`) |
| 24-hex Mongo ObjectID | `674f3052cdbf2c191e0a01b7` | Legacy Protect automations |

**Why this is safe:** An agent cannot invent an ID — it received it from a prior tool
call. The ID it returns encodes exactly which backend owns it. No read-before-write probe
is needed for update or delete.

**Update/Delete — deterministic routing by format** (actual implementation in
`alarm_facade.py`):

```python
# Module-level compiled regex
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

@staticmethod
def _id_family(rule_id: str) -> str:
    """Route by id: v2 UUIDs go to the Alarm Manager, everything else to legacy."""
    if not isinstance(rule_id, str) or not rule_id.strip():
        raise ValueError("Alarm rule id must be a non-empty string")
    return "v2" if _UUID_RE.match(rule_id) else "legacy"
```

**Create — explicit read probe (no prior ID):**
1. Probe v2 read reachability (same selection logic as `list_rules` via `_v2_write_available()`)
2. If SuperAdmin + v2 available → create via v2
3. Else → create via legacy

The probe is explicit (not lazy) so create commits to one backend before executing.

> **Open regression pending Phase 3:** PR #320 moved `list_rules`/`get_rule` to v2
> while leaving mutation tools wired to the legacy backend directly. On any SuperAdmin +
> migrated console, all alarm rule mutations fail silently: agent receives a UUIDv7 from
> `list_rules`, passes it to `update_rule`, legacy `get_rule` returns
> `UniFiNotFoundError` with no useful diagnostic.
>
> **Triage tell:** `UniFiNotFoundError` on `protect_alarm_update_rule`/`delete_rule`
> combined with `complete=True` on `protect_alarm_list_rules` = this exact bug. Phase 3
> (extending the facade to own mutations) is the proper fix — no interim guard was opened
> per maintainer decision.

This routing pattern is consistent with the dual-API surface governance pattern for
firewall V2 vs Integration API ID families.

## Procedure 4: Write Schema Vocabulary Translation

The v2 and legacy backends use **fundamentally different field names** for mutations —
not just different ID formats. `rule_to_controller` (alarms.py:481) does **not** bridge
them; it only performs snake→camel renames within the legacy vocabulary.

**Divergence table:**

| Concept | Legacy (`/proxy/protect/api/automations`) | v2 (`/api/v2/alarms/`) |
|---|---|---|
| Rule name | `name` | `title` |
| Enabled flag | `enable` | `enabled` |
| Trigger events | `conditions` | `triggers` |
| Sources | `sources` | `scope.sources` |
| Actions | `actions` | `actions` |
| Legacy-only field | `cooldown` | — |

A plan that routes through a unified facade and assumes `rule_to_controller` handles
both backends will **silently send malformed bodies** to the legacy path (it sends
`name`/`conditions`, not `title`/`triggers`, and never reaches the v2 vocabulary).

**The fix:** Implement a dedicated `alarm_rule_to_legacy_body` — a genuine inverse of
`alarm_rule_from_legacy`, not a reuse of `rule_to_controller`. Use the canonical write
shape (`title`/`enabled`/`triggers`/`scope`) at the facade surface, then translate for
each backend path. Both functions live in
`packages/unifi-core/src/unifi_core/protect/models/alarm_rules.py`.

**Legacy serializer inverse — echo `data` verbatim:**

`alarm_rule_from_legacy` does NOT decompose nested `conditions`/`actions` elements. It
stores the **entire nested legacy dict** verbatim in the `data` field with
`trigger_id=None`:
- Each `conditions` element `{"condition": {...}}` → `trigger_id=None, data={"condition": {...}}`
- Each `actions` element `{"type": "HTTP_REQUEST", ...}` → `data={"type": "HTTP_REQUEST", ...}`

The inverse serializer must therefore echo `data` verbatim — **not** reconstruct
`{"type": condition.trigger_type, **condition.data}` (that's wrong because `trigger_type`
is `None` for legacy conditions):

```python
def alarm_rule_to_legacy_body(rule: AlarmRule) -> dict:
    return {
        "name": rule.title,          # canonical title → legacy name
        "enable": rule.enabled,      # canonical enabled → legacy enable
        "conditions": [c.data for c in rule.conditions],  # echo verbatim
        "actions":    [a.data for a in rule.actions],      # echo verbatim
        # ... other fields
    }
```

> **Gotcha — fabricated tests mask this:** A hand-crafted flat fixture can accidentally
> round-trip because it lacks the nested legacy structure. Only testing against a **real
> captured legacy fixture** catches the structural mismatch (round-3 review finding RB1).
> Test serializers against real captured data from the start.

**Fetch-merge-PUT pattern for updates (both backends):**
1. **Fetch** the raw body from the owning backend (identified by ID family)
2. **Merge** caller's changes into that raw body
3. **PUT** the merged raw body back to the same backend

The facade is the locus of this entire operation. Never pass pre-parsed or pre-transformed
data to mutation helpers — if helpers receive already-transformed data, serialization can
silently corrupt fields across the v2/legacy vocabulary mismatch.

**Why lossy round-trip is acceptable:** `cooldown` and legacy-only `conditions`
substructure have no canonical home. Fetch-merge-PUT preserves them by merging canonical
changes into the raw legacy body rather than replacing it wholesale.

## Procedure 5: api_request_raw for Discarded Responses

Several Protect mutation endpoints return an **empty body** on success. `api_request()`
unconditionally calls `response.json()`, which throws `Could not decode JSON` on `b""`
— the operation succeeds but the caller sees a spurious error.

**Use `api_request_raw` whenever the response body is discarded:**

```python
# Broken: empty response → JSON decode error
await self._api.api_request("delete", url, raise_exception=True)

# Fixed: handles empty bytes cleanly, zero data loss
await self._api.api_request_raw("delete", url, raise_exception=True)
```

**Known affected methods (all fixed as of PRs #316, #319, #321):**

| Method | Endpoint | PR |
|---|---|---|
| `apply_delete_known_face` | DELETE `/proxy/protect/api/recognition/face/groups/{id}` | #319 |
| `apply_delete_known_vehicle` | DELETE vehicle group | #316 |
| `apply_merge_known_faces` | POST `/recognition/face/groups/merge` | #321 |

All three discard the response body — they return a pre-operation preview snapshot.
`api_request_raw` is always safe for these callers.

**Live confirmation (PR #319, group id `6a1f1b0d02084103e428b998`):**

```
DELETE (api_request_raw): deleted=True  raw_type=bytes  body=None  ← empty body confirmed
AFTER: UniFiNotFoundError → group deleted (operation succeeded)
```

**When auditing new delete/merge calls:** Search for `api_request("delete"` and
`api_request("post"` across Protect managers. If the caller discards the return value,
it must use `api_request_raw`. All `method="delete"` calls in Protect managers now use
`api_request_raw` — maintain this invariant for new additions.

## Procedure 6: require_non_empty_actions Mutation Guard

**Live-tested gotcha (2026-05-27):** Creating an alarm rule with an empty `actions` list
via the API produces a rule that **breaks the Protect UI** — the UI becomes non-functional
and the corrupted rule **can only be deleted via the API**, not through the UI.

`require_non_empty_actions` (defined in
`packages/unifi-core/src/unifi_core/protect/models/_validators.py`) is a non-negotiable
invariant. Apply it on the canonical `actions` field in the facade before any create or
partial-update that includes `actions`. The facade exposes it via the private wrapper
`_require_non_empty_canonical_actions` in `alarm_facade.py`.

**Placement rules:**

| Operation | Apply guard? | Reason |
|---|---|---|
| Create | Always | No rule should ever be created with empty actions |
| Update (partial, `actions` in change set) | Yes | Guard before routing to either backend |
| Update (partial, `actions` NOT in change set) | No | Don't block updates that don't touch actions |

**Guard location:** In the facade, on the canonical body, **before** either backend path
executes. This ensures the guard is backend-agnostic and survives any refactoring of the
input model layer.

**How it was almost lost:** During plan revision to unify the write contract, swapping
`AlarmCreateRuleInput`/`AlarmUpdateRuleInput` for `AlarmRuleWrite` silently dropped the
`require_non_empty_actions` call (round-2 review finding NB2). When refactoring input
models, **explicitly verify the guard is still applied** — the guard must travel with the
facade's canonical path, not with any specific input model class.

## Procedure 7: Phase-Based Delivery and Capture-First Discipline

**Deliver read-only capabilities before mutations.** Read paths have fewer safety
invariants and provide the live surface knowledge needed to implement mutations safely.
PR #320 delivered `list_rules`/`get_rule` via the facade; Phase 3 delivers mutations
only after the full architecture was designed and independently reviewed.

**Capture-first before implementing unknown mutation endpoints:**

When v2 create/update/delete request shapes are unknown:
1. Do **not** implement against assumed shapes — fabricated fixture tests will mask bugs
2. Open a capture session against a real console and record the raw HTTP exchange
3. Build the serializer and unit tests from the **real** captured fixture
4. Only then implement the mutation method

This is not process overhead — it is the only reliable way to discover structural
differences (like the write vocabulary divergence in §4) before they ship as silent
data corruption.

**Phased delivery checklist for any dual-surface Protect feature:**

1. ✅ Map both surfaces (paths, auth, ID formats, data overlap, asymmetries)
2. ✅ Implement facade with read operations and backend selection logic
3. ✅ Add `_meta` coverage signal for degraded (legacy fallback) path
4. ✅ Verify fallback triggers on both `403` **and** `200 []` cases
5. ✅ Capture raw HTTP exchange for all mutation endpoints before implementing them
6. ✅ Implement write schema translators tested against real captured fixtures
7. ✅ Add `require_non_empty_actions` guard in facade before routing
8. ✅ Extend facade to own all mutations: update/delete route by ID family; create uses read probe

## Cross-Cutting Gotchas

**Never version-name tools.** `protect_alarm_v2_list_rules` leaks implementation detail,
forces callers to reason about API internals, and creates a naming obligation to add
`v2` variants for every operation. Tools describe capability; the facade handles backend
selection transparently.

**ID spaces are non-overlapping.** v2 UUIDv7 IDs and legacy Mongo ObjectIDs share no
values. Feeding a v2 ID to the legacy backend returns `UniFiNotFoundError` with no
useful diagnostic. Feeding a legacy ID to v2 similarly fails. The facade must route;
callers must never bypass it.

**rule_to_controller is NOT a cross-backend serializer.** It performs snake→camel renames
within the *legacy* vocabulary only (alarms.py:481). It emits `name`/`conditions`, not
`title`/`triggers`. Using it on the v2 serialization path silently sends malformed bodies.

**Test serializers against real captured fixtures, not hand-crafted inputs.** Fabricated
flat structures can accidentally round-trip because they lack the nested legacy structure
(`{"condition": {...}}` inside `conditions`). Only real fixture data catches structural
mismatches in the serializer inverse.

**Fallback must handle both 403 and 200 [].** Any facade with graceful degradation needs
two fallback triggers: HTTP error codes *and* "success but empty." A 200-empty response
from an unmigrated service looks like success — it is not.
