---
name: myco:mcp-response-redaction-governance
description: |
  Use this skill whenever you're adding, changing, or reviewing sensitive-field
  disclosure behavior on an MCP tool or API response — even if the user just
  asks to "expose this field" or "let callers opt into raw data." Covers:
  configuring per-surface redaction via redact_sensitive_fields and its
  env-var hierarchy (should_redact_sensitive_fields in unifi-core), the two
  real, separately-owned policy mechanisms in unifi-core (PolicyGateChecker
  for mutation gates, the redaction resolver for response disclosure) and how
  to extend either for a new domain, the two distinct enforcement points
  (per-tool/per-route redaction application vs. the StrictKwargFastMCP.call_tool
  write-back marker guard), and migrating legacy include_sensitive-style
  caller flags to server-owned policy. Trigger this any time a change would
  let a request argument control whether secrets/tokens/sensitive fields are
  disclosed in a response — that decision belongs to server/operator policy,
  never to the caller.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# MCP Response Redaction Governance

This domain covers how sensitive-field disclosure (secrets, tokens, raw
credentials) is controlled across MCP tools and API responses. The
governing principle: **request intent is not authorization**. A caller
argument like `include_sensitive=true` expresses what the caller wants,
but only server/operator policy decides whether to honor it. Never let a
per-call argument directly gate secret disclosure.

## Prerequisites

- Know which surface you're touching: an MCP product server
  (`network`/`access`/`protect`) or the REST API (`api`). Each surface has
  its own env-var prefix and resolves the redaction decision at a
  different point in the request lifecycle (see Procedure A).
- Do not assume a single unified "PolicyEngine" class exists. Check
  `packages/unifi-core/src/unifi_core/policy.py` and
  `packages/unifi-core/src/unifi_core/policy_gate.py` directly — there are
  two separate mechanisms, not one (see Procedure B).
- Locate the correct enforcement point for what you're changing: read-path
  redaction and the mutation write-back guard are two different checks in
  two different files (see Procedure C). Don't assume one covers the other.

## Procedure A: Configuring redaction policy per surface

Sensitive-field disclosure is controlled by a boolean, named for the
enforced behavior rather than a data format:

```yaml
policy:
  response:
    redact_sensitive_fields: true  # default; true = redact secrets
```

Naming rationale: `redact_sensitive_fields: true|false` is clearer than
alternatives like `sensitive_fields: redacted|raw`, because the operator
is deciding *whether the server redacts*, not choosing an output format.
Keep this convention when adding new redaction toggles.

The boolean is resolved by `should_redact_sensitive_fields(server_prefix,
config, env)` in `packages/unifi-core/src/unifi_core/policy.py`, in this
order (highest specificity wins):

1. `UNIFI_{SURFACE}_REDACT_SENSITIVE_FIELDS` — per-surface env override
   (e.g. `UNIFI_NETWORK_REDACT_SENSITIVE_FIELDS`,
   `UNIFI_API_REDACT_SENSITIVE_FIELDS`)
2. `UNIFI_REDACT_SENSITIVE_FIELDS` — global env fallback
3. `policy.response.redact_sensitive_fields` from the surface's own config
4. Default: `true` (redact) if nothing is set — safe-by-default

**Resolution timing differs by surface — check this before assuming a live
env-var change takes effect:**

- **MCP surfaces**: each app defines a local `should_redact_sensitive_fields()
  -> bool` binding function in its own runtime module — e.g.
  `apps/network/src/unifi_network_mcp/runtime.py`,
  `apps/access/src/unifi_access_mcp/runtime.py`,
  `apps/protect/src/unifi_protect_mcp/runtime.py` — that calls the shared
  resolver on every invocation. Because MCP tool functions call this
  binding at the top of each call, an env-var change takes effect on the
  next tool call with no restart.
- **API surface**: `apps/api/src/unifi_api/config.py` calls
  `should_redact_sensitive_fields("api", config=container)` once, inside
  `load_config()`, and caches the result on `ApiConfig.policy.response
  .redact_sensitive_fields`. Routes then read that cached attribute per
  request. Changing `UNIFI_API_REDACT_SENSITIVE_FIELDS` or
  `UNIFI_REDACT_SENSITIVE_FIELDS` for the API surface requires a process
  restart to take effect — it is not re-resolved per request.

When adding a new surface, add its per-surface env var to the same
hierarchy rather than hardcoding a local redaction flag, and decide
deliberately whether the new surface resolves per-call (like MCP) or at
config-load time (like the API) — don't silently inherit whichever
pattern is closest by copy-paste.

