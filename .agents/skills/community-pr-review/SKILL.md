---
name: myco:community-pr-review
description: >-
  Use this skill when reviewing or merging any community PR in unifi-mcp — even if the user
  just says "take a look at this PR" or "can we merge this." Covers the quality gate checklist
  (f-string logger ban, Ruff lint, validator registration, doc site update ordering), the
  fork-edit model for trusted contributors, org-fork push limitations, dual-subagent review,
  PR body standards, live smoke tests, mutating cycles, the unresponsive-first-time-contributor
  fork-edit exception, and the close-and-redirect pattern. Also covers community infrastructure
  setup (.github/ health files, issue routing, bug report template design) and evidence-first
  bug triage protocol. Apply this skill before approving any externally-authored PR, before
  running the merge command, when auditing recently merged PRs, and when setting up community
  engagement infrastructure.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Community PR Review and Merge

Community PRs go through a fixed quality checklist before merge. For trusted contributors
(level99 has 7+ merged PRs), the maintainer commits fixes directly to the contributor's fork
branch rather than requesting round-trip revisions — this preserves attribution while eliminating
latency. An exception exists for first-time contributors who are historically unresponsive: when the fix is
trivial (ruff format, simple doc change), apply fork-edit rather than request changes. This skill documents
the full workflow from first look to merge commit, including technical validation for PRs that touch UniFi API tool implementations.

## Prerequisites

- PR is open and CI workflow state is understood (see Step 0b for first-time contributor gotcha)
- You have push access to the contributor's fork (needed for the fork-edit model)
- `AGENTS.md` is current — it is the canonical source for hard bans
- For first-time contributors: check prior PR history to assess responsiveness (72+ hour silence threshold for fork-edit exception eligibility)
- For PRs touching tool implementations or API handlers: a **live UniFi controller** must be reachable to run smoke tests
- **Makefile three-layer generation pipeline:** `make generate` regenerates committed artifacts, `make check-generated` checks for drift, `make pre-commit` runs the full chain (format → generate → lint → test → drift checks). Run `make pre-commit` before opening any PR that modifies generated artifacts.

---

## Step 0b — First-Time Contributor CI Auth Gate (Critical Gotcha)

When a first-time contributor opens a PR from a fork, GitHub queues all CI workflows with status
`action_required` silently. The workflows do NOT run automatically. No error is shown to the
contributor — they see a blank CI box in the PR.

**You must manually authorize the workflow run** in the GitHub UI:

1. Go to the PR Actions tab
2. Scroll to the pending workflow(s)
3. Click "Approve and run" on each queued workflow

Do this before asking the contributor to make changes or before running your own review tests.
Without this step, you will review against stale code or outdated test results, and the
contributor will believe their PR is broken when it's just the CI gate.

This gotcha affects every first-time contributor, including level99 on their first PR.

---

## Subagent Decomposition (For Complex PRs)

For PRs with significant code changes or security implications, split the review across two
subagents rather than doing a single-pass review:

1. **Code review subagent** — correctness, security, quality gates (Gates 1–4 below)
2. **Test coverage subagent** — test completeness, coverage gaps, test pattern compliance

Before dispatching either, check out the branch locally and run `git log origin/main..HEAD`
to enumerate commits. This gives both subagents a shared commit list for scoped analysis.

PR #135 (`fix/acl-create-mac-passthrough`) established this split — it caught both a code
correctness issue and a test coverage gap that a single-pass review would have missed.

---

## Step 1 — Run the Quality Gate Checklist

First, classify the PR type (Gate 0), then work through the applicable gates in order.

### Gate 0: PR Type Classification — Routes the Checklist

Determine whether this is a **feature addition PR** or a **governance/structural refactor PR**
before running any other gate.

