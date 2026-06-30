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
assumptions. Live smoke runs caught multiple critical bugs before merge. Run live smoke
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

5. **Git worktree `.env` placement** — `scripts/live_smoke.py` derives its repo root from
   its own file location (`Path(__file__).resolve().parents[1]`) and loads `.env` from that
   root. In a git worktree the root resolves to the worktree directory, NOT the main
   checkout. Copy or symlink your credentials file from the main checkout into the worktree
   root before running:
   ```bash
   ln -s /path/to/main-checkout/.env /path/to/worktree/.env
   ```
   Omitting this causes silent credential-not-found failures with no warning.

6. **Use `uv run`, not system python3** — the repo's dependencies are managed by uv and are
   not installed in the system Python environment. Always invoke the harness via:
   ```bash
   uv run python scripts/live_smoke.py --server network --phase safe
   ```
   Running with bare `python3` will fail with import errors for `aiounifi`, `dotenv`, and
   other dependencies not available outside the uv-managed virtual environment.

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
running a different API version. The Access proxy incident exemplifies this: unit tests passed;
live hardware returned auth-wrapped-in-200 errors invisible to mocks.

**Ship doctrine — verify the changed code path, not an adjacent green path:** Smoke evidence
only counts if it exercises the specific code modified by the PR. If your PR touches the
alarm manager, a passing run that exercises only the client manager is not evidence. Identify
the tools that invoke the changed code and name them explicitly in the PR smoke evidence block.

**Execution:**

```bash
# For the affected domain(s) (e.g., network, protect, access):
uv run python scripts/live_smoke.py --server <domain> --phase readonly
uv run python scripts/live_smoke.py --server <domain> --phase safe
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
uv run python scripts/live_smoke.py --server network --phase safe

# Read-only tools only (narrowest scope)
uv run python scripts/live_smoke.py --server network --phase readonly

# Preview phase — all mutating tools called with confirm=False
uv run python scripts/live_smoke.py --server protect --phase preview

# Approved operations — runs all safe lifecycles plus explicitly approved mutations
uv run python scripts/live_smoke.py --server network --phase approved

# Run all servers at once (requires full .env with Access and Protect creds)
uv run python scripts/live_smoke.py --server all --phase safe

# Inventory — prints safety_tier classification for every tool; no live calls
uv run python scripts/live_smoke.py --server network --phase inventory
```

**Phase progression guidance:**
- Start every new tool or hardware target with `--phase readonly`.
- Advance to `--phase safe` only after `readonly` passes cleanly.
- Advance to `--phase approved` only after `safe` passes cleanly.
- Never skip directly to `approved` on a first run against a new tool or new hardware.
- Use `--phase inventory` to audit tier assignments without making any live calls.
- Phase scope has expanded over the project lifecycle: earlier phases were intentionally narrow
  (deployment/auth only, no controller-touching); later phases added full Protect physical actions
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
uv run python scripts/live_smoke.py --server network --phase approved
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

**Disposable resource rule for destructive operations:** When a lifecycle method exercises
destructive operations (archive, bulk-delete, format), always target a disposable resource
created specifically for that run (e.g., a DNS record named `smoke-test-<timestamp>`). Never
run destructive smoke against a production resource. If a dedicated test resource cannot be
guaranteed (e.g., hardware-bound resources like camera channels), add the tool to
`RISKY_OPERATION_NAMES` to exclude it from automated phases and require explicit human approval.

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
   uv run python scripts/live_smoke.py --server network --phase inventory | grep unifi_new_thing
   ```
   Confirm `safety_tier` matches your intent. Classification is driven automatically by
   manifest annotations — check the tool's `ToolAnnotations` in the tool module.

2. **If the tool should be `read_only`:** Ensure `readOnlyHint=True` is set on
   `ToolAnnotations` in the tool function. The harness will auto-include it in `readonly`
   phase. No harness edits needed.

3. **If the tool has a `confirm` param (preview/lifecycle):** The harness auto-includes it
   in `preview` phase with `confirm=False`. For safe lifecycle testing (create+delete pair),
   add a new lifecycle method to the `LiveSmokeRunner` class in `scripts/live_smoke.py` and
   call it from `run_lifecycles()` or `run_approved()`.

   **Lifecycle completeness checklist — required for every new lifecycle method:**
   - [ ] Follows create → update → get → delete order (NOT create → delete only)
   - [ ] The update step asserts field preservation via a subsequent `get` call
   - [ ] Non-default fields are tested with explicit targeted values (not just defaults)
   - [ ] The lifecycle method lands in the harness permanently, not a throwaway script

   **Throwaway vs. permanent:** One-off validation scripts (for enum-hint PRs, new optional
   parameters, or targeted edge-case verification) belong under `scripts/` and must be deleted
   after verification — they are NOT lifecycle methods and must NOT be committed to the
   harness permanently. Only full create→update→get→delete lifecycle flows should be
   added as permanent harness methods.

   The DNS lifecycle (`lifecycle_network_dns`) is the canonical reference implementation:
   create a record, update one field, get it back to assert the update landed, then delete.
   WLAN and AP-group lifecycles were extended to follow the same pattern.

4. **If the tool is risky/destructive:** Add it to `RISKY_OPERATION_NAMES` (the set at
   line ~90 in `scripts/live_smoke.py`) or set `destructiveHint=True` on `ToolAnnotations`.
   This moves it to `pending_approval` and excludes it from automated phases.

5. **Run read-only phase first, inspect the artifact:**
   ```bash
   uv run python scripts/live_smoke.py --server network --phase readonly
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

