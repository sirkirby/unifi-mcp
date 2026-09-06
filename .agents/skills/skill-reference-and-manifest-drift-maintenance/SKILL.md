---
name: myco:skill-reference-and-manifest-drift-maintenance
description: |
  Use when adding, changing, or reviewing tool categories, tool parameters,
  or tool docstrings in unifi-mcp apps (apps/access, apps/network,
  apps/protect) whose behavior surfaces through generated artifacts: each
  app's generated tool manifest (e.g.
  apps/protect/src/unifi_protect_mcp/tools_manifest.json) and the plugin
  skill reference docs with AUTO:tools:<category> marker blocks. Applies
  even if the user only asks to "add a tool" and doesn't mention manifests
  or docs — generated artifacts are a deterministic function of Python
  source and CI's drift-check gate only verifies rendered content matches
  disk, never that a new category/tool got a section, marker, or
  full-depth description. Covers: regenerating manifests/skill-references
  after source changes, the new-tool-category checklist (ToC + AUTO
  markers + generator run), resolving generated-manifest merge conflicts
  by regeneration (never by hand), and catching pre-existing drift
  surfaced when an unrelated PR trips the reference-check CI gate.
managed_by: myco
user-invocable: true
allowed-tools: Read, Edit, Write, Bash, Grep, Glob
---

# Skill Reference & Generated Manifest Drift Maintenance

Each app has a generated tool manifest (e.g.
`apps/protect/src/unifi_protect_mcp/tools_manifest.json`) and a generated
skill reference doc under the corresponding plugin (e.g.
`plugins/unifi-network/skills/unifi-network/references/network-tools.md`,
`plugins/unifi-access/skills/unifi-access/references/access-tools.md`)
that uses `<!-- AUTO:tools:<category> -->` marker blocks. Both are
**generated artifacts** — a pure function of the Python source
(docstrings, parameter signatures, tool registrations).
`packages/unifi-mcp-shared/src/unifi_mcp_shared/manifest_generator.py`
implements the shared manifest-generation logic that each app's own
generator wrapper script calls (e.g.
`apps/network/scripts/generate_tool_manifest.py`, invoked via that app's
`make manifest` target). Nothing about these generated files should ever
be hand-authored. The recurring failure mode in this codebase is not that
regeneration is hard — it's that CI's drift-check only diffs
*already-rendered* content against disk. It cannot detect a missing
section, a missing marker, or a description that's technically present
but shallower/staler than the source. Those gaps are only caught by a
human applying the checklists below.

## Prerequisites

- Locate the generator scripts for this repo before starting — search
  `scripts/` (e.g. `Grep -r "tools_manifest" scripts/` and
  `Grep -r "generate_tool_manifest\|generate_skill_references" scripts/`)
  rather than assuming a fixed filename, since generator script names can
  move between refactors. Verified examples in this repo:
  `scripts/generate_skill_references.py`, the shared
  `packages/unifi-mcp-shared/src/unifi_mcp_shared/manifest_generator.py`
  module, and the per-app wrapper it documents (e.g.
  `apps/network/scripts/generate_tool_manifest.py`, run via that app's
  `make manifest` target).
- Locate the skill reference doc(s) for the category you're touching by
  searching repo-wide for `AUTO:tools:` markers (`Grep -rl "AUTO:tools:" .`)
  rather than assuming a fixed path. These live under each plugin's own
  skill references directory (`plugins/<plugin>/skills/<plugin>/references/*.md`)
  — not under `apps/` — and the exact category set can vary per plugin.
- Regenerate inside a worktree venv synced to the **locked dependencies**.
  Using system Python or a stale venv can produce output that's subtly
  different from what CI would generate, defeating the point of
  regenerating at all.
- `make pre-commit` **does** regenerate manifests when it's actually run —
  both the root Makefile (`pre-commit: format generate lint test
  check-generated worker-typecheck`, where `generate` includes `manifest`)
  and each app's own Makefile (e.g. `apps/network/Makefile`:
  `pre-commit: format manifest server-manifest lint test`). But there is
  no `.pre-commit-config.yaml` wiring it into a git hook — it's a manual
  `make` target. Don't assume a branch's manifest is current just because
  its author "probably ran pre-commit"; check explicitly (Procedure A)
  whenever behavior-relevant source changed.

