---
name: firewall-auditor
description: Audit UniFi firewall policies for conflicts, redundancies, security gaps, and best practices. Use when asked to review firewall rules, check for security issues, audit network policies, or optimize firewall configuration.
---

# Firewall Policy Auditor

You audit the firewall configuration on a UniFi network. Your job is to dispatch the right MCP tool calls, evaluate the results against a documented rubric, score the audit deterministically, and present prioritised findings.

The work is split between you and one tiny CLI:

- **You** gather data via the `unifi-network` MCP tools, evaluate each benchmark, and write findings.
- **`scripts/unifi-firewall-score`** turns those findings into the canonical score. This is the only deterministic boundary — running it on the same findings always produces the same score, which is what makes audit history meaningful.

There is no Python script doing the audit for you. There is no HTTP sidecar. You drive the audit; the CLI does the math.

---

## Required MCP Server

This skill requires the `unifi-network` MCP server. If `unifi_tool_index` is unavailable, stop and direct the user to `/setup`.

---

## Procedure

### 1. Gather data in parallel

Dispatch these tool calls in **a single batch** (multiple tool uses in one assistant turn — they are independent and you should not serialise them):

- `unifi_list_firewall_policies`
- `unifi_list_firewall_zones`
- `unifi_list_networks`
- `unifi_list_firewall_groups`
- `unifi_list_devices`
- `unifi_get_dpi_stats` *(optional but useful for HYG-05 / EGR-03 context)*

If a tool returns `success=false`, stop the audit and surface the error. Do not partial-report.

For richer per-policy detail (needed by HYG-02 conflict detection and HYG-05 shadowing), follow up with `unifi_get_firewall_policy_details` for each policy returned by `unifi_list_firewall_policies`. Batch these calls in parallel as well.

### 2. Evaluate the 16 benchmarks

Walk through each benchmark in `references/security-benchmarks.md` in order: **SEG-01 → SEG-04, EGR-01 → EGR-03, HYG-01 → HYG-05, TOP-01 → TOP-04**. For each benchmark, the reference document specifies:

- The exact condition to verify
- Which tool output to read
- The default severity (`critical`, `warning`, or `info`)
- A `fix` template you can include in the finding

A benchmark may produce **zero, one, or many findings** — one per offending instance. For example, TOP-02 (firmware updates) produces one finding per device with `upgradeable=true`, not one finding total. Per-instance counting is what makes the score reflect real exposure (rubric §"Why per-instance deductions").

For each instance, build a finding object:

```json
{
  "benchmark_id": "SEG-01",
  "severity": "critical",
  "message": "No rule blocks IoT VLAN traffic to private networks.",
  "fix": {
    "tool": "unifi_create_firewall_policy",
    "params": { "name": "Block IoT to Internal", "action": "REJECT", ... }
  }
}
```

The `fix` block is optional but include it whenever the benchmark reference shows a remediation template.

### 3. Score the findings

Pipe the findings through the scoring CLI. This is the **only** part of the audit where math happens — keep it that way so trend tracking stays comparable.

```bash
echo '{"findings": [...]}' | "${CLAUDE_PLUGIN_ROOT}/skills/firewall-auditor/scripts/unifi-firewall-score"
```

The CLI returns:

```json
{
  "rubric_version": 1,
  "overall_score": 73,
  "overall_status": "needs_attention",
  "categories": {
    "segmentation":   {"score": 14, "max": 25, "deduction": 11, "count": 4},
    "egress_control": {"score": 23, "max": 25, "deduction":  2, "count": 1},
    "rule_hygiene":   {"score": 15, "max": 25, "deduction": 10, "count": 5},
    "topology":       {"score": 21, "max": 25, "deduction":  4, "count": 2}
  }
}
```

Do not compute the score yourself. The CLI is stable across versions; your arithmetic is not.

### 4. Append to history

Maintain a single audit history file at `${UNIFI_SKILLS_STATE_DIR:-$HOME/.claude/unifi-skills}/audit-history.json`. The file is a JSON array of `{timestamp, overall_score, overall_status, rubric_version}` entries.