**Feature addition PR** — adds new tools, managers, or capabilities
→ Apply the **design-fit criterion first**: does the new tool or manager belong in this codebase,
or does it duplicate existing functionality / violate the intended scope? A PR that passes all
mechanical gates but adds a tool that's outside the project's design intent should be redirected
(Principle #6) rather than merged. Only after confirming design fit should you run Gates 1–4.

**Governance/structural refactor PR** — reorganizes field definitions, introduces shared Pydantic
models, changes base class hierarchy, or implements a field-symmetry sub-issue
→ Run the structural-correctness path instead:

1. **Pydantic inheritance correct?** — If a shared base model is introduced, does it accurately
   represent the common fields? Are subclass fields genuinely distinct from the base?
2. **Field coverage complete?** — Does the shared model cover all field variants used by the
   resource's create, read, list, and update surfaces? No field should be accessible via
   list/read but absent from the shared model.
3. **Type symmetry correct?** — Field types in the shared model must be compatible with both
   read-surface output and create/update input. Name-match alone is insufficient — a field can
   appear in both surfaces but fail silently if types diverge (e.g., `source_macs: list[str]`
   returned by list tools vs. `source_macs: str` accepted by create). This is enforced by the
   field-symmetry CI gate (the field-symmetry pattern, formalised in #137 and rolled out in Phases 0–4).
4. **No field leakage?** — Fields belonging to one resource variant must not silently appear
   on another through inheritance.
5. **Matches issue spec?** — Compare against the linked GitHub issue. Every scoped item should
   be implemented; nothing out of scope should be added.
6. **Pattern symmetric with AGENTS.md rule?** — The implementation must align with the
   field-symmetry governance rule in `AGENTS.md`, not diverge from it.

Gates 1–4 (f-string logger, Ruff lint, validator registry, doc site, shared validator blast radius) still
apply to governance PRs for any new or modified tool/manager files — but the structural
questions above are the primary gate.

**Why the split matters:** PR #140 (ACL shared-field-model pilot, level99) was reviewed with
the feature-addition checklist. The structural questions were asked only because the reviewer
recognized the PR type. A structural refactor can pass Gates 1–3 cleanly while still violating
inheritance structure, field coverage, or type symmetry — the feature-addition checklist gives
false confidence on governance PRs.

---

### Gate 1: Lint Checks and F-String Logger — Hard Blocker

**Primary targets:** All files the PR touches. F-strings specifically in `*_manager.py` files.

#### 1A: Ruff Lint Enforcement

Run the full lint gate that CI enforces:

```bash
make lint
```

This invokes Ruff on all modified files and fails on any violations. Do NOT merge a PR with
lint failures. The project uses Ruff as the canonical linter; violations are hard blockers.

If the PR introduces lint errors, request fixes via fork-edit (trusted contributors) or a
review comment (first-time contributors).

#### 1B: F-String Logger — Hard Blocker

**Primary target:** Every `*_manager.py` file the PR touches.

Scan for f-string logger calls and replace any hits with `%s`-style lazy formatting:

```python
# BLOCKED
logger.info(f"Found {count} devices on {network}")

# REQUIRED
logger.info("Found %s devices on %s", count, network)
```

**Why the manager layer is the blind spot:** Tool files (`*_tools.py`) tend to get this right
because they're reviewed more often. Manager files (`*_manager.py`) are where f-string loggers
keep appearing. In PR #119, level99's tool layer used `%s` correctly but introduced 23 f-string
calls in `device_manager.py` (14), `network_manager.py` (7), and `tools/network.py` (2). Always
check manager files explicitly.

**Implicit concatenation is invisible to grep:** Adjacent string literals cannot
be reliably caught by automated scripts. This survived a 481-call automated migration in PR #122
and was only caught by manual review. Scan manually for this pattern when logger calls span lines.

**Full-payload logging promoted to INFO level:** A `logger.debug` call that dumps a full JSON
payload is acceptable at DEBUG level but becomes production noise and data-exposure risk if
promoted to `logger.info`. Watch for this in manager files — it appeared at `firewall_manager.py`
line 622 in PR #146. All full-payload log calls must use `logger.debug`.

```python
# BLOCKED: full payload at INFO level
logger.info("Firewall policy response: %s", json.dumps(response))

# REQUIRED: full payload at DEBUG level only
logger.debug("Firewall policy response: %s", json.dumps(response))
```

**No-issue-refs ban extends to test docstrings and comment strings:** Hardcoded `#NNN` GitHub
issue or PR numbers embedded in test docstrings, pytest parameterize IDs, or inline comment
strings are banned under the same no-issue-refs rule as source code. These literals survive into
the package wheel and create dangling stale references that are invisible to the f-string logger
scanner. When the PR touches test files, scan them manually for `#\d+` embedded in string
literals and docstrings.

**Why this is a hard ban:** F-string loggers eagerly evaluate all arguments even when the log
level is suppressed. On deployments with debug logging disabled, this creates unnecessary overhead
on every suppressed call.

---

### Gate 2: Pydantic Model Wiring — Silent Failure Risk

**Target:** Any PR introducing a new tool or manager for a domain that has create/update tools.

New domains must define a pydantic model in `packages/unifi-core/src/unifi_core/<server>/models/<domain>.py` and wire it into the tool layer. A domain without a model silently bypasses field validation — unknown or read-only fields pass through unchecked.

Check that each new domain has a corresponding model with `MUTABLE_FIELDS` / `READ_ONLY_FIELDS` frozensets and `to_controller_create` / `to_controller_update` helpers. Verify the tool layer calls `to_controller_update(fields)` (not a raw dict pass-through) for update tools.

**The `to_controller_update` gotcha:** When a model exists but the tool bypasses it and passes raw caller args directly to the manager, the model's field validation is silently skipped. Confirm the tool calls `to_controller_update(fields)` and passes the result, not the original dict.

---

### Gate 3: Doc Site Update — Ordering Gate

**Target:** Any PR that adds, renames, or removes tools.

The doc site must be updated as part of the same PR — not as a follow-up. The ordering matters:
the doc site should be updated *after* the tool code is finalized but *before* merge, so the
published docs stay in sync with the merged code at every point in history.

For PR #126, this gate was explicitly enforced — the PR wasn't merged until doc counts matched.

**Note:** `docs/index.html` is a static marketing site HTML file, not a generated artifact.
Marketing site changes must be made and reviewed manually, separate from the tool documentation sweep.

---

### Gate 4: Shared Pydantic Model Defaults — Blast Radius Check

**Target:** Any PR that modifies a shared `<Domain>Base` pydantic model in `packages/unifi-core`.

If a PR adds non-`None` defaults to mutable fields on a shared base model, every update tool that uses the model will silently inject those defaults when the caller omits the field — a data-loss bug with blast radius across all tools that import the model.

**Hard blocker pattern:**

```python
# DANGEROUS — non-None default on shared base model field
class PolicyBase(BaseModel):
    create_allow_respond: bool = False   # silently overwrites on update
    schedule: dict = {"mode": "ALWAYS"}  # silently overwrites on update
```

**The rule:** Non-`None` defaults belong only in create-specific subclasses or create-specific
code paths. Shared base model fields must use `= None`. Any PR that adds non-`None` defaults to
a shared base model field is a **hard blocker**.

This gate emerged from PR #146. Check for it whenever the PR diff touches a `<Domain>Base` class
that both create and update tools inherit from.

---

## Step 1.5 — API-Touching PRs: Live Validation Requirements

For any PR that modifies UniFi MCP tool implementations, fixes API integration bugs, or adds new
handlers, apply additional technical validation before merge. The UniFi controller is stateful
and mock-based tests do not catch real-world edge cases.

### Smoke Test Coverage (All API-Touching PRs)

Run `scripts/live_smoke.py` against a live controller — not a mock — before opening or approving
the PR.

```bash
# Run read-only + preview smoke tests against the network server
# NOTE: The API server is 'unifi-api-server' (not 'unifi-api')
python scripts/live_smoke.py --server unifi-api-server --phase safe

# Run all servers (network + protect + access)
python scripts/live_smoke.py --server all --phase safe
```

**What "passing" means:** each tool returns a structurally valid response; no unexpected errors
or stack traces; list tools return at least the expected schema shape even with no controller objects.

**Independent maintainer smoke is mandatory — contributor's run does not substitute:** Even when a
contributor has already run live smoke tests and embedded results in the PR body, the maintainer
must run a full independent validation suite. Contributor runs confirm the code works in their
environment; maintainer runs confirm it against the project's reference hardware and catch
environment-specific divergence that the contributor cannot reproduce. This is a non-optional
standing rule. Reference: PR #356 (level99 ran smoke pre-submission; maintainer still ran full
independent suite before merge).

**Gotcha:** A tool already broken before the PR is still your responsibility to flag. Don't
silently skip known-broken tools — note them explicitly in the PR description.

**Gotcha:** Mock tests give false confidence. Response shapes differ between controller versions,
and some fields only appear when specific configuration exists.

**Gotcha:** HA/shadow mode transient failures are environment issues, not code bugs. If live smoke
tests fail with "resource temporarily unavailable" or "sync in progress," verify the HA cluster has
stabilized. Retry after 30–60 seconds. Do not block merge on HA transient failures.

**Gotcha — MCP plugin invokes the published PyPI package, not local branch code.** When you run
tool calls through the MCP plugin in Claude Code (or any MCP client), the plugin loads the
**installed (published) package** — not your local working tree or the PR branch. A fix that
only exists on a branch will not be exercised via the plugin until it is published. Use
`scripts/live_smoke.py` directly (not the plugin) when verifying branch-local changes, and
confirm the fix reaches production by running the plugin after the release tag is pushed.

**Gotcha — enum-hint PRs: harness defaults miss the change entirely.** When a PR adds enum-value hints or restricts accepted values for a tool parameter, `scripts/live_smoke.py` invokes each tool with default arguments only and exercises none of the constrained paths. Run a targeted script that explicitly passes each new enum value and asserts the response shape is correct (or fails predictably for invalid values).

**Gotcha — hardware-gated tools: deferral requires four conditions.** Some tools succeed only with specific attached hardware. Before blocking merge on a live test failure, confirm all four: (a) the failing tool targets optional hardware (e.g., Access controller), (b) the test environment lacks that hardware, (c) the failure message indicates absence ("device not found" / "hardware unavailable"), not a logic or auth error, and (d) the same tool passes on an environment with the hardware attached. If all four hold, document the deferral explicitly in the PR description.

**Gotcha — HTTP 401 on uiprotect bootstrap path is benign noise.** Live smoke runs against a controller with Protect enabled emit HTTP 401 on the uiprotect bootstrap path during library startup. This is the library's startup probe and is expected — not an authentication failure. Do not block merge or file a bug on a 401 from this specific path.

### API Family Boundary Check (V2 vs. Integration)

**Target:** Any PR that adds or modifies tools exposing UniFi API identifiers.

The UniFi API has two distinct identifier families: **V2 ObjectIDs** (UUID format, newer controllers)
and **Integration UUIDs** (legacy format). Tools must not mix identifier families in the same resource
surface — doing so creates silent data-loss bugs when downstream integrations receive mismatched ID types.

**Family boundary rule:** Each tool's input and output must be consistently rooted in one identifier
family. All nested references must match the primary resource's ID family.

If the PR introduces mixed families, request fixes before merge. This is a **hard blocker**.

### Mutating Cycle Tests (Create/Update/Delete PRs)

For any PR that touches create, update, or delete handlers, run a full mutating cycle:

1. **Create** — create the resource via the tool; capture the returned ID.
2. **Partial update** — update only a subset of fields.
3. **Verify field preservation** — read back and confirm fields you did NOT update are unchanged.
4. **Delete** — remove the resource and confirm it is gone (expect 204 or equivalent).

**Why field preservation matters:** The UniFi API silently drops fields not included in a
PUT/PATCH body. The verify step is the only reliable way to catch silent field zeroing.

### New-Parameter Coverage (Read-Tool PRs that Add Optional Params)

`scripts/live_smoke.py` calls every tool with default values only — it exercises none of the new
code paths. A targeted in-process pass is required: build a small Python script under `scripts/`
that calls each new parameter with at least one non-default value and asserts on the response shape.
Delete the script after verification — it's one-shot validation, not a durable harness.

### Docker Compose Verification (Shape/Description/Default Changes)

For PRs that change tool descriptions, response shapes, or parameter schemas, verify both discovery paths
a real LLM client uses:

1. **Pre-loaded path** (`unifi_load_tools` then `list_tools`) — confirms full JSON schema reaches MCP clients
2. **Lazy-execute path** (`unifi_execute(tool, arguments)`) — confirms description text carries new param
   semantics (schemas do not appear at the lazy-discovery tier). `unifi_execute` auto-promotes the tool
   into the loaded set after first call.

### "Fully Additive" Claim Audit

When a PR body claims "fully additive," diff every response shape against `main`. Any field that
disappears from the default path is a breaking change. Gate the narrowing behind an opt-in flag, or
explicitly document it as an intentional breaking change.

### Cross-Platform Validation (Windows-Targeting PRs)

For any PR that adds or modifies Windows-specific behavior (PowerShell prereq scripts, `.exe` executable detection, CRLF line endings), validate the following from macOS before approving:

1. **Plugin bundle `.ps1` presence** — unzip the plugin bundle and confirm `.ps1` scripts are included: `unzip -l <bundle>.zip | grep '\.ps1'`. Missing scripts mean Windows prereq flows will silently fail to load.
2. **Stdio MCP auth probe** — invoke the MCP server via stdio with intentionally bogus credentials and confirm the error response is human-readable (not a generic opaque "MCP error"). Windows users hit the stdio auth path first; an opaque error leaves them with no recovery action.
3. **Prereq script CRLF and `.exe` detection** — read the modified Windows prereq scripts and confirm CRLF handling and `.exe` suffix detection are correct. These regressions are invisible to macOS test runs.

You cannot execute `.ps1` scripts directly from macOS, but these three checks catch the most common Windows regression classes without requiring Windows hardware.

---

## Step 1.5b — AI-Bot vs Human Contributor Handling

### AI-Bot PRs: Close in Favor of In-House Work

When an AI-Bot submits a fix to an area with parallel in-house work, close it with:

```
Thank you for the contribution. We're already working on this area in-house
(see issue #NNN). Our version includes tests, live smoke validation, and full
audit coverage. We'll proceed with the in-house approach rather than merging
parallel work. Closed in favor of issue #NNN.
```

There is no goodwill concern — a bot is a tool whose value is the idea, not the effort.

### Human Contributors: Merge or Encourage Forward

- **If the PR is salvageable,** use the fork-edit model (Step 2) to integrate their work
- **If the PR is unsalvageable,** use Principle #6 (close-and-redirect) but include meaningful credit
- Always acknowledge the effort, even if you don't merge the code

---

## Step 1b — Post Feedback With the Right Review Type

When you find merge blockers in Step 1, submit your GitHub review as **`request-changes`**, not
as `comment`. This prevents accidental merge and signals mandatory work clearly.

Structure your review body with explicit sections:

```
## Hard Blockers (must fix before merge)
- [ ] Replace f-string loggers in device_manager.py (23 instances)
- [ ] Register new tool in validator registry

## Minor Items (nice-to-have)
- Consider renaming X for consistency with Y
```

Hard blockers are items from Gates 1–4. Use the `comment` review type only when you have zero
hard blockers and are leaving suggestions.

---

## Hard Blockers (must fix before merge)

See Gates 1–4 above for detailed checklists. Summary:
- F-string loggers in any modified file (Gate 1B)
- Ruff lint violations (Gate 1A)
- Missing Pydantic model wiring for new domains (Gate 2)
- Doc site not updated for tool additions/removals (Gate 3)
- Non-`None` defaults on shared base model fields (Gate 4)
- Mixed API identifier families (Step 1.5)

## Minor Items (nice-to-have)

- Naming alignment with existing conventions
- Test coverage for edge cases not on the happy path
- PR body prose (not blocking, but worth noting)

---

## Step 2 — Apply Fixes (Fork-Edit Model)

If you found gaps in Step 1, don't request changes — fix them directly on the contributor's
fork branch. This is the established model for trusted contributors and for unresponsive first-time contributors with trivial fixes.

```bash
# Add the contributor's fork as a remote (one-time setup)
git remote add <contributor> https://github.com/<contributor>/unifi-mcp.git

# Verify and update the remote URL if stale (e.g., after the unifi-network-mcp → unifi-mcp
# repo rename, or if the fork was recreated since the last PR)
git remote get-url <contributor>
git remote set-url <contributor> https://github.com/<contributor>/unifi-mcp.git  # if URL is wrong

# Fetch and check out their branch
git fetch <contributor>
git checkout -b review/<pr-branch> <contributor>/<pr-branch>

# Make your fixes, commit with attribution context, then push back
git push <contributor> HEAD:<pr-branch>
```

**Tip:** `gh pr checkout <PR-number>` resolves the PR's head ref directly without requiring a named remote. Use this when the remote URL may be stale — it bypasses the rename/recreate gotcha entirely.

**Trusted contributor definition:** Level99 qualifies (7+ merged PRs). For first-time or
low-history contributors, prefer review comments so they learn the patterns.

### Unresponsive First-Time Contributor — Fork-Edit Exception

When a first-time contributor is **historically unresponsive** (72+ hours no response) AND the fix
is **trivial and mechanical** (ruff format, logger replacement, simple doc fix), apply fork-edit
instead of requesting changes. **Reference:** PR #288 — contributor non-responsive to ruff format
request; fork-edit unblocked the PR.

### Org Forks — Push Limitation

**The fork-edit model only works for personal forks.** Org forks block `git push` back even when
"Allow edits from maintainers" is checked — that checkbox is scoped to personal accounts only.

| Fork type | Can push fixes? | Action |
|-----------|----------------|--------|
| Personal fork | ✅ Yes | Fork-edit model |
| Org fork | ❌ No | Merge PR as-is, then commit cleanup to `main` in a follow-up |

---

## Step 3 — Verify PR Body Standards

Before merging, confirm the PR body includes: **What changed**, **Why**, and **Testing notes**
(including live smoke test output for API-touching PRs).

### API-Touching PR Body: Minimum Requirements

1. **Tool summary** — List every tool fixed or added, grouped by category.
2. **Embedded live test output** — Paste raw terminal output (not a prose summary) in a `<details>` block.
3. **Issue references** — `#N` format in both the commit message and the PR body for reliable auto-close.

### When a PR surfaces broader scope (Principle #5)

If reviewing a PR uncovers a pattern warranting a wider architectural fix, open a separate GitHub
issue and link it in the PR body. Use Principle #5 when: **the PR itself is salvageable** but the
idea it surfaces is too big to carry in this PR.

### When the PR itself is unsalvageable — Close-and-Redirect (Principle #6)

1. **Extract valid proposals** — open a new GitHub issue capturing genuine good ideas
2. **Implement in-house** — if high-value, plan to implement on `main`
3. **Credit the contributor** — close with a comment acknowledging them and linking the new issue

**Reference:** PR #142 (riichard) was closed using this pattern.

### Principle #5 vs. Principle #6 — Decision Matrix

| Situation | Principle | Action |
|-----------|-----------|--------|
| PR is good; it just surfaced a bigger idea | **#5** | Keep PR → merge; open separate issue |
| PR has too many concerns to fix cleanly | **#6** | Close PR → extract ideas; implement in-house |
| PR has mechanical gaps (logger, registry) | Fork-edit | Fix directly on fork; don't close |
| Contributor is first-time/low-history | Review comments | Request changes; don't close unless clearly out of scope |

---

## Step 4 — Merge

**Gotcha — `mergeStateStatus: BLOCKED`:** GitHub's `mergeable` field and `mergeStateStatus` are
independent. A PR can show `mergeable: MERGEABLE` while `mergeStateStatus` is still `BLOCKED`
(e.g., required approvals missing, required status checks pending, branch protection rules active).
Always confirm both before running the merge command:

```bash
gh pr view <PR-number> --json mergeStateStatus,reviewDecision,mergeable
```

`mergeStateStatus: BLOCKED` means the PR cannot be merged regardless of `mergeable`. Resolve
the blocking condition (get missing approvals, wait for pending checks) before proceeding.

```bash
# Merge with a merge commit (not squash) to preserve contributor commits
gh pr merge <PR-number> --merge
```

Prefer merge commits over squash so individual commits from the contributor remain visible
in history. Squash only if the branch history is genuinely noisy.

**Merge strategy override:** The merge-commit default can be overridden on explicit user instruction.
If the user specifies squash-merge for a PR, apply it without hesitation — do not silently revert
to the default. Acknowledge the override explicitly. Reference: PRs #315, #316.

---

## Sequential PR Artifact Conflicts

When two community PRs both modify the same generated artifacts (GraphQL schema, REST docs, or
manifest files), the second PR becomes conflicting after the first is merged.

Resolution:
1. Review both PRs before deciding merge order — earlier detection minimizes rebase cycles.
2. After merging the first PR, rebase the second onto updated `main`.
3. Regenerate the affected artifacts on the rebased branch.
4. Push the regenerated artifacts and wait for CI to re-run.
5. Proceed with the standard review checklist on the rebased branch.

Do not merge both PRs in rapid succession without first checking for shared artifact dependencies.

---

## Post-Merge Audit Pattern

If a PR was merged without running this checklist, run a retroactive audit:

```bash
git diff --name-only <merge-commit>^1 <merge-commit>
```

Then run Gates 1–4 against those files. If gaps are found, open a follow-up PR immediately.
PR #122 was audited retroactively using this exact approach.

---

## Community Infrastructure Setup

Set up `.github/` infrastructure when the project goes public or when a new issue category
emerges. This is the upstream foundation that makes PR triage scalable.

The standard layout is: `.github/ISSUE_TEMPLATE/` (structured forms), `.github/config.yml`
(routing rules), `CONTRIBUTING.md` (contribution guidelines including the evidence-first doctrine),
and `SUPPORT.md` (support channels: Discussions for questions, tracker for confirmed bugs only).

### config.yml Routing

Route sensitive and support traffic away from Issues before it arrives:

```yaml
# .github/config.yml
blank_issues_enabled: false
contact_links:
  - name: Security Vulnerability
    url: https://github.com/ORG/REPO/security/advisories/new
    about: Report a security vulnerability via GitHub Security Advisories
  - name: Usage Question / Support
    url: https://github.com/ORG/REPO/discussions
    about: Ask questions and get help in GitHub Discussions
```

`blank_issues_enabled: false` forces all issues through form templates, preventing unstructured
filings. Security reports go to Advisories (private by default); support questions go to Discussions
so the issue tracker stays actionable.

---

## Bug Report Template Design

The bug report form collects hardware-specific context that prevents 3-comment follow-up cycles.
Because unifi-mcp behavior varies by controller firmware, hardware SKU, and install method,
collecting this context at first filing is essential.

### Required Fields (never make optional)

| Field | Type | Why required |
|-------|------|--------------|
| Controller hardware | Dropdown | API behavior varies by hardware family |
| UniFi OS version | Text | Firmware version determines which API fields are present |
| Install method | Text | Determines whether aiounifi version is pinned vs. flexible |
| Client OS | Text | Needed for install-method-specific issues |

**Controller hardware dropdown options:** UDM Pro, UDM Pro Max, UDM SE, UDM (base), UDR / UDR7,
UCG Max / UCG Ultra / UCG Fiber, Cloud Key Gen2 / Gen2+, Self-hosted (Linux), Self-hosted (Docker),
UniFi-hosted (Site Manager / Cloud Console), Other, N/A — not an MCP server bug.

**Per-application version fields** (Network, Protect, Access): label as "Required if reporting a
bug in this app." GitHub Issue Forms don't support conditional `required` — enforce via description text.

### AI-Agent Context Fields (optional — four separate fields)

Because unifi-mcp is used by AI agents, many reported bugs are agent misuse rather than server bugs.
Use four separate optional fields: AI model used, exact prompt, tool calls observed (render: shell),
and raw tool output sanitized (render: json). Optional to avoid friction-stalling non-AI bugs.

**Template impact:** Issue #297 (before template): "MacOS, Claude Code Desktop via uvx" with zero
controller info — three follow-up comments without reproduction. Issue #298 (after template, commit
`b8e8054`): hardware ("UDM Pro") and raw API output on first filing — fix confirmed within 5 minutes.