## Procedure A: Regenerate after any behavior/schema-relevant source change

Any change to a meta-tool's documented behavior, or a tool parameter's
type/default, requires regenerating the manifest *and* manually diffing
the generated text — not just confirming a description field exists.

1. Make the source change (docstring, parameter signature, etc.) in the
   Python source — e.g. a shared meta-tool module like
   `packages/unifi-mcp-shared/src/unifi_mcp_shared/meta_tools.py`, or an
   app's own tool module.
2. Run the manifest generator for every affected app (`make manifest` at
   the app level, or `make generate` at the repo root for all apps).
3. Diff the app's regenerated manifest for **content parity**, not just
   presence: does the new manifest text actually carry the same depth of
   detail as the docstring (edge cases, defaults, caps, thresholds), or
   did it fall back to abbreviated legacy text?
4. If a parameter's default or type changed, confirm the manifest
   description string was regenerated *after* the docstring update — an
   ordering bug (regenerate-then-edit-docstring, instead of
   edit-docstring-then-regenerate) silently ships mismatched schema even
   though runtime behavior stays correct. Example seen in this codebase:
   a parameter changed from `list[str] = []` to `Optional[list[str]] =
   None` at runtime coalesces identically (`value or None`), but a
   manifest generated before the docstring update still described the
   old "empty list" default — confusing for any LLM client reading the
   JSON schema directly instead of the Python source.
5. Treat "the description field exists" as insufficient review signal.
   The CI drift-check only fails on differing rendered content for
   fields/markers that already exist — it will pass even when the
   content is stale or abbreviated, because presence ≠ parity.

## Procedure B: New tool category checklist (skill reference docs)

