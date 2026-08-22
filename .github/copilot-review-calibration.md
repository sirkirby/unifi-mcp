# Copilot PR Review Calibration

This runbook calibrates GitHub Copilot Code Review before automatic reviews are enabled. Copilot remains advisory; a human maintainer makes every approval and merge decision.

## Corpus

Use six pull requests and record each exact head SHA:

- Three opaque draft replay pull requests whose source mappings exist only in the private Myco evidence register.
- Three qualifying future community pull requests whose governance sources are byte-identical to configured `main`.

Across the final corpus, cover all six categories:

1. Straightforward bug or packaging change.
2. Controller-facing feature.
3. Cross-surface model, REST, GraphQL, MCP, relay, or serialization change.
4. Authentication or session-lifecycle change.
5. Hardware-sensitive response, event, endpoint, or mutation behavior.
6. Dependency-only negative control.

A case is invalid if `AGENTS.md`, `.github/copilot-instructions.md`, or `.github/skills/unifi-mcp-code-review/SKILL.md` differs byte-for-byte from configured `main`; if review attribution/session logs do not prove instruction and skill loading; if effort is not Balanced; or if agentic context is degraded.

Private source mappings, human baselines, and expected findings must be unavailable through any configured MCP server until scoring is complete. If server-side exclusion cannot be proven, disable MCP access for calibration reviews.

## Procedure

For each case:

1. Construct the exact final review head and record its base SHA, head SHA, changed files, and CI state.
2. Prove the three governance sources are byte-identical to configured `main`.
3. Complete and save the human baseline against that exact head before reading Copilot output.
4. Revalidate every expected blocker/high finding on that head and record expected test gaps, live-hardware requirement, and disposition.
5. Immediately before review, prove the head/base SHAs are unchanged and repeat governance equality.
6. Request Copilot from the Reviewers menu and select **Balanced**.
7. Verify `AGENTS.md`, repository instructions, and `unifi-mcp-code-review` through attribution or session logs.
8. Fetch the completed Copilot review object and require its `commit_id` to equal the baselined head SHA.
9. Score the result in Myco evidence plan `b63330a19102f440` and verify the whole-content save through readback.

## Per-case scorecard

| Field | Recorded value |
|---|---|
| Case ID and exact head SHA | — |
| Base SHA and changed files | — |
| Governance byte-equality proof | — |
| Category coverage | — |
| Human baseline completed first | — |
| Known blocker/high findings | — |
| Copilot blocker/high true positives | — |
| Copilot blocker/high false positives | — |
| Valid novel findings | — |
| Required live validation | — |
| Copilot live-validation decision correct | — |
| Unsupported CI/test/hardware claims | — |
| Style or deterministic-CI duplicate comments | — |
| Expected disposition | — |
| Actual disposition | — |
| Copilot review ID | — |
| Copilot review `commit_id` | — |
| `AGENTS.md` loaded | — |
| Repository instructions loaded | — |
| Review skill loaded | — |
| Review effort shown as Balanced | — |
| Approximate AI-credit/Actions usage | — |
| Review text or stable excerpts and session URL | — |
| Case valid for calibration | — |

Recall is `true positives / known blocker-high findings`. Precision is `true positives / all Copilot blocker-high findings`. A case with no known blocker/high finding contributes no recall denominator; a case with no Copilot blocker/high finding contributes no precision denominator.

## Activation gates

Automatic review may be enabled only when:

- All six categories are covered by six valid cases.
- At least five independently verified blocker/high findings remain present across at least two replay heads.
- At least one clean negative-control case is present.
- Aggregate known blocker/high recall is at least 80%.
- Aggregate Copilot blocker/high precision is at least 80%.
- Recall and precision both have non-zero denominators; zero is an automatic no-go.
- Every hardware-gated case receives the correct live-validation requirement.
- There are zero fabricated claims about CI, tests, controller calls, or hardware.
- Copilot never says `READY FOR MAINTAINER REVIEW` while a known blocker remains.
- Instruction and skill loading are proven for every case.
- Style/CI-duplicate noise averages no more than one comment per case.
- Calibration remains within the maintainer-approved AI-credit, Actions-minute, and invalid-rerun ceilings selected before the first replay review.
- The maintainer reviews the completed scorecard in evidence plan `b63330a19102f440` and explicitly approves activation.

Failure does not weaken a gate. Tune the instructions or skill, then rerun three cases for instruction-only changes or the full six-category corpus for material skill, trust-boundary, MCP, model-policy, or effort changes.

## Evaluation after activation

During normal maintenance, evaluate up to the first 20 automatic reviews. Make manual checkpoints after approximately 5, 10, and 20 reviews or after 30 days, recording compact rows in the separate Myco evidence plan. Track eligible community PRs, automatic triggers, and manual fallbacks separately. No background observer, webhook, database, dashboard, or scheduled job is created.

Repeated automatic-trigger failure for normal community contributors requires a return to manual review requests even when semantic quality remains acceptable.

At each checkpoint choose: continue unchanged, continue observation, tune and recalibrate, disable new-push review, return to manual review requests, or disable Copilot review.

## Immediate rollback triggers

- Any fabricated CI, test, controller, or hardware claim.
- Any ready disposition while a known blocker remains.
- Repeated failure to require hardware validation.
- Blocker/high precision below 70% across five consecutive reviews.
- Excessive repeated comments after new pushes.
- Cost reaches the maintainer-approved AI-credit, Actions-minute, or rerun ceiling.

Rollback order: disable new-push review; disable the automatic-review ruleset and return to manual requests; disable Copilot review entirely. Rollback never changes `protect-main` or human approval requirements.
