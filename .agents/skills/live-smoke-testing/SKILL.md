---
name: myco:live-smoke-testing
description: |
  Activate this skill when running, interpreting, extending, or debugging the live hardware
  smoke test harness in `scripts/live_smoke.py`. Covers all aspects of manifest-driven live
  testing against real UniFi hardware: .env credential setup, tool classification tiers,
  --phase flag selection to bound blast radius, the human-in-the-loop confirmation gate for
  mutations, artifact interpretation in live-smoke-results/, adding new tools to the harness,
  and recognizing known API contract failure patterns that mock-based CI cannot catch. Apply
  this skill even if the user doesn't explicitly ask about the harness — activate whenever a
  PR requires live smoke evidence, a new tool category needs coverage, or an API contract
  mismatch is suspected. CRITICAL: Treat live smoke as a PRE-MERGE BLOCKING GATE when code
  changes API response parsing (new fields, filtering logic, payload normalization).
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Live Smoke Testing Against Real UniFi Hardware

`scripts/live_smoke.py` is the manifest-driven live hardware test harness. It validates API
contracts that mock-based CI (unit tests, golden fixtures) structurally cannot catch — auth
token expiry, payload normalization, API version mismatches, and hardware-specific field
assumptions. Phase 2 live smoke runs caught 3 critical bugs before merge. Run live smoke
before every major merge that touches API-facing code.

## Prerequisites

Before any live run, ensure:

1. **`.env` file at project root** (gitignored) with real credentials:
   ```
   UNIFI_HOST=<controller-hostname-or-ip>
   UNIFI_USERNAME=<admin-username>
   UNIFI_PASSWORD=<admin-password>
   UNIFI_SITE=<site-id>           # usually "default"
   # For Access domain:
   UNIFI_ACCESS_API_KEY=<access-api-key>
   ```

2. **Per-server `tools_manifest.json` is up-to-date** — the harness auto-discovers tools
   from each server's manifest. During development, verify your local module's manifest
   is current:
   ```bash
   # Check where each server's manifest is located
   find . -name "tools_manifest.json" -type f
   ```
   New tools registered in the manifest are automatically included in smoke runs; no manual
   harness edits are needed just to add read-only or preview coverage for a newly registered
   tool. If adding a new tool, verify the manifest entry exists and `safety_tier()`
   classification is correct (see Procedure A).

3. **Target hardware is reachable** — verify connectivity before running:
   ```bash
   curl -k https://$UNIFI_HOST
   ```

4. **Branch context** — the harness lives in `scripts/live_smoke.py` on the main branch.
   When branching or bisecting, confirm you have the current harness code before running.

## Procedure 0: PRE-MERGE BLOCKING GATE — API Response Parsing Changes

**Trigger Criteria — Live Smoke is Mandatory Before Merge:**

Code changes in any of these categories require a pre-merge live smoke run that must PASS
before the PR can be merged:

- **Manager response normalization logic** — changes to how API response payloads are converted
  to domain models (e.g., field mapping, null handling, type coercion in manager classes)
- **New API response fields** — adding handling for fields that are new to the UniFi API or
  new to a particular controller firmware version
- **Filtering or field selection logic** — changes to which fields are extracted from responses,
  or conditional inclusion/exclusion of fields based on hardware or firmware state
- **Payload shape transformation** — restructuring nested payloads, flattening, or re-nesting
  fields for compatibility with domain models
- **Version-dependent API contracts** — changes that assume an API endpoint behaves differently
  across firmware versions

