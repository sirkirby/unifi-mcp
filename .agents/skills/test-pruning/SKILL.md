---
name: test-pruning
description: |
  Remove, fold or consolidate redundant tests in unifi-mcp without losing a check. Use when
  asked to trim, prune, shrink or deduplicate the test suite, to fold copy-pasted tests into
  parametrized ones, or to review a PR that deletes or folds tests.
---

# Test pruning

A pruning pass makes the suite smaller while every check still holds. The bar for what may go is
`AGENTS.md` → Test Assertions; this skill is how to apply it at scale. Scripts live in `scripts/`.

The trap is that coverage cannot see a **weakened** test: one that still runs the same code but
would now pass a broken result. On the first pass, branch coverage stayed at zero loss while
review found nine weakened tests. Every gate below exists to catch what coverage misses.

## 1. Baseline

Run `scripts/cov_ctx.sh <worktree> <suite> <out>.coverage` for every suite you will touch, on an
untouched worktree of the base commit. Suites: `core shared relay network protect access api`.
It records per-test branch coverage and unsets `UNIFI_*` first, since exported settings change
which tests collect.

Done when each suite you will touch has a baseline file named `base.<suite>.coverage` in one directory.
Keep the baseline of every other suite there too: step 2 reads them to decide ownership.

## 2. Candidates

`python3 scripts/candidates.py <suite> <baseline-dir> <worktree> <out>.json [exclude.txt]` lists
test functions whose coverage other tests already provide, with the kept tests that overlap each
most. It keeps every arc in the suite's own package, plus arcs in other packages that the owning
suite does not cover, which matches how CI measures coverage. Security, redaction, drift,
symmetry, contract, golden and incident-evidence tests are never candidates.

A candidate is only a lead. In the app suites, many managers now live in `unifi_core`, and the core
suite often runs that code without asserting it, so the app test is the only real check. Expect
to keep most app-suite candidates; folding copy-pasted tests saves more than deleting.

Done when each suite has a candidate file.

## 3. Review every candidate

For each candidate, open it and the kept tests it overlaps, and decide from the assertions:

- **Delete** only under the `AGENTS.md` bar: a kept test asserts the same thing on the same input.
  Record that kept test and its exact assertion.
- **Fold** tests with the same body into one parametrized test, keeping every case and assertion.
- **Keep** everything else, with a one-line reason.

Write a ledger: one row per deleted or folded test, naming the kept test and assertion that
covers it. `scripts/foldsummary.py <ledger.md>...` turns ledgers into a PR-sized summary.

Done when every candidate has a row and every deletion names an exact counterpart.

## 4. Gates before the PR

Run all of these on the finished branch; each catches a different kind of weakened test.

1. **Coverage**: `scripts/cov_ctx.sh` on the branch, then `python3 scripts/arcdiff.py <suite>
   <baseline-dir> <after>.coverage` must report no required arc lost. A few arcs are reached
   nondeterministically (the `unifi_api/services/managers.py` loop near line 2045, and the
   connection- and event-manager arcs in `unifi_core/network/managers` reached by the
   `test_server_cleanup.py` connect race). Treat a loss as flaky only after a rerun of the
   unchanged base loses the same arcs.
2. **Weakening scan**: `python3 scripts/weakscan.py <repo> <base-ref> <branch>` flags loops over a
   returned collection with no length check, and expected values that share an object with the
   input under test. Fix or justify each finding.
3. **Independent review**: give a reviewer that did not make the changes only the diff, the
   ledger and the scan output. Ask it to compare every deleted or folded test's assertions with
   what replaced them, and to name any dropped assertion or weaker replacement (empty data,
   different input, a broader end-to-end test). This is the only gate that catches an assertion
   dropped inside a fold.
4. **Mutation diff** (optional, for deletions in high-risk code): `python3 scripts/mutdiff.py
   <clean-worktree> <source-file> <function>[,...] <test-file> <base-ref> <branch>` reports bugs
   the original tests caught that the changed tests let through. It costs one pytest run per
   mutant, so scope it to the functions behind the deletions you are least sure of.

Done when coverage reports no unexplained loss, every scan finding is fixed or justified, and the
reviewer's findings are resolved.

## 5. PR

One PR per suite group, with the ledger summary, collected cases before and after, net lines, and
the coverage result. Then address every valid point in the Copilot review before merging.