## Procedure B: Extending policy for a new domain — pick the right existing shape

There is **no single unified policy engine class**. Two separate
mechanisms live in `unifi-core`, and each new policy question should be
modeled as one more instance of whichever shape fits, not a third bespoke
mechanism:

1. **Gate checks** (`PolicyGateChecker` in
   `packages/unifi-core/src/unifi_core/policy_gate.py`) answer "is this
   category/action combination allowed?" via a 3-level env-var hierarchy:
   `UNIFI_POLICY_<SERVER>_<CATEGORY>_<ACTION>` →
   `UNIFI_POLICY_<SERVER>_<ACTION>` → `UNIFI_POLICY_<ACTION>` → allowed by
   default. Use this shape for new allow/deny gates on categorized
   actions (mutation authorization is the existing example via
   `.check(category, action)`).
2. **Resolvers** (`should_redact_sensitive_fields` in
   `packages/unifi-core/src/unifi_core/policy.py`) answer "what is the
   value of this policy setting for this surface?" via the per-surface →
   global → config → default hierarchy described in Procedure A. Use this
   shape for a typed value (not just allow/deny) that varies by surface.

To add a new domain:

1. Decide whether the question is a categorized allow/deny gate or a
   surface-scoped value resolver, and follow the matching precedent file
   above rather than writing a new env-var precedence scheme from
   scratch.
2. Put the resolver/checker itself in `packages/unifi-core` so every
   product package shares one implementation.
3. If a shared per-surface convenience wrapper is useful — as
   `should_redact_response_sensitive_fields` in
   `packages/unifi-mcp-shared/src/unifi_mcp_shared/response_policy.py`
   does for redaction — add it in `packages/unifi-mcp-shared`, and bind it
   per surface with a thin `should_redact_sensitive_fields() -> bool`
   function inside that surface's own runtime module (following
   `apps/network/src/unifi_network_mcp/runtime.py` as the template) rather
   than having every tool call the generic resolver with a hardcoded
   surface string.

**Gotcha:** design discussions for this domain have proposed unifying
gate-checks and resolvers under one `PolicyEngine`/`PolicyContext`
interface. That interface does not exist in the codebase today — verify
with `grep -r PolicyEngine` before writing code or docs that assume it
does, and don't reintroduce it without also migrating both existing
mechanisms onto it in the same change.

## Procedure C: Enforcing redaction and the write-back guard — two different checks

These are separate mechanisms enforced in separate places. Don't assume
fixing one covers the other.

**1. Read-path redaction (per-tool / per-route, not centralized):**
Every read tool/route resolves the boolean early and passes it explicitly
into `redact_sensitive_fields(payload, redact_sensitive=...)` (defined in
`packages/unifi-core/src/unifi_core/redaction.py`) when shaping its
response:

```python
# MCP tool (e.g. apps/network/src/unifi_network_mcp/tools/system.py)
redact_sensitive = should_redact_sensitive_fields()
return redact_sensitive_fields({...}, redact_sensitive=redact_sensitive)

# API route (e.g. apps/api/src/unifi_api/routes/actions.py)
redact_sensitive = request.app.state.config.policy.response.redact_sensitive_fields
shaped = redact_sensitive_fields(result.payload, redact_sensitive=redact_sensitive)
```

This call is **not applied automatically by a middleware or dispatcher**
— every new read tool, route, serializer, or GraphQL resolver that
returns a payload with potentially sensitive fields must call it
explicitly. When adding a new read surface, grep sibling tools/routes in
the same file for `redact_sensitive_fields(` to find the local pattern to
follow, and confirm the new code path actually calls it (a missing call
is the most likely regression, not a wrong env var).

**2. Write-back marker guard (centralized in MCP transport):**
`StrictKwargFastMCP.call_tool`, implemented in
`packages/unifi-mcp-shared/src/unifi_mcp_shared/strict_dispatch.py`,
inspects incoming tool arguments via `redaction_marker_paths()` (defined
in `packages/unifi-core/src/unifi_core/redaction.py`) and rejects any
argument that still carries the redaction marker value, so a caller can't
round-trip a previously-redacted response field back as if it were a real
update. This *is* centralized — but it only covers the "marker submitted
as new data" case, not the read-redaction decision above.

The API surface has an analogous but separate guard: it rejects any
`include_sensitive` key present in the request args outright — see
`apps/api/src/unifi_api/services/actions.py` and
`apps/api/src/unifi_api/routes/actions.py` — rather than doing
marker-pattern detection.