**Image-level Docker smoke** (release gate requirement):

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

- **api-actions and api-resources use curated subsets, not auto-discovery.** `API_ACTIONS_SAMPLE`
  in `scripts/live_smoke.py` is a hardcoded list of 6 tools (network clients/devices, protect
  cameras/lights, access doors/users). New tools are NOT automatically included in
  `--phase api-actions` coverage. To add a new tool to the api-actions phase, explicitly
  append it to `API_ACTIONS_SAMPLE`. Do not assume successful MCP-direct smoke implies
  api-actions coverage.

- **`--phase safe` exercises default args only — it is a regression detector, not full coverage.**
  The harness calls every tool with its default argument values. New optional parameters added
  to existing tools are not exercised by the safe phase. After a PR that adds optional parameters,
  run a targeted second pass: write a short script under `scripts/` that calls the tool with
  each new non-default value and asserts on the response shape. Delete after verification.

- **HA/shadow mode transient failures are environment issues, not code bugs.** If live smoke
  fails with "resource temporarily unavailable," "sync in progress," or similar, verify the
  HA cluster has stabilized before investigating the tool. Retry after 30–60 seconds. Do not
  block merge on HA transient failures — note them in the PR with a re-run confirmation.

- **Credential rotation invalidates prior artifacts.** If credentials changed between runs,
  artifacts from prior runs cannot be used as PR evidence. Re-run from scratch.

- **Phase scope expands with each new domain.** Each new tool category must be classified and
  added — do not assume prior phases cover new domains.

- **`tools_manifest.json` is the source of truth for auto-discovery.** Manifest annotation
  correctness (`readOnlyHint`, `destructiveHint`) and harness registration (for lifecycle
  methods) are both required. Wrong annotations silently misclassify tools.

- **`AlarmRulesFacade` fallback silently masks SuperAdmin credential failures.** If the
  account lacks SuperAdmin on the Protect console, `AlarmManagerPermissionError` is caught by
  `AlarmRulesFacade` and it silently falls back to the legacy automations API. The smoke
  record shows `status: ok` — but the v2 code path was never exercised. The `complete` flag
  in the MCP `_meta` block distinguishes v2 success (`complete: true`) from legacy fallback
  (`complete: false`). When smoke-testing alarm rules, inspect the `summary._meta` block and
  confirm `complete: true`; a passing run with `complete: false` means v2 was never reached.

- **HTTP 404 from Access API-key endpoints confirms auth is working.** When using
  API-key-authenticated Access endpoints, a 404 on a valid-format resource path means the
  key was accepted but the resource doesn't exist — this is a green credential signal. A
  401/403 means the key was rejected. Use this to validate Access API key configuration:
  deliberately query a known-missing resource ID and expect 404, not 401.

- **HTTP 401 on the uiprotect bootstrap/WebSocket path during Protect smoke is expected and benign.**
  The uiprotect library opens a WebSocket channel for real-time events using a cookie-based
  auth path that the MCP API key does not cover. A 401 on that WebSocket/bootstrap path does
  not indicate a problem with the REST API key — the REST path used by all MCP tool calls
  is healthy. When you see a 401 in Protect smoke output, check whether it's on the
  WebSocket bootstrap path before treating it as a real auth failure.

