---
name: myco:unifi-client-data-correctness
description: |
  Apply this skill whenever modifying, debugging, or extending UniFi client
  data retrieval in the unifi-mcp monorepo — even if the user doesn't
  explicitly ask about correctness or fallback behavior. Covers five
  permanent architectural fixtures of clients.py: (1) choosing the right
  endpoint (/stat/sta for live clients, /rest/user for offline or historical
  only); (2) preserving name and hostname as independent fields rather than
  collapsing with "or"; (3) deriving online status via the _is_online()
  uptime-field fallback when is_online is absent from the payload; (4)
  building a resilient fallback chain that never re-raises transient endpoint
  errors; (5) merging dual-source raw payloads with live data winning on
  overlapping keys. Verified against a live UDM SE controller (UniFi OS
  5.1.12 / Network App 10.3.58): 0/180 active clients carry is_online;
  121/445 clients have name and hostname set to different values.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# UniFi Client Data Retrieval Correctness

This skill covers the five correctness patterns required when reading, mapping,
or extending UniFi client data in the unifi-mcp monorepo. The patterns were
validated against a live UDM SE controller and surfaced four production bugs
(Issues #297–#298, PRs #299–#300) in a single release cycle. Each pattern is a
permanent fixture — violating any one of them silently corrupts client data for
a measurable fraction of real devices.

Primary files:
- `packages/unifi-core/src/unifi_core/network/models/clients.py` — model
  factories (`client_from_controller`, `blocked_client_from_controller`,
  `client_lookup_from_controller`) and the `_is_online()` helper
- `packages/unifi-core/src/unifi_core/network/managers/client_manager.py` —
  `get_client_details()` with dual-endpoint fallback and merge logic
- `apps/api/src/unifi_api/graphql/types/network/client.py` — Strawberry GraphQL
  types (`Client`, `BlockedClient`, `ClientLookup`) that mirror the Pydantic models

## Prerequisites

Before working on any client retrieval code, confirm:

1. You know which endpoint is the data source for the code path you are
   changing (`/stat/sta` vs `/rest/user`). The two have radically different
   field coverage; a change that is correct for one may be wrong for the other.
2. You have access to raw controller payloads (via `scripts/live_smoke.py
   --server network --phase readonly --tool unifi_list_clients`) to verify
   field presence. Do **not** assume field presence based on documentation or
   past experience — firmware variance is real.
3. Any bug report must include: controller hardware, UniFi OS version, Network
   Application version, and the raw API payload showing the unexpected value.
   Implement fixes only after the root cause is confirmed in the raw payload
   (not inferred from shaped output).

## Procedure 1: Choose the Right Endpoint

Use `/stat/sta` (active connections) as the primary source for client details.
Fall back to `/rest/user` (historical snapshots) only for offline clients or
transient failures. Never invert this order.

| Aspect | `/stat/sta` | `/rest/user` |
|--------|------------|--------------|
| Freshness | Current (controller polls ~every second) | Infrequently refreshed snapshot |
| Field count | 92+ (signal, channel, uptime, traffic, satisfaction…) | 7 (basic MAC/IP/name) |
| Online clients | ✅ Complete and current | ❌ Can lag hours or days |
| Offline clients | ❌ Not included | ✅ Historical record preserved |

**Why this matters:** Using `/rest/user` as the primary source means callers
receive stale IPs, missing signal data, and no real-time status — all silently,
with no error. The 85-field gap between the two endpoints is not a minor
difference.

**Implementation shape (see also Procedure 4):**

```python
from unifi_core.exceptions import UniFiNotFoundError

async def get_client_details(mac: str) -> dict:
    """Retrieve live client data with fallback to historical."""
    try:
        clients = await self.clients.update()  # /stat/sta — live
        for client in clients:
            if client.mac == mac:
                return client
    except Exception as e:
        logger.debug(f"Live endpoint failed: {e}; falling back to /rest/user")

    # Fallback: offline clients or transient failures
    all_clients = await self.manager.get_all_clients()  # /rest/user
    for client in all_clients:
        if client.mac == mac:
            return client

    raise UniFiNotFoundError("client", mac)
```

Apply this pattern in `unifi_get_client_details` and `unifi_list_clients`.
For `unifi_list_clients` with `include_offline=true`, hit `/stat/sta` first
for active clients, then union with `/rest/user` for the historical tail.

## Procedure 2: Preserve `name` and `hostname` as Independent Fields

Never collapse `name` (user-assigned alias) and `hostname` (DHCP device name)
with an `or` fallback. They are semantically independent and must be returned
as separate fields.

**The broken pattern — causes silent data loss:**

```python
# ❌ WRONG — used in all three factories before the fix
hostname=raw.get("hostname") or raw.get("name"),
```

When both fields are populated with different values, the user's alias (`name`)
is silently discarded. Live measurement: **121 of 445 clients (27%)** have
both fields set differently (e.g., alias "Living Room Harmony" vs. DHCP
hostname "HarmonyHub").

**The correct pattern:**

```python
# ✅ CORRECT — return both independently
name=raw.get("name") or None,
hostname=raw.get("hostname") or None,
```

**Scope — this bug appears identically in four places; all must be fixed
together:**

| Location | Factory / Type | Affected tool |
|----------|---------------|---------------|
| `clients.py` — `client_from_controller` | `Client` | `unifi_list_clients`, `unifi_get_client_details` |
| `clients.py` — `blocked_client_from_controller` | `BlockedClient` | `unifi_list_blocked_clients` |
| `clients.py` — `client_lookup_from_controller` | `ClientLookup` | `unifi_lookup_by_ip` |
| `graphql/types/network/client.py` — `from_manager_output` (×3) | Strawberry types | GraphQL layer |

All three Pydantic models require `name: Optional[str]`. All three Strawberry
types require a matching `name` field. A cross-layer symmetry test verifies
both layers agree.

**Verification:** After the fix, run the live smoke test and confirm that
`shaped.name` is populated on the affected records:

```bash
python scripts/live_smoke.py --server network --phase readonly --tool unifi_list_clients
```

## Procedure 3: Derive Online Status via `_is_online()` — Never Use `is_online` Directly

The `is_online` field is **absent from the `/stat/sta` payload on many
controller firmware versions**. Live measurement: **0 of 180 active clients**
on a UDM SE running UniFi OS 5.1.12 / Network Application 10.3.58 carried the
`is_online` field. Using it directly stamps all active clients as `"offline"`.

**The broken pattern:**

```python
# ❌ WRONG — all clients become "offline" when is_online is absent
status="online" if raw.get("is_online") else "offline",
```

**The correct pattern — use the `_is_online()` helper in `clients.py`:**

```python
def _is_online(raw: dict) -> bool:
    """Derive online status when is_online field is absent."""
    # Explicit field takes priority when present
    if raw.get("is_online") is True:
        return True
    # Fallback: any non-zero uptime field proves current connection
    for field in ["_uptime_by_uap", "_uptime_by_usw", "_uptime_by_ugw", "uptime"]:
        if raw.get(field, 0) > 0:
            return True
    return False
```

Then in each factory:

```python
status="online" if _is_online(raw) else "offline",
```

The GraphQL layer in `graphql/types/network/client.py` has an identical
`_is_online()` mirror — both must be kept in sync.

**Why uptime fields work:** On `/stat/sta`, the controller only returns records
for clients currently connected. Any non-zero uptime value is proof of active
connection right now. The payload also carries `tx_bytes-r`, `rx_bytes-r`, and
`satisfaction_now` as corroborating live indicators.

**Gotcha — `/rest/user` uptime fields are stale:** Historical records in
`/rest/user` may retain last-session uptime values after disconnect. The uptime
fallback is only reliable when the data source is `/stat/sta`. For historical
records, treat `is_online` absence as unknown rather than offline.

## Procedure 4: Build a Resilient Fallback Chain — Never Re-Raise Transient Errors

When `/stat/sta` fails transiently (controller throttle, 5xx, network glitch),
the exception **must not bubble to the caller**. Without a try/except, a
transient failure makes offline clients completely unfindable — the user gets an
error instead of the historical record that `/rest/user` would have returned.

**The broken pattern:**

```python
# ❌ WRONG — transient 5xx on /stat/sta makes offline lookups fail hard
clients = await self.clients.update()
for client in clients:
    if client.mac == mac:
        return client
# If update() raises, we never reach /rest/user
```

**Requirements for a correct fallback chain:**

1. **Wrap the live endpoint in `try/except Exception`** — do not narrow to a
   specific exception type; controller errors are not typed consistently.
2. **Log the failure at DEBUG level** — not WARNING or ERROR. Transient
   throttles are expected behavior, not incidents.
3. **Fall through to `/rest/user`** — do not re-raise, do not return an error
   response.
4. **Write operations (mutations) are exempt** — they should fail fast. Only
   read paths need the fallback chain.

```python
from unifi_core.exceptions import UniFiNotFoundError

try:
    clients = await self.clients.update()  # /stat/sta
    for client in clients:
        if client.mac == mac:
            return client
except Exception as e:
    # Expected: controller throttle, transient 5xx, network blip.
    # Log at DEBUG so it appears in verbose traces but not in normal logs.
    logger.debug(f"Live endpoint failed: {e}; trying /rest/user fallback")

# Fallback path: always executes on exception, also executes when
# the client is offline (not present in /stat/sta even on success).
all_clients = await self.manager.get_all_clients()
for client in all_clients:
    if client.mac == mac:
        return client

raise UniFiNotFoundError("client", mac)
```

**Cost accepted:** Failure case requires 2 round-trips instead of 1. This is
acceptable because the success path (no exception) stays at 1 round-trip,
failures are rare, and client caching absorbs repeat calls within a time window.
Correctness outweighs latency here.

## Procedure 5: Merge Dual-Source Raw Payloads — Live Data Wins on Overlap

`get_client_details()` in `client_manager.py` fetches from both `/stat/sta` and
`/rest/user` independently, then merges their raw dicts. The merge order is
critical: **`/stat/sta` (live) must win on all overlapping keys**.

**The correct merge order in `client_manager.get_client_details()`:**

```python
# /stat/sta wins for overlapping keys (live data trumps stale snapshot).
# /rest/user supplies stable user-table fields (_id, noted, fixed_ip,
# local_dns_record, usergroup_id) that /stat/sta sometimes omits.
merged_raw = {**user_raw, **active_raw}
return SimpleNamespace(mac=client_mac, raw=merged_raw)
```

Where `user_raw` is from `/rest/user` and `active_raw` is from `/stat/sta`.
Python dict merge semantics mean `active_raw` keys overwrite `user_raw` keys
on conflict — exactly what we want.

**Why order matters:**

| Field | `/rest/user` (user_raw) | `/stat/sta` (active_raw) | Merged result |
|-------|------------------------|--------------------------|---------------|
| `ip` | `"10.0.0.99"` (last-known) | `"10.0.0.5"` (current) | ✅ `"10.0.0.5"` — live wins |
| `status` | absent | derived (via `_is_online`) | ✅ live value used |
| `_id` | ObjectID string | absent | ✅ stable user-table field preserved |
| `fixed_ip` | set value | absent | ✅ user-table field preserved |

**The anti-pattern to avoid:**

```python
# ❌ WRONG — user_raw overwrites active_raw; stale IP wins over current IP
merged_raw = {**active_raw, **user_raw}
```

**When to apply:** Only in code paths that combine records from both endpoints.
Single-source paths (online-only `unifi_list_clients` hitting `/stat/sta`
directly, or an offline fallback using only `/rest/user`) do not need merging.

**Where this lives:** `client_manager.py` — `get_client_details()`. Any future
refactor that restructures the merge must preserve live-wins-on-overlap
semantics.

## Cross-Cutting Gotchas

**Gotcha: `/rest/user` uptime values survive disconnect.** Some firmware
variants retain last-session uptime in `/rest/user` records after a client
disconnects. The `_is_online()` fallback (Procedure 3) must only be trusted
when the data source is `/stat/sta`. Always be aware of which endpoint produced
the raw dict before applying status derivation.

**Gotcha: The same mapping bug exists in three model factories and the GraphQL
layer.** When fixing a field mapping error in `client_from_controller`, check
`blocked_client_from_controller`, `client_lookup_from_controller` (all in
`clients.py`), and the three `from_manager_output` classmethods in
`graphql/types/network/client.py`. They are structurally identical and tend to
carry the same defects.

**Gotcha: Do not fix user-reported bugs without raw payload evidence.** UniFi
API behavior varies by controller firmware. A defensive code change without
understanding the variance may be unnecessary (already working on test
controllers) or incomplete (patching a symptom). Always request: controller
hardware, UniFi OS version, Network Application version, and the raw
`/stat/sta` or `/rest/user` output showing the unexpected value. When a
reporter provides raw payloads, trust the evidence immediately and fix with
high confidence.

**Gotcha: Write operations (mutations) must not use the fallback chain.**
Read paths should swallow transient endpoint errors and fall back. Write paths
(block, unblock, rename) must fail fast — silently falling back on a mutation
failure could mask a real error or cause inconsistent controller state.
