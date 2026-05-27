---
name: add-integration-api-tool
description: >
  Use this skill when adding any tool that talks to the UniFi public Integration API
  (X-API-Key auth, /proxy/network/integration/...). The integration API uses a
  different ID namespace and field schema from the V2 controller API, so these tools
  form their own "families" with scoped IDs. Covers when to start a new family vs
  join an existing one, how to scope IDs in tool descriptions, the narrow conditions
  under which silent ID translation is allowed (rare), how to wire auth, and how to
  bridge between ID spaces (explicit named bridging tools only). Applies whether
  you are adding a read tool, a mutation tool, or a paired family of both.
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Adding a Tool That Uses the UniFi Integration API

The UniFi controller exposes two API surfaces. They are not interchangeable.
Skipping this distinction creates silent footguns where IDs from one API are
accepted by tools backed by the other and silently fail — or worse, succeed
against the wrong resource.

## The two surfaces

| | V2 controller API | Integration API |
|---|---|---|
| Auth | session cookie | `X-API-Key` header |
| Path prefix | `/proxy/network/api/...`, `/proxy/network/v2/api/...` | `/proxy/network/integration/v1/...` |
| IDs | Mongo ObjectIDs (`674f0...`) | UUIDs (`0998be5a-...`) |
| Field naming | `snake_case` | `camelCase` |
| Action shape | `"action": "ALLOW"` + flat fields | nested `{"action": {"type": "ALLOW", "allowReturnTraffic": true}}` |
| `ip_version` | `"BOTH"` | `"ipProtocolScope": {"ipVersion": "IPV4_AND_IPV6"}` |
| Coverage | everything the web UI uses | curated, expanding subset |
| Membership | full controller state | filtered (system policies often excluded) |

These differences are not cosmetic. The same logical resource appears in V2
with a Mongo ID and in Integration with a UUID, with no native bridge field
connecting them.

## Step 1: Identify the family

A *tool family* is a set of tools whose returned IDs and accepted IDs are
interchangeable.

- Reading + writing to the same API endpoint group? Same family.
- Reading from V2 and writing to V2? Same family (the existing firewall
  policy CRUD family).
- Reading from Integration and writing to Integration? Same family.
- Mixing? You're inventing a bridging tool — see Step 5.

**Current families in this codebase:**

| Family | API | IDs | Tools |
|---|---|---|---|
| Firewall policy CRUD | V2 | Mongo | `unifi_list_firewall_policies`, `unifi_get_firewall_policy_details`, create / update / delete / toggle |
| Firewall policy ordering | Integration | UUID | `unifi_get_firewall_policy_ordering` + `unifi_reorder_firewall_policies` |

If your new tool fits cleanly inside an existing family, join it. If not,
start a new family — and document its boundary.

## Step 2: Scope IDs in the tool description

Any tool that returns IDs which could be confused with another family's IDs
MUST include a scoping clause in its `description`. This applies to:

- MCP tool descriptions (`@server.tool(description=...)`)
- GraphQL type and query descriptions (`@strawberry.type(description=...)`, `@strawberry.field(description=...)`)
- REST route descriptions (`@router.get(description=...)`)

Standard formula:

> *"These IDs are scoped to the &lt;family-name&gt; tool family — do not
> pass them to other &lt;resource&gt; tools."*

Canonical example from the ordering family:

```python
@server.tool(
    name="unifi_get_firewall_policy_ordering",
    description=(
        "Get user-defined firewall policy ordering for a source/destination "
        "firewall zone pair. Returns policy IDs from the UniFi public integration "
        "API (UUIDs); these IDs are scoped to the ordering tool family — pass them "
        "ONLY to unifi_reorder_firewall_policies. They do NOT correspond to the "
        "policy IDs returned by unifi_list_firewall_policies or any other "
        "controller-API firewall tool."
    ),
    ...
)
```

The scoping clause is not optional for integration-API tools.

## Step 3: Require the API key, with clear remediation