Adding a new tool category (e.g. a new settings category surfaced in a
plugin's skill reference doc) requires three things, and bumping a tool
count is not one of them:

1. **ToC entry** for the category in the relevant plugin's skill
   reference file (`plugins/<plugin>/skills/<plugin>/references/*.md`).
2. **Section block** with `<!-- AUTO:tools:<category_name> -->` /
   closing marker comments (match the exact naming convention used by
   neighboring sections in the same file — e.g. the `doors`, `policies`,
   `credentials` sections in
   `plugins/unifi-access/skills/unifi-access/references/access-tools.md`,
   or the `clients`, `devices`, `firewall` sections in
   `plugins/unifi-network/skills/unifi-network/references/network-tools.md`).
3. **Run the generator** and confirm the section is actually populated
   with tool entries — not just that the total tool count changed.

Why this matters: the drift-check flag only fails when re-rendered
content *differs* from what's on disk for markers that already exist. A
PR that adds tools but skips the ToC/section/markers entirely will pass
CI cleanly while leaving the new tools completely undiscoverable in the
reference doc — the count goes up, but an agent reading the doc body
never finds them. This must be caught in review, not by the pipeline.

## Procedure C: Resolve generated-manifest merge conflicts by regeneration

When merging `main` into a working branch (fork-edit, rebase, or a
long-lived branch catching up), a conflict in the app's generated
manifest file is the *expected* failure mode whenever both branches
touched any tool in that app — it is not a real content conflict, it's
two independent generation runs colliding.

1. Accept the merge with conflict markers present in the manifest file
   (don't try to hand-resolve the diff).
2. Regenerate the manifest from the now-merged Python source tree, using
   the exact same generation command CI uses (the app's `make manifest`
   target).
3. Stage the freshly regenerated file in place of the conflicted one.
4. Do this inside a worktree venv synced to locked dependencies so the
   output is byte-identical to what CI would produce — a stale venv can
   produce a "regenerated" file that still diffs from CI's expectation.

Never resolve a manifest conflict by manually editing either side of the
diff — because the manifest is a deterministic function of source, manual
resolution only *looks* plausible; regeneration is the only version
guaranteed correct by construction. This class of conflict is enabled by
`make pre-commit` being a manual target rather than an enforced git hook:
a branch that never re-ran `make pre-commit` (or `make manifest`) after
`main` moved forward will carry a stale manifest that then conflicts on
merge.

## Procedure D: Catch dormant drift when an unrelated PR trips the CI gate

The reference-check CI gate (the root Makefile's `check-skill-references`
/ `check-generated` targets) only fires when the generated manifest or a
reference file *changes* in the current PR. That means a category
shipped months earlier with a skipped documentation step (missing ToC
entry, missing `AUTO:tools:<category>` markers) can sit silently broken
until some unrelated PR happens to touch the same generated files and
trips the gate.

1. When the gate fires unexpectedly (or during any manifest/reference
   review), check whether the flagged gap actually originates from the
   current change or is pre-existing drift from an earlier PR.
2. If pre-existing: bundle the drift fix into the PR that tripped the
   gate rather than filing a separate fix — it's faster and unblocks the
   triggering PR immediately.
3. Add the missing section header + `AUTO:tools:<category>` markers,
   then run `scripts/generate_skill_references.py` (or the app-level
   `make skill-references` equivalent) to repopulate all sections, and
   sanity-check the resulting tool/section counts look right for the
   whole file, not just the category you fixed.
4. Treat this as confirmation of the Procedure B checklist for whichever
   earlier PR introduced the category — the fix strategy is the same
   checklist, applied retroactively.

## Cross-Cutting Gotchas

- **Presence ≠ parity, everywhere in this pipeline.** Every drift-check
  gate here (`--check` flags, manifest diffs, `check-skill-references`
  CI) only validates that already-rendered content matches disk. None of
  them validate that a *new* category, tool, or behavior actually got a
  section, marker, or full-depth description — that's a structural gap
  in the tooling, not a one-off bug, so don't rely on CI green to mean
  "the docs are complete."
- **`make pre-commit` regenerates manifests, but only if someone runs it.**
  Both the root Makefile (`pre-commit: format generate lint test
  check-generated worker-typecheck`) and each app's Makefile (e.g.
  `apps/network/Makefile`'s `pre-commit: format manifest server-manifest
  lint test`) do include manifest regeneration — but there's no
  `.pre-commit-config.yaml` forcing it automatically on commit. This is
  the recurring enabler behind stale manifests, both as isolated drift
  (Procedure A) and as merge conflicts (Procedure C). If a contributor's
  branch is more than a few commits behind `main` and touches any tool
  file, assume the manifest needs a manual regen check before merge —
  don't assume `make pre-commit` was ever run.
- **Never hand-edit a generated artifact**, even to "quickly fix" a
  conflict or a one-line description mismatch. Any manual edit to a
  generated manifest or a skill reference file's `AUTO:` block will be
  silently overwritten or drift again at the next regeneration — fix the
  Python source and regenerate instead.
- **A "correct behavior, wrong schema text" gap is still worth fixing.**
  Even when runtime behavior is unaffected (e.g. `value or None`
  coalescing masks a default-value mismatch), the generated schema is
  what LLM clients and downstream integrators actually read — treat
  schema/doc drift as a real defect, not cosmetic, even at low severity.
- **Out of scope: the runtime tool-index/registration-mode catalog is a
  different "manifest" from the ones this skill covers.** `docs/tool-index.md`
  and `apps/worker/worker/src/relay-object.ts` describe a discovery-time
  catalog keyed by `UNIFI_TOOL_REGISTRATION_MODE` (`eager`/`lazy`/`meta_only`)
  — it is hand-authored documentation of runtime behavior, not a generated
  artifact from `packages/unifi-mcp-shared/src/unifi_mcp_shared/manifest_generator.py`.
  A known divergence had `meta_only` mode's index initially behaving like
  `lazy` mode instead of the `meta_only` behavior documented in
  `docs/tool-index.md`. Regenerating an app's generated manifest (e.g. the
  one under `apps/protect/src/unifi_protect_mcp/`) or skill-reference docs
  does not touch this code path — treat registration-mode divergence as a
  separate bug class from the generated-artifact drift this skill addresses.