- **`access_get_activity_summary` CODE_SYSTEM_ERROR -3 on the Access activities histogram endpoint is a pre-existing controller issue, not a code bug.**
  This error reproduces consistently across branches and controller firmware versions on
  affected controllers. It is a known upstream Access controller issue unrelated to MCP
  code changes. When this error appears in smoke results, treat it as an
  environment/controller issue: note it in the PR, re-run on a different controller if
  available, and do not block merge solely on this error.

- **macOS local-network privacy gate — Homebrew Python/uv gets `[Errno 65] No route to host` on RFC1918 addresses.** macOS 15/26.x enforces a per-binary local-network entitlement. Homebrew Python, uv, and other ad-hoc-signed (non-Apple-signed) binaries are denied LAN access by the system firewall even when macOS Privacy & Security shows them as approved — the entitlement check is per binary and resets on Homebrew upgrades. Symptoms: `[Errno 65] No route to host` for any 192.168.x.x / 10.x.x.x connection while `ping` succeeds. **Workaround:** run the smoke harness inside Docker (`docker run --rm ...`) where the container inherits the LAN entitlement from Docker Desktop. Per-binary macOS approval is also possible but resets on the next `brew upgrade`.

- **`UNIFI_NETWORK_HOST` vs `UNIFI_HOST` — `--server all` MCP-direct runs use `UNIFI_HOST` for the Network controller.** These are distinct variables operating at different layers. MCP-direct smoke (`--server all`) bootstraps the Network server using `UNIFI_HOST`, not `UNIFI_NETWORK_HOST`. The API bootstrap path used by REST API phases uses `UNIFI_NETWORK_HOST` when set. If `UNIFI_NETWORK_HOST` is correct but `UNIFI_HOST` is wrong or absent, `--server all` MCP-direct runs connect to the wrong controller (or fail silently) while `--phase api-actions` and `--phase api-resources` continue working. Always verify both variables when debugging unexpected `--server all` connection behavior.

- **Enum-hint PRs require explicit non-default MCP tool calls — `--phase safe` alone is insufficient evidence.** The default `--phase safe` run exercises every tool with its default argument values only. A PR that modifies enum hints or filter descriptions on tool arguments is never exercised by the harness defaults — the modified annotation paths are simply not invoked. Required evidence: make an explicit targeted call (e.g., via Docker Compose MCP or a short probe script) that passes the newly-documented enum value and confirms the correct filtered response. `--phase safe` output is necessary background but not sufficient smoke evidence for enum-hint changes.

- **Nonzero harness exit from a pre-existing unrelated tool failure — document and proceed.** A live smoke run may exit nonzero because a tool unrelated to the PR's changes fails (e.g., a known upstream controller issue or pre-existing API regression). This is NOT a merge blocker for the PR's code path. Required steps: (a) identify the failing tool and confirm it fails identically on `main` independent of the PR; (b) confirm all tools in the PR's exercised code path show `status: ok` in the artifact; (c) document the pre-existing failure with the tool name and error message in the PR description. Never treat every nonzero harness exit as a merge block — only failures in the PR's exercised code path are blocking.

- **Mutation-widening PRs require safe-apply/revert smoke OR documented `confirm=false` preview.** When a PR widens a mutation tool's accepted parameters (e.g., adding updateable fields to `unifi_update_traffic_route`), unit tests alone are insufficient — mocks cannot catch API-side field rejection or payload normalization failures. Required: either (a) a live smoke run that applies the mutation with `confirm=True` against a disposable resource, asserts the result, and reverts idempotently (net-zero), OR (b) documented deferral: run with `confirm=False` preview and embed the returned preview payload showing the would-be request shape in the PR evidence block. Omitting both for mutation-widening PRs is a merge blocker.

- **`Bootstrap.doorlocks` may be absent in newer uiprotect versions — access via `getattr` fallback only.** The `doorlocks` attribute was removed from the uiprotect `Bootstrap` dataclass in a library upgrade. Direct attribute access (`bootstrap.doorlocks`) raises `AttributeError` at runtime on affected versions with no deprecation warning. Fix: replace all `bootstrap.doorlocks` accesses with `getattr(bootstrap, "doorlocks", [])`. Live smoke against a controller running an upgraded uiprotect surfaces this as an `exception` status in Protect smoke records; mock-based unit tests and golden fixtures cannot catch it.
