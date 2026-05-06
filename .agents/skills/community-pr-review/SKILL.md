---
name: myco:community-pr-review
description: |
  Use this skill when reviewing or merging any community PR in unifi-mcp — even if the user
  just says "take a look at this PR" or "can we merge this." Covers the complete quality gate
  checklist (f-string logger ban, validator registry registration, doc site update ordering),
  the fork-edit model for trusted contributors, org-fork push limitations, the dual-subagent
  review pattern, PR body standards, technical API validation (live smoke tests, mutating
  cycles), and the close-and-redirect pattern for unsalvageable PRs. Apply this skill before
  approving any externally-authored PR, before running the merge command, and when auditing
  recently merged PRs for compliance.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Community PR Review and Merge

Community PRs go through a fixed quality checklist before merge. For trusted contributors
(level99 has 7+ merged PRs), the maintainer commits fixes directly to the contributor's fork
branch rather than requesting round-trip revisions — this preserves attribution while eliminating
latency. This skill documents the full workflow from first look to merge commit, including
technical validation for PRs that touch UniFi API tool implementations.

## Prerequisites

- PR is open and CI workflow state is understood (see Step 0b for first-time contributor gotcha)
- You have push access to the contributor's fork (needed for the fork-edit model)
- `AGENTS.md` is current — it is the canonical source for hard bans
- For PRs touching tool implementations or API handlers: a **live UniFi controller** must be reachable to run smoke tests

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
→ Run Gates 1–4 as written below.

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
   returned by list tools vs. `source_macs: str` accepted by create). This is CI-enforced via
   `tests/unit/test_tool_field_symmetry.py`'s type assertion requirement (issue #137 scope
   extension).
4. **No field leakage?** — Fields belonging to one resource variant must not silently appear
   on another through inheritance.
5. **Matches issue spec?** — Compare against the linked GitHub issue. Every scoped item should
   be implemented; nothing out of scope should be added.
6. **Pattern symmetric with AGENTS.md rule?** — The implementation must align with the
   field-symmetry governance rule in `AGENTS.md`, not diverge from it.

Gates 1–4 (f-string logger, validator registry, doc site, shared validator blast radius) still
apply to governance PRs for any new or modified tool/manager files — but the structural
questions above are the primary gate.

**Why the split matters:** PR #140 (ACL shared-field-model pilot, level99) was reviewed with
the feature-addition checklist. The structural questions were asked only because the reviewer
recognized the PR type. A structural refactor can pass Gates 1–3 cleanly while still violating
inheritance structure, field coverage, or type symmetry — the feature-addition checklist gives
false confidence on governance PRs.

---

### Gate 1: F-String Logger — Hard Blocker

**Primary target:** Every `*_manager.py` file the PR touches.

Scan for f-string logger calls:

```bash
grep -rn 'logger\\.\\(debug\\|info\\|warning\\|error\\|critical\\)(f"' \\
  $(git diff --name-only origin/main...HEAD)
```

Replace any hits with `%s`-style lazy formatting:

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

**Implicit concatenation is invisible to grep:** Adjacent string literals (`"foo" "bar"`) cannot
be reliably caught by automated scripts. This survived a 481-call automated migration in PR #122
and was only caught by manual review. Scan manually for this pattern when logger calls span lines.

**Full-payload logging promoted to INFO level:** A `logger.debug` call that dumps a full JSON
payload is acceptable at DEBUG level but becomes a production noise and data-exposure risk if
promoted to `logger.info`. Watch for this in manager files — it appeared at `firewall_manager.py`
line 622 in PR #146. All full-payload log calls must use `logger.debug`.

```python
# BLOCKED: full payload at INFO level
logger.info("Firewall policy response: %s", json.dumps(response))

# REQUIRED: full payload at DEBUG level only
logger.debug("Firewall policy response: %s", json.dumps(response))
```

**Why this is a hard ban and not a suggestion:** F-string loggers eagerly evaluate all arguments
even when the log level is suppressed. On deployments with debug logging disabled, this creates
unnecessary overhead on every suppressed call.

---

### Gate 2: Validator Registry — Silent Failure Risk

**Target:** Any PR introducing a new tool or manager.

New tools must be registered in the validator registry. An unregistered tool silently skips
validation at runtime — no error, no warning, just unvalidated data passing through.

Check that each new tool has a corresponding entry. Verify the registration file exists and
the new tool's name appears in it. If the contributor added a tool but not a registry entry,
add it before merging.