```bash
STATE_DIR="${UNIFI_SKILLS_STATE_DIR:-$HOME/.claude/unifi-skills}"
mkdir -p "$STATE_DIR"
HIST="$STATE_DIR/audit-history.json"
[ -f "$HIST" ] || echo "[]" > "$HIST"

# Compose the new entry from the score CLI output ($SCORE_JSON) and append.
ENTRY=$(echo "$SCORE_JSON" | python3 -c "
import json, sys, datetime
s = json.load(sys.stdin)
print(json.dumps({
    'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'overall_score': s['overall_score'],
    'overall_status': s['overall_status'],
    'rubric_version': s['rubric_version'],
}))
")
python3 -c "
import json, sys
hist = json.load(open('$HIST'))
hist.append(json.loads('''$ENTRY'''))
json.dump(hist[-50:], open('$HIST', 'w'), indent=2)
"
```

Keep the last 50 entries (enough for ~a year of weekly audits).

### 5. Compute the trend

Compare against the previous entry in the history file. Report:

- `previous_score` — the prior entry's score, or `null` if this is the first audit
- `change` — signed integer delta (e.g., `+5`, `-3`)

If `rubric_version` differs from the prior entry, **do not** compute a trend — the scoring model changed and historical scores are not comparable. Tell the user the rubric was updated and a fresh trend baseline starts now.

### 6. Present the report

Format depends on user intent:

**Default (interactive):** human-readable summary
- Overall score and status (with the trend)
- Per-category scores
- Critical findings called out first, then warnings, then info
- Top 3–5 prioritised recommendations with the `fix` tool name

**On request ("give me JSON" / "machine-readable"):** emit the full report as JSON with this shape:

```json
{
  "timestamp": "...",
  "overall_score": 73,
  "overall_status": "needs_attention",
  "categories": { ... from CLI ... },
  "findings": [ ... all per-instance findings ... ],
  "trend": { "previous_score": 68, "change": "+5" }
}
```

---

## Score thresholds (from `references/scoring-rubric.md`)

| Score | Rating | Meaning |
|-------|--------|---------|
| 80–100 | Healthy | Follows best practices with minor gaps |
| 60–79 | Needs Attention | Notable gaps; address on a planned schedule |
| 0–59 | Critical | Significant exposure requiring immediate remediation |

---

## Acting on findings

For each finding, do **not** call mutating tools yourself. The auditor reads; the **firewall-manager** skill writes. For each remediation:

1. Explain in plain language what the finding means and why it matters.
2. Show the `fix.tool` and `fix.params` from the report.
3. Tell the user: "To apply this fix, switch to the firewall-manager skill, which will preview the change and wait for your confirmation before modifying the controller."

**Priority order:** critical findings (SEG-01 / SEG-02 / SEG-03 / HYG-02 / TOP-01) first, then warnings, then info. Use this same order when summarising the report — never bury a critical finding under a long info list.

---

## Tips

- **Parallel by default.** All Step 1 reads are independent — issue them in one batch. Per-policy details in Step 2 are also parallelisable.
- **Consult the benchmark reference whenever a check is unclear.** `references/security-benchmarks.md` is authoritative; do not invent new checks. If you encounter a real-world issue not covered by the 16 benchmarks, report it as a freeform observation outside the scored categories — do not invent a new `benchmark_id`.
- **Don't compute the score in your head.** Even simple sums drift run-to-run. Always pipe through `unifi-firewall-score`.
- **Per-instance counting matters.** Five offline devices is five TOP-01 findings, not one.
- **Severity comes from the benchmark, not the situation.** The reference defines the default severity for each benchmark. Don't downgrade a critical finding because the user "isn't worried about it" — record it accurately and let them decide what to act on.
- **Skip the trend on rubric changes.** A `rubric_version` mismatch with the prior history entry means the math changed; report the new baseline and explain why no trend is shown.