When reviewing a redaction-related change, check both mechanisms
independently: does every new read path call `redact_sensitive_fields()`,
and (for MCP) is the new tool's manifest/schema covered by the marker
write-back check so a redacted field can't be replayed as a mutation
input?

## Procedure D: Migrating away from `include_sensitive`-style caller flags

If you find an existing tool/API parameter that lets a caller request
raw/unredacted data directly (e.g. `include_sensitive=true`), migrate it
to server-owned policy:

1. Remove the caller-controlled parameter from the public tool schema /
   API request shape entirely — do not just gate it, remove it. Leaving
   it present but "gated" still collapses request-intent and
   authorization into one flag.
2. Replace any internal use of the old flag name with redaction-oriented
   naming: `should_redact_sensitive_fields()`,
   `should_redact_response_sensitive_fields()`, `redact_sensitive=True|False`
   at the actual redaction boundary in `redact_sensitive_fields()`. Do not
   carry the old `include_sensitive` name forward as an internal helper
   pattern.
3. Compute any internal "include sensitive" boolean, if still needed
   downstream, as `not redact_sensitive_fields` derived purely from
   server policy — never from a caller-supplied value.
4. If the surface still needs to reject a caller attempting to pass the
   old parameter (rather than silently ignoring it), return an explicit
   error naming the correct replacement env var/config key — see the
   unsupported-argument error constant defined in
   `apps/api/src/unifi_api/services/actions.py` — instead of silently
   dropping the argument.
5. Coordinate the change across every package that touches the response
   path (the shared policy resolver, each MCP product server, and the
   REST API) — a partial migration reintroduces the caller-controlled
   disclosure gap on the surfaces left behind.

## Cross-Cutting Gotchas

- **Two mechanisms, not one**: gate checks (`PolicyGateChecker`) and
  resolvers (`should_redact_sensitive_fields`) are independent code paths
  in `unifi-core` today. A fix or extension to one does not automatically
  apply to the other — check both when auditing policy coverage.
- **Resolution timing varies by surface**: MCP resolves per call; the API
  surface resolves once at config-load time and caches it (see Procedure
  A). Don't assume a live env-var override works identically on every
  surface — verify against the surface's actual resolution point.
- **Safe-by-default**: if no policy signal is present anywhere in the
  hierarchy, the system must default to redacting. Never default to
  disclosure.
- **Read-redaction vs. write-back guard are different checks**: fixing a
  bug in the read-path `redact_sensitive_fields()` call site does not
  touch the `StrictKwargFastMCP.call_tool` marker guard, and vice versa.
  Test both independently when changing either.
- **Don't invent a third policy shape**: before adding any new
  server-side policy check, decide whether it's an allow/deny gate
  (`PolicyGateChecker` shape) or a surface-scoped value (resolver shape),
  and extend the matching existing mechanism in `packages/unifi-core`.
- **Secret-vocabulary boundary vs. logging hygiene**: CodeQL's
  clear-text-logging-sensitive-data alert rule, applied to Network
  client/device managers and tools, typically flags MAC-address logger
  arguments, not leaked passwords or tokens. `unifi_core.redaction`
  intentionally targets secret key material and leaves inventory
  identifiers (MAC addresses, serials) readable — that's a separate
  boundary from this domain's secret-field redaction pattern. Don't add
  inventory identifiers to the redaction vocabulary to silence these
  alerts; fix the logging call site instead.
- **Exception text is a disclosure surface too**: error-classification /
  support-bundle code must never serialize a raw exception's text or
  status property back into a response — a hostile exception subclass can
  carry sensitive data via its message or attributes
  (`test_error_classification_never_serializes_exception_text` guards
  this). Treat exception serialization as another redaction-adjacent
  boundary alongside tool/route payloads, not something the read-path
  `redact_sensitive_fields()` call alone covers.

## Historical context

This governance model was established while closing a reported weakness
where a per-call caller-supplied flag could influence sensitive
disclosure directly. The fix removed the caller-controlled parameter from
public surfaces in favor of the `redact_sensitive_fields` config/env
model in Procedure A, and added the write-back marker guard in Procedure
C. Design discussion during that work proposed unifying mutation-gate and
response-disclosure policy under one `PolicyEngine`/`PolicyContext`
interface; that unification was the intended end-state but has not
shipped — the codebase still has the two separate mechanisms described in
Procedure B. Treat any reference to a single "PolicyEngine" as
aspirational until it is actually merged, and verify against the
`unifi-core` policy modules directly.