---

## Evidence-First Issue Triage

Do not implement code changes based on user reports without first establishing reproduction evidence.
UniFi API behavior varies by firmware — a defensive patch without understanding the variance is
either unnecessary or treats a symptom rather than the root cause.

### Triage Checklist (execute in order)

1. **Check template completeness** — Did the reporter provide controller hardware, OS version, and
   install method? If not, request those fields before proceeding.

2. **Establish reproduction** — Run a live smoke test against a real controller, or request raw API
   output from the reporter. The live-smoke Docker environment is the reference reproduction point.

3. **Inspect raw API payloads** — Before any code change, get the raw JSON from the relevant
   controller endpoint. The missing field may be present under a different name, absent only in older
   firmware, or already handled by the codebase.

4. **Rule out alternative explanations:**
   - Version drift (plugin users have pinned aiounifi; source installs may not)
   - Cached vs. live data: the stat/sta endpoint is live-polled; the rest/user snapshot is updated
     infrequently — timing determines what you see
   - API contract differences between hardware families at the same OS version

5. **Confirm hypothesis before coding** — Only after steps 1–4 confirm the bug is real and understood
   should you begin implementation.

**Gotcha: AI-generated analysis without reproduction** — If an AI assistant proposes a code fix for
a bug report, treat that proposal as a starting hypothesis — not a confirmed diagnosis. Issue #297
showed this pattern: initial AI analysis proposed a code change without confirmed reproduction; the
developer correctly pushed back. Always verify with live reproduction before merging any AI-proposed fix.