**Why this is a blocking gate:** Mock-based CI uses golden fixtures (static JSON files) that
cannot evolve with real hardware firmware updates. Changes to response parsing are invisible
to unit tests — they pass against the fixed fixture forever, but fail against real hardware
running a different API version. The 2026-05-17 Access proxy incident (#283) exemplifies
this: unit tests passed; live hardware returned auth-wrapped-in-200 errors invisible to mocks.

**Execution:**

```bash
# For the affected domain(s) (e.g., network, protect, access):
python scripts/live_smoke.py --server <domain> --phase readonly
python scripts/live_smoke.py --server <domain> --phase safe
# Both must exit status 0 with no failed/exception records in artifacts
```

**Sign-off:** Include in the PR description:
```
**Live Smoke Evidence:**
- ✓ network readonly: 45 tools, 0 failures
- ✓ network safe: 12 lifecycle ops, 0 failures
- Artifacts: [link to live-smoke-results/{server}-{timestamp}.json]
```

The PR reviewer must confirm both phases passed and inspect the artifact for correct
payloads before approving merge. This is equivalent to a code review checkpoint — it
verifies API contract assumptions against reality before the code lands on main.

## Procedure A: Understand Tool Classification Tiers

The harness classifies tools dynamically from manifest annotations and the `RISKY_OPERATION_NAMES`
set (line ~90 in `scripts/live_smoke.py`). `safety_tier()` on `LiveSmokeRunner` drives
phase inclusion.

| Tier (`safety_tier` value) | How it's determined | Run gate |
|----------------------------|--------------------|-|
| `read_only` | `readOnlyHint: true` annotation in manifest | Included in `readonly` and `safe` phases |
| `preview_or_safe_lifecycle` | Has `confirm` param; not in `RISKY_OPERATION_NAMES` | Preview (confirm=False) in `preview`/`safe`; lifecycle pairs in `lifecycle`/`safe` |
| `requires_approval` | In `RISKY_OPERATION_NAMES` set OR `destructiveHint: true` | Excluded from automated runs; listed in `pending_approval`; manual only |
| `defer_heavy_read` | In `STREAM_OR_HEAVY_READS` set (streaming/export tools) | Skipped unless `--include-heavy-reads` passed |
| `mutating_requires_review` | Has writes but no `confirm` param and not explicitly risky | Flagged for manual review |

**Classification is driven by manifest annotations — not static tier lists.** When in doubt,
set `destructiveHint: true` on the tool's `ToolAnnotations`. A tool missing `readOnlyHint`
that does only reads is silently treated as mutating; fix the annotation.

## Procedure B: Run the Harness with `--phase` Control

The `--phase` flag bounds blast radius. The `--server` flag is required for all MCP-direct
phases. Always start at the safest phase and advance only after the prior phase passes cleanly.

```bash
# Safest run — readonly + preview + safe lifecycles (default phase is "safe")
python scripts/live_smoke.py --server network --phase safe

# Read-only tools only (narrowest scope)
python scripts/live_smoke.py --server network --phase readonly

# Preview phase — all mutating tools called with confirm=False
python scripts/live_smoke.py --server protect --phase preview

# Approved operations — runs all safe lifecycles plus explicitly approved mutations
python scripts/live_smoke.py --server network --phase approved

# Run all servers at once (requires full .env with Access and Protect creds)
python scripts/live_smoke.py --server all --phase safe

# Inventory — prints safety_tier classification for every tool; no live calls
python scripts/live_smoke.py --server network --phase inventory
```

**Phase progression guidance:**
- Start every new tool or hardware target with `--phase readonly`.
- Advance to `--phase safe` only after `readonly` passes cleanly.
- Advance to `--phase approved` only after `safe` passes cleanly.
- Never skip directly to `approved` on a first run against a new tool or new hardware.
- Use `--phase inventory` to audit tier assignments without making any live calls.
- Phase scope has expanded over the project lifecycle: Phase 1 was intentionally narrow
  (deployment/auth only, no controller-touching); Phase 2 added full Protect physical actions
  and Access lock/unlock patterns. Expect further expansion for each new REST endpoint domain.

**Expected output:** The harness streams per-tool status to stdout. A passing run exits with
a summary count. Any `failed` or `exception` status line requires investigation before merge.

## Procedure C: Human-in-the-Loop Mutation Gate

Mutation tools require a two-stage human gate. The `preview` phase (included in `safe`)
handles Stage 1 automatically; Stage 2 requires human review before running `--phase approved`.

**Stage 1 — Preview phase (harness does this automatically during `safe`/`preview`):**

The harness calls all `preview_or_safe_lifecycle` tools with `confirm=False`. This returns
a preview payload without executing any write. Review the output in the terminal and in the
per-server artifact file in `live-smoke-results/`.

**Stage 2 — Human approval, then approved phase:**

```bash
# After reviewing Stage 1 preview output, if all looks correct:
python scripts/live_smoke.py --server network --phase approved
```

The `approved` phase runs explicitly coded lifecycle methods (e.g.,
`lifecycle_network_dns()`, `lifecycle_network_oon_policy()`) that execute idempotent
create+delete pairs with `confirm=True`.

**Rules:**
- Never skip Stage 1 — even for tools you've run before, always review the preview against
  current hardware state. A lifecycle run against stale assumptions can leave orphaned
  resources on the controller.
- If the preview shows unexpected scope, wrong site, or wrong resource count, stop.
  Investigate the tool's argument construction before proceeding to `approved`.
- Safe-lifecycle runs should leave zero net hardware changes. After an `approved` run,
  verify the controller UI shows no orphaned test resources.

## Procedure D: Interpret Artifacts in `live-smoke-results/`

Each run writes one JSON file per server, stamped with a timestamp:
```
live-smoke-results/{server}-{timestamp}.json
```

The file contains a `SmokeReport` serialized as JSON:
```json
{
  "server": "network",
  "started_at": "2026-05-01T12:00:00+00:00",
  "finished_at": "2026-05-01T12:03:45+00:00",
  "connected": true,
  "records": [
    {
      "tool": "unifi_list_clients",
      "phase": "readonly",
      "status": "ok",
      "args": {},
      "duration_ms": 342,
      "success": true,
      "error": null,
      "summary": { ... }
    }
  ],
  "created_resources": [],
  "cleaned_resources": [],
  "pending_approval": []
}
```

**Status values per record:**
- `"ok"` — tool completed; `success` is `true`; inspect `summary` for shape correctness.
- `"failed"` — tool returned `success: false`; check `error` field.
- `"skipped"` — tool excluded from current phase or args unavailable; not a failure.
- `"exception"` — Python exception raised during invocation; check `error` for traceback.

**API contract mismatches show up in `summary` content, not always as `"failed"`.** For
example, an Access proxy returning HTTP 200 with an auth-failure body: `status` is `"ok"`
but `success` is `false` or `summary` contains no usable data. Always inspect `summary`
content and `pending_approval`, not just the overall status counts.

**Confirmed API contract failure patterns** (discovered through live testing; mocks did not
catch any of these):

| Pattern | Symptom in artifact | Root cause |
|---------|-------------------|-|
| Access proxy auth masking | `status: ok`, empty/error summary | Token expiry → proxy returns 404 wrapped in 200 |
| OON payload normalization | Create succeeds, object malformed | Manager-side shape translation required; API expects different field structure |
| Alarm archive preview semantics | Preview count ≠ actual archived count | Mismatch between filter used in preview vs. execution |
| `hardware_platform` field assumption | Field missing or wrong type on some models | Not all hardware versions expose this field |
| Network alerts/IPS API version incompatibility | 404 or schema error on known endpoint | Endpoint path changed between controller firmware versions |
| Access `CODE_UNAUTHORIZED` ambiguity | Same error code for expired token vs. wrong credentials | Cannot distinguish root cause without inspecting response body detail |

When you see a live smoke failure with no corresponding unit test failure, assume API
contract mismatch first. Inspect the full `summary` body before looking at tool logic.

## Procedure E: Extend the Harness for New Tools

When a new tool is scaffolded and registered in the server's `tools_manifest.json`, extend
the harness as follows:

1. **Run inventory to see current classification:**
   ```bash
   python scripts/live_smoke.py --server network --phase inventory | grep unifi_new_thing
   ```
   Confirm `safety_tier` matches your intent. Classification is driven automatically by
   manifest annotations — check the tool's `ToolAnnotations` in the tool module.

2. **If the tool should be `read_only`:** Ensure `readOnlyHint=True` is set on
   `ToolAnnotations` in the tool function. The harness will auto-include it in `readonly`
   phase. No harness edits needed.

3. **If the tool has a `confirm` param (preview/lifecycle):** The harness auto-includes it
   in `preview` phase with `confirm=False`. For safe lifecycle testing (create+delete pair),
   add a new lifecycle method to the `LiveSmokeRunner` class in `scripts/live_smoke.py` and
   call it from `run_lifecycles()` or `run_approved()`:
   ```python
   async def lifecycle_network_new_thing(self) -> None:
       # 1. Create the resource
       create_rec = await self.call("unifi_create_new_thing", {...}, "lifecycle")
       if not create_rec.success:
           return
       resource_id = ...  # extract from create_rec.summary
       # 2. Delete it (idempotent cleanup)
       await self.call("unifi_delete_new_thing", {"id": resource_id, "confirm": True}, "lifecycle")
   ```

4. **If the tool is risky/destructive:** Add it to `RISKY_OPERATION_NAMES` (the set at
   line ~90 in `scripts/live_smoke.py`) or set `destructiveHint=True` on `ToolAnnotations`.
   This moves it to `pending_approval` and excludes it from automated phases.

5. **Run read-only phase first, inspect the artifact:**
   ```bash
   python scripts/live_smoke.py --server network --phase readonly
   cat live-smoke-results/network-*.json | python -m json.tool | grep -A5 unifi_new_thing
   ```
   Confirm `status: "ok"` and `success: true` and that `summary` has the expected shape.

6. **Advance to safe/approved phase** after readonly passes cleanly.

7. **Document the tier classification in the PR description** — reviewers need to know the
   blast-radius classification to sign off on the smoke evidence.

## Procedure F: Probe Script Workflow and Image-Level Docker Smoke

Live hardware smoke catches API contract mismatches but requires real hardware access. Two
additional regression layers run without hardware and catch regressions in the CI pipeline.

**Probe-script layer** (`scripts/probe_*.py` utilities):

Smaller-scope smoke scripts run against development builds without requiring full live
hardware setup. These probe scripts verify:
- Tool registration (manifest entries are syntactically valid)
- Schema validation (schemas load and validators register)
- Manager instantiation (DI/bootstrap sequence succeeds)
- Tool function signatures (decorators and parameters match manifest)

Run probe scripts in any PR that touches tool registration or schema changes:
```bash
python scripts/probe_tools.py --server network
python scripts/probe_schemas.py
```

Probe failures are non-fatal for local development but become CI gates to catch early
regressions before a full hardware run.

**Image-level Docker smoke** (Phase 3+ requirement):

The release build pipeline runs image-level smoke tests on generated Docker images before
they're pushed to GHCR. This tests:
- All three app servers start cleanly inside their respective images
- All tools are discoverable in each image's tools_manifest.json
- Basic connectivity to a mock controller (localhost loopback) succeeds

Image-level smoke does not execute tool logic (no live hardware), but it catches
import errors, missing dependencies, manifest corruption, and startup failures that
only appear in the final release image.

This layer lives in CI/CD pipeline (GitHub Actions), not in developer workflows.
Local equivalents can be tested with:
```bash
docker build -t unifi-network:dev -f Dockerfile.network . && \
  docker run --rm unifi-network:dev python -c "from unifi_network_mcp import *; print('OK')"
```

**Four-layer regression model:**
1. **Unit/fixture layer** — mock data, schema validation, bootstrap (fast, pre-commit)
2. **Probe-script layer** — tool registration, manifest, schema instantiation (minutes, pre-push)
3. **Live smoke layer** — API contract verification on real hardware (manual gate, code review)
4. **Image-level layer** — Docker build, startup, manifest integrity (release gate, CI pipeline)

Each layer adds cost but catches distinct classes of regressions. The first three run
in developer workflows; the fourth is automated in the release pipeline.

## Cross-Cutting Gotchas

- **Mock + golden fixtures are insufficient by design.** Live smoke is the only mechanism
  that catches auth token expiry, real payload shapes, hardware-specific fields, and API
  version skew. Treat live smoke as a required quality gate, not optional extra validation.

- **`.env` is gitignored — never commit credentials.** If you see `UNIFI_HOST` or
  `UNIFI_PASSWORD` in a diff, abort the commit immediately and rotate the credentials.

- **`--server` is required for all MCP-direct phases.** Omitting it causes a parse error.
  `api-actions`, `api-resources`, and `api-streams` phases use a different runner and do
  not require `--server`.

- **Phase 2 baseline is 56 passing approved-ops.** This count was established during Phase 2
  development. A PR that drops the count or introduces new failures requires a documented
  explanation and fix before merge.

- **Credential rotation invalidates prior artifacts.** If credentials changed between runs,
  artifacts from prior runs cannot be used as PR evidence. Re-run from scratch.

- **Phase scope expands with each new domain.** Phase 1 deliberately excluded
  controller-touching endpoints; Phase 2 added them. Phase 3 will require harness expansion
  for new REST endpoints. Every new tool category must be classified and added — do not
  assume prior phases cover new domains.

- **`tools_manifest.json` is the source of truth for auto-discovery.** Manifest annotation
  correctness (`readOnlyHint`, `destructiveHint`) and harness registration (for lifecycle
  methods) are both required. Wrong annotations silently misclassify tools.