**The `validated_data` gotcha (from PR #123):** When a validator exists but the tool accesses
`request.params` directly instead of `validated_data`, validation runs but its output is
silently discarded. After confirming a tool is registered, also confirm it reads from
`validated_data`, not from the raw params object.

---

### Gate 3: Doc Site Update — Ordering Gate

**Target:** Any PR that adds, renames, or removes tools.

The doc site must be updated as part of the same PR — not as a follow-up. The ordering matters:
the doc site should be updated *after* the tool code is finalized but *before* merge, so the
published docs stay in sync with the merged code at every point in history.

For PR #126, this gate was explicitly enforced — the PR wasn't merged until doc counts matched.

Verify: does the PR update the doc site entry count and tool listing to match what's being
merged? If not, either request the update or make it yourself before merging (see Step 2).

---

### Gate 4: Shared Validator Modifications — Blast Radius Check

**Target:** Any PR that modifies a shared validator class (e.g., `ResourceValidator.validate()`).

If a PR injects schema defaults into a shared `validate()` method, every update tool that calls
the method will silently overwrite fields the caller intentionally omitted — a data-loss bug with
blast radius across all 37+ default-using properties and all three app packages.

**Hard blocker pattern:**

```python
# DANGEROUS — defaults injected into shared validator
class ResourceValidator:
    def validate(self, data: dict) -> dict:
        data.setdefault("create_allow_respond", False)  # silently overwrites on update
        data.setdefault("schedule", {"mode": "ALWAYS"})  # silently overwrites on update
        return data
```

With this code, `update_firewall_policy({"name": "new"})` would silently inject unwanted field
values — overwriting whatever the controller currently has, regardless of what the caller specified.

**The rule:** Defaults belong in create-specific code paths only (or in an explicit opt-in method
such as `validate_and_apply_defaults()` that update tools do not call). Any PR that adds defaults
to a shared validator code path is a **hard blocker**.

This gate emerged from PR #146. Check for it whenever the PR diff touches a class that both
create and update tools inherit from or call into.

---

## Step 1.5 — API-Touching PRs: Live Validation Requirements

For any PR that modifies UniFi MCP tool implementations, fixes API integration bugs, or adds new
handlers, apply additional technical validation before merge. The UniFi controller is stateful
and mock-based tests do not catch real-world edge cases.

### Smoke Test Coverage (All API-Touching PRs)

Run `scripts/live_smoke.py` against a live controller — not a mock — before opening or approving
the PR.

**Coverage requirement:** All touched tools must pass, and you must also run the full cross-category
sweep to confirm no lateral regressions across the ~37 tools / 15 categories.

```bash
# Run read-only + preview smoke tests against the network server
python scripts/live_smoke.py --server network --phase safe

# Run all servers (network + protect + access)
python scripts/live_smoke.py --server all --phase safe
```

**What "passing" means:**
- Each tool returns a structurally valid response (correct keys, expected types).
- No unexpected errors or stack traces in the output.
- Tools that list resources return at least the expected schema shape even when the controller has no objects of that type.

**Gotcha:** A tool that was already broken before the PR is still your responsibility to flag. Don't
silently skip known-broken tools — note them explicitly in the PR description so the reviewer knows
the scope of the damage.

**Gotcha:** Mock tests give false confidence. The UniFi controller is quirky — response shapes
differ between controller versions, and some fields only appear when specific configuration exists.
A test that passes against a mock may fail silently against a real controller.

### Mutating Cycle Tests (Create/Update/Delete PRs)

For any PR that touches create, update, or delete handlers, run a full mutating cycle using
`--phase approved` — not just the happy path.

**Full cycle:**
1. **Create** — create the resource via the tool; capture the returned ID.
2. **Partial update** — update only a subset of fields using the tool.
3. **Verify field preservation** — read back the resource and confirm fields you did NOT update are unchanged.
4. **Delete** — remove the resource and confirm it is gone (expect 204 or equivalent).

**Why field preservation matters:** The UniFi API silently drops fields that aren't included in a
PUT/PATCH body. An update tool that reconstructs the full object from only the changed fields can
accidentally zero out existing configuration. The verify step is the only reliable way to catch this.

**Example output to embed verbatim in the PR:**
```
[CREATE] unifi_create_firewall_policy "test-smoke-policy" → id: abc123 ✓
[UPDATE] set description="updated", name unchanged → read back: name="test-smoke-policy" ✓
[DELETE] abc123 → 204 No Content ✓
```

---

## Step 1b — Post Feedback With the Right Review Type

When you find merge blockers in Step 1, submit your GitHub review as **`request-changes`**, not
as `comment`. This matters for two reasons:

1. **Prevents accidental merge** — GitHub blocks merging a PR that has an unresolved
   "request changes" review, even if CI is green.
2. **Signals mandatory work clearly** — the contributor sees their PR requires action, not just
   feedback.

Structure your review body with explicit sections:

```
## Hard Blockers (must fix before merge)
- [ ] Replace f-string loggers in device_manager.py (23 instances)
- [ ] Register new tool in validator registry

## Minor Items (nice-to-have)
- Consider renaming X for consistency with Y
```

Hard blockers are items from Gates 1–4. Minor items are suggestions that won't delay merge.
Use the `comment` review type only when you have zero hard blockers and are leaving suggestions.

---

## Step 2 — Apply Fixes (Fork-Edit Model)

If you found gaps in Step 1, don't request changes — fix them directly on the contributor's
fork branch. This is the established model for trusted contributors.

```bash
# Add the contributor's fork as a remote (one-time setup)
git remote add <contributor> https://github.com/<contributor>/unifi-mcp.git

# Fetch and check out their branch
git fetch <contributor>
git checkout -b review/<pr-branch> <contributor>/<pr-branch>

# Make your fixes, then commit with attribution context
git commit -m "fix: address review gaps from PR #NNN

- Replace f-string loggers in device_manager.py (14 instances)
- Register new validator in registry
Co-authored-by: Contributor Name <email>"

# Push back to their fork
git push <contributor> HEAD:<pr-branch>
```

**Why fork-edit instead of review comments:** For contributors with a track record, a review
comment requesting changes introduces a multi-hour latency (timezone, notification lag, second
review round). Fixing directly and crediting in the commit message is faster and maintains
the contributor's name in the merge commit. Use judgment — this model is appropriate when
the gap is mechanical and the fix is unambiguous.

**Trusted contributor definition:** Level99 qualifies (7+ merged PRs). For first-time or
low-history contributors, prefer review comments so they learn the patterns.

### Org Forks — Push Limitation

**The fork-edit model only works for personal forks.** Org forks (e.g., `vigrai/unifi-mcp`
from contributor fgallese in PR #133) block `git push` back to the contributor's branch even
when "Allow edits from maintainers" is checked on the PR. That checkbox is scoped to personal
accounts — GitHub does not honor it for org-owned forks.

Decision matrix:

| Fork type | Can push fixes? | Action |
|-----------|----------------|--------|
| Personal fork (e.g., `level99/unifi-mcp`) | ✅ Yes | Fork-edit model as described above |
| Org fork (e.g., `vigrai/unifi-mcp`) | ❌ No | Merge PR as-is, then commit cleanup directly to `main` in a follow-up commit |

When merging an org-fork PR as-is and fixing on main, record what was fixed and why in the
follow-up commit message so the history is traceable.

---

## Step 3 — Verify PR Body Standards

Before merging, confirm the PR body includes:

- **What changed** — which tools or managers were added/modified
- **Why** — the use case or problem being solved
- **Testing notes** — how to verify the change works (including live smoke test output for API-touching PRs)

If the PR body is sparse, edit it before merging. The PR body becomes part of the git log
context and is referenced in future sessions when diagnosing regressions.

### API-Touching PR Body: Minimum Requirements

For PRs that modify tools or API handlers, the PR description must include:

**1. Tool summary** — List every tool fixed or added, grouped by category:

```markdown
### Tools Changed
- **unifi_get_client_details** — fixed null-check on optional connection field (#138)
- **unifi_create_firewall_policy** — new tool (#142)
- **unifi_update_firewall_policy** — new tool (#142)
```

**2. Embedded live test output** — Paste the raw terminal output (not a prose summary). Reviewers
need actual values and shapes, not "tests passed."

```markdown
<details>
<summary>Live test output (controller 8.x, 2024-04-01)</summary>

```
[paste raw output here — do not summarize]
```

</details>
```

Reviewers have been burned by "all tests passed" summaries that omit the one tool that returned a
malformed response. Embed the raw output and let the reviewer decide what matters.

**3. Issue references** — Tag every issue using `#N` format. GitHub autolinks and auto-closes on merge:

```
Closes #142, #155
```

**Gotcha:** If you reference an issue in the commit message but not in the PR body, GitHub's
auto-close only triggers reliably when the PR body contains the `#N` reference. Put it in both.

### When a PR surfaces broader scope (Principle #5)

If reviewing a PR uncovers a pattern that warrants a wider architectural fix (beyond what this
contributor's PR should carry), open a separate GitHub issue rather than expanding the PR.
Link the issue in the PR body for context. This keeps the PR focused and creates community
visibility for the broader discussion.

Use Principle #5 when: **the PR itself is salvageable** but the idea it surfaces is too big
to carry in this PR.

### When the PR itself is unsalvageable — Close-and-Redirect (Principle #6)

Some PRs are too scattered, unfocused, or structurally misaligned to merge or fix via the
fork-edit model. When the PR as a whole cannot be salvaged, **close it constructively** rather
than requesting rework:

1. **Extract valid proposals** — identify any genuinely good ideas in the PR and open a new
   GitHub issue capturing them. Write the issue clearly enough that a different contributor
   (or the maintainer) can implement the ideas properly.
2. **Implement in-house** — if the ideas are high-value, plan to implement them directly on
   `main` rather than accepting a rework of the original PR.
3. **Credit the contributor** — close the PR with a comment that acknowledges the contributor
   for surfacing the problem, links the new issue, and explains why the PR was closed rather
   than revised. This keeps the community relationship healthy.

**Reference:** PR #142 (riichard) was closed using this pattern. The PR had multiple overlapping
concerns that couldn't be cleanly separated. Valid proposals were extracted to a GitHub issue;
the contributor was credited in the close comment.

### Principle #5 vs. Principle #6 — Decision Matrix

| Situation | Principle | Action |
|-----------|-----------|--------|
| PR is good; it just surfaced a bigger idea | **#5** | Keep PR → merge it; open separate issue for the bigger idea |
| PR has too many concerns to fix cleanly | **#6** | Close PR → extract ideas to issue; implement in-house |
| PR has mechanical gaps (logger, registry) | Fork-edit | Fix directly on fork; don't close |
| Contributor is first-time/low-history | Review comments | Request changes; don't close unless clearly out of scope |

The key question: *can a targeted fix make this PR mergeable?* If yes → Principle #5 or
fork-edit. If no → Principle #6.

---

## Step 4 — Merge

Once all gates pass and any fixes are committed to the fork branch:

```bash
# Merge with a merge commit (not squash) to preserve contributor commits
gh pr merge <PR-number> --merge
```

Prefer merge commits over squash so individual commits from the contributor remain visible
in history. Squash only if the branch history is genuinely noisy.

---

## Post-Merge Audit Pattern

If a PR was merged without running this checklist (e.g., merged by a contributor directly),
run a retroactive audit:

```bash
# Find files changed in the merge commit
git diff --name-only <merge-commit>^1 <merge-commit>
```

Then run Gates 1–4 against those files. If gaps are found, open a follow-up PR immediately.
Don't let an unreviewed merge sit — the pattern compounds. PR #122 was audited retroactively
using this exact approach and a fix PR was opened the same session.

---

## Quick Reference — Gate Summary

| Gate | Blocker level | Where to look | Common miss |
|------|--------------|---------------|-------------|
| First-time CI auth (Step 0b) | Blocking | GitHub Actions tab | Manual workflow approval not triggered |
| PR type (Gate 0) | Routing gate | PR description + linked issue | Applying feature-addition checklist to a governance/refactor PR |
| F-string loggers (Gate 1) | Hard block | `*_manager.py` | Manager layer even when tool layer is clean; full-payload calls promoted to INFO |
| Validator registry (Gate 2) | Critical (silent) | Registry file + `validated_data` usage | Tool registered but reads raw params |
| Doc site count (Gate 3) | Ordering gate | Doc site entry count | Updated after merge instead of before |
| Shared validator defaults (Gate 4) | Hard block | `ResourceValidator.validate()` and any shared validator class | Defaults injected into shared path silently overwrite update-tool fields |
| Live smoke tests (Step 1.5) | Validation requirement | `scripts/live_smoke.py` output | Approval without actual live controller tests; mock-only validation |
| Mutation cycles (Step 1.5) | Field preservation blocker | Create → update → verify → delete cycle | Update tools that reconstruct objects silently zero fields |