Integration API endpoints reject session-cookie auth. Without the API key,
the tool MUST fail with a remediation message. Put the check in the manager
so every tool in the family inherits it:

```python
if self._auth is None or not self._auth.has_api_key:
    raise RuntimeError(
        "<feature> requires a UniFi API key. "
        "Create a Network API token in UniFi Control Plane -> Integrations "
        "and set UNIFI_API_KEY or UNIFI_NETWORK_API_KEY for the MCP."
    )
```

See `firewall_manager.py:_request_integration_api` for the canonical
implementation.

## Step 4: Silent ID translation — when allowed, when banned

**Banned by default.** Silently translating between V2 and Integration ID
spaces inside a tool is forbidden because the underlying mapping is rarely
1:1.

**Grandfathered exception: zones.** PR #301 translates V2 zone IDs to
Integration zone UUIDs internally via `_get_integration_firewall_zones`.
This is allowed *only* because zones meet all three criteria:

- **1:1**: every V2 zone has exactly one Integration zone and vice versa
- **Stable**: changes via either API remain consistent
- **Deterministic**: zone names are unique and stable bridge fields

**Do not extend the silent-translation pattern** to a new resource without
verifying these three criteria against live data. The data for policies
fails all three (180 V2 vs 25 Integration; 8 duplicate names in V2; no
bridge field in Integration's `metadata`).

## Step 5: When you genuinely need to bridge ID namespaces

Rare. But if a workflow requires it: write a named bridging tool. The
bridge is visible in the API surface and its failure modes are
documented:

```python
@server.tool(
    name="unifi_resolve_policy_id_for_ordering",
    description=(
        "Look up the integration-API ordering UUID for a V2 firewall policy. "
        "Returns None when the policy has no Integration-API representation "
        "(e.g., predefined system policies, IP-group-referenced policies). "
        "This is the only sanctioned bridge between the firewall policy CRUD "
        "family and the firewall policy ordering family."
    ),
    ...
)
```

Don't bury translation inside other tools. Make the bridge first-class.

## Step 6: Tests

Cover the family boundary explicitly:

- **Auth requirement** — tool fails fast without an API key, with the
  remediation message. Anchor: `test_firewall_manager.py::test_ordering_requires_api_key`.
- **Scoped IDs** — for ordering-style tools, the response contains
  integration UUIDs (not V2 IDs) and downstream tools in the family accept
  them.
- **Bridge failure modes** — if you wrote a bridging tool (Step 5), every
  failure mode (missing-in-target, name collision, etc.) has a test.

## Step 7: Doc surface

In the skill docs for the resource category, group integration-API tools
together. They share a contract; the doc should make that obvious. Don't
interleave them with V2 tools in the listing.

For the API server (REST + GraphQL), the same scoping rules apply to the
operation/route descriptions. After editing those, regenerate the
OpenAPI spec and reference docs via `make pre-commit`.

## Reference implementation

`apps/network/src/unifi_network_mcp/tools/firewall.py` — the ordering
family.

Read these elements before writing your own:

- The two tool descriptions scoping the UUIDs
- The shared API-key requirement at the manager layer
  (`_request_integration_api`)
- The zone-ID translation (`_get_integration_firewall_zones`) — the *only*
  sanctioned silent translation
- That the family is exactly two tools with no cross-family entry points

## Enforcement note

Family scoping is currently *guidance*, not runtime/type enforcement.
Cross-family ID misuse fails at the controller (400 from the integration
API) and surfaces as a tool error. The agent reads the scoping clause in
the tool description and routes IDs accordingly.

Stronger enforcement options (typed IDs via `NewType`, runtime regex
validation, a `family` field in `tools_manifest.json`) are deliberately
deferred until the integration-API surface grows beyond the current single
family. If you find yourself adding a second integration-API family,
reopen this question.

## Related rules

- AGENTS.md → `### API Surface Boundaries` (terse statement of the rule)
- Myco decision spore `architecture-d44806fa` (full reasoning + live data)