---

## Quick Reference — Gate Summary

| Gate | Blocker level | Where to look | Common miss |
|------|--------------|---------------|-------------|
| First-time CI auth (Step 0b) | Blocking | GitHub Actions tab | Manual workflow approval not triggered |
| PR type (Gate 0) | Routing gate | PR description + linked issue | Applying feature-addition checklist to a governance/refactor PR |
| Design fit (Gate 0) | Feature PR primary | Scope, duplication, project intent | Mechanical gates pass but tool is out of scope |
| Ruff lint (Gate 1A) | Hard block | Output of `make lint` | Lint violations not run or not fixed |
| F-string loggers (Gate 1B) | Hard block | `*_manager.py` | Manager layer even when tool layer is clean; full-payload calls promoted to INFO |
| No-issue-refs in test strings (Gate 1B) | Hard block | Test docstrings and comment strings in PR diff | `#NNN` literals in pytest docstrings/parameterize IDs invisible to logger scanner |
| Pydantic model wiring (Gate 2) | Critical (silent) | `unifi-core/models/<domain>.py` + tool `to_controller_update` call | Domain model exists but tool bypasses it with raw dict |
| Doc site count (Gate 3) | Ordering gate | Doc site entry count | Updated after merge instead of before |
| Shared pydantic model defaults (Gate 4) | Hard block | `<Domain>Base` model in `unifi-core` | Non-None defaults on shared base model fields silently overwrite update-tool fields |
| API family boundary (Step 1.5) | Hard block | Tool ID types and nested object references | V2 ObjectID and Integration UUID mixed in same tool surface |
| HA/shadow mode transience (Step 1.5) | Environment issue (not code) | Live smoke test error messages | Blocking merge on HA sync timeouts; retry after stabilization |
| mergeStateStatus:BLOCKED (Step 4) | Blocking | `gh pr view --json mergeStateStatus,reviewDecision` | Merging when protection rules block despite mergeable:MERGEABLE |
| AI-Bot vs human (Step 1.5b) | Precedent gate | Issue tracker + PR scope | Merging bot PRs with parallel in-house work; missing credit for human contributors |
| Live smoke tests (Step 1.5) | Validation requirement | `scripts/live_smoke.py` output | Approval without actual live controller tests; mock-only validation |
| Independent maintainer smoke (Step 1.5) | Non-optional standing rule | Maintainer's own smoke run (not contributor's) | Accepting contributor's smoke results without running independent suite |
| Plugin invokes published package (Step 1.5) | Coverage gap | MCP plugin tool calls during PR branch validation | Verifying branch-local fix via plugin before publishing; fix appears absent |
| Enum-hint PRs (Step 1.5) | Coverage gap | Targeted script with explicit enum args | Harness defaults miss all constrained parameter paths |
| Hardware-gated deferral (Step 1.5) | Deferral gate | Four-condition checklist | Blocking merge on hardware-absent failures without documenting deferral |
| uiprotect 401 (Step 1.5) | Benign noise | Live smoke Protect bootstrap output | Filing bug or blocking merge on expected startup probe 401 |
| Mutation cycles (Step 1.5) | Field preservation blocker | Create → update → verify → delete cycle | Update tools that reconstruct objects silently zero fields |
| Cross-platform PRs (Step 1.5) | Validation requirement | Plugin bundle .ps1, stdio auth probe, prereq scripts | Approving Windows-targeting PRs without macOS cross-platform checks |
| Issue triage (Triage section) | Evidence gate | Raw API payload from reporter | Implementing fixes without confirmed reproduction or raw payload inspection |
