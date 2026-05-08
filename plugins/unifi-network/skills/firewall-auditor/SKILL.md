---
name: firewall-auditor
description: Audit UniFi firewall policies for conflicts, redundancies, security gaps, and best practices. Use when asked to review firewall rules, check for security issues, audit network policies, or optimize firewall configuration.
---

# Firewall Policy Auditor

You are auditing the firewall configuration on a UniFi network. Your goal is to identify conflicts, redundancies, security gaps, and deviations from best practices — then score results and track improvement over time.

## Required MCP Server

This skill requires the `unifi-network` MCP server. Use `unifi_tool_index` to verify available tools before proceeding.

---

## Setup Check

Before running an audit, confirm the MCP server is reachable and configured:

1. Check that `UNIFI_NETWORK_HOST` is set in the environment. If it is not set or empty, direct the user to the `/setup` skill before continuing.
2. Call `unifi_tool_index` to verify the server responds and tools are available.
3. If the server is unreachable, report the error and suggest checking `UNIFI_MCP_HTTP_ENABLED` and `UNIFI_NETWORK_MCP_URL`.

---

## Quick Audit (preferred)

Run the audit script for a complete, scored report:

```bash
python plugins/unifi-network/skills/firewall-auditor/scripts/run-audit.py --format json
```

The script connects to the MCP server (auto-detected from `UNIFI_NETWORK_MCP_URL` or `http://localhost:3000`), gathers firewall data in parallel, evaluates all 16 benchmarks, scores results, saves history, and prints a JSON report.

**Interpreting the output:**

The JSON report has this top-level structure:

```json
{
  "success": true,
  "timestamp": "<ISO-8601>",
  "overall_score": 73,
  "overall_status": "needs_attention",
  "summary": { "total_policies": 12, "enabled": 10, "disabled": 2, "networks": 5, "devices": 8 },
  "categories": {
    "segmentation":   { "score": 14, "max": 25, "findings": [...] },
    "egress_control": { "score": 23, "max": 25, "findings": [...] },
    "rule_hygiene":   { "score": 15, "max": 25, "findings": [...] },
    "topology":       { "score": 21, "max": 25, "findings": [...] }
  },
  "critical_findings": [...],
  "recommendations": ["[SEG-01] No rule blocking IoT VLAN traffic... — use unifi_create_firewall_policy with action=REJECT and zone-based source/destination."],
  "trend": { "previous_score": 68, "change": "+5" }
}
```

Read `overall_score` and `overall_status` first, then walk through `critical_findings` before the per-category detail. Findings include a `benchmark_id`, `severity`, `message`, and — when applicable — a `fix` block with the exact MCP tool and parameters to resolve it.

For a human-readable summary instead of JSON:

```bash
python plugins/unifi-network/skills/firewall-auditor/scripts/run-audit.py --format human
```

---

## Understanding Results

### Score thresholds (from `references/scoring-rubric.md`)

| Score | Rating | Meaning |
|-------|--------|---------|
| 80–100 | Healthy | Follows best practices with minor gaps |
| 60–79 | Needs Attention | Notable gaps; address on a planned schedule |
| 0–59 | Critical | Significant exposure requiring immediate remediation |

Each of the four categories (Segmentation, Egress Control, Rule Hygiene, Topology) contributes up to 25 points. Deductions are applied per finding instance:

- critical finding: -5 points per instance
- warning: -2 points per instance
- informational: -1 point per instance

The category floor is 0 — a total segmentation failure does not obscure good hygiene scores.

### What each benchmark means (from `references/security-benchmarks.md`)

| ID | Category | What it checks | Default severity |
|----|----------|----------------|-----------------|
| SEG-01 | Segmentation | IoT VLAN blocked from private networks | critical |
| SEG-02 | Segmentation | Guest VLAN restricted to internet only | critical |
| SEG-03 | Segmentation | Management VLAN only reachable from admin sources | critical |
| SEG-04 | Segmentation | Every VLAN pair has an explicit policy | warning |
| EGR-01 | Egress Control | IoT and Guest VLANs have outbound (WAN_OUT) filtering | warning |
| EGR-02 | Egress Control | DNS forced through approved resolvers | warning |
| EGR-03 | Egress Control | Threat intelligence IP block groups defined and applied | informational |
| HYG-01 | Rule Hygiene | No disabled rules duplicating enabled ones | warning |
| HYG-02 | Rule Hygiene | No conflicting rules for identical traffic | critical |
| HYG-03 | Rule Hygiene | All rule references resolve to valid objects | warning |
| HYG-04 | Rule Hygiene | Rules have descriptive names | warning |
| HYG-05 | Rule Hygiene | No broad accept rules shadowing specific drop rules | warning |
| TOP-01 | Topology | No adopted devices offline | critical |
| TOP-02 | Topology | All devices have current firmware | warning |
| TOP-03 | Topology | Switch uplinks carry consistent VLAN configurations | warning |
| TOP-04 | Topology | No orphaned port profiles | informational |

Consult `references/security-benchmarks.md` for the full check definition, the MCP tools each benchmark uses, and the exact remediation command for each ID.

---

## Acting on Findings

Each finding in the report includes a `fix` block when an automated remedy is available:

```json
{
  "benchmark_id": "SEG-01",
  "severity": "critical",
  "message": "No rule blocking IoT VLAN traffic to private networks.",
  "fix": {
    "tool": "unifi_create_firewall_policy",
    "params": {
      "name": "Block IoT to Internal",
      "action": "REJECT",
      "source":      { "zone_id": "<iot_zone_id>",      "matching_target": "ANY" },
      "destination": { "zone_id": "<internal_zone_id>", "matching_target": "ANY" }
    }
  }
}
```

For each finding:

1. Explain what the finding means in plain language and why it matters.
2. Show the `fix.tool` and `fix.params` from the report so the user knows exactly what will change.
3. Defer actual execution to the **firewall-manager** skill. Tell the user: "To apply this fix, switch to the firewall-manager skill, which will preview the change and wait for your confirmation before modifying the controller."

Never call mutating tools directly from within this skill. The auditor reads; the firewall-manager writes.

**Priority order for acting:** address critical findings first (SEG-01, SEG-02, SEG-03, HYG-02, TOP-01), then warnings, then informational items.

---

## Tracking Trends

The script automatically records every audit result in `audit-history.json` (stored in `.claude/unifi-skills/` by default, or the path in `UNIFI_SKILLS_STATE_DIR`). Up to 50 entries are retained.

The `trend` field in each report shows the score change since the previous run:

```json
"trend": { "previous_score": 68, "change": "+5" }
```

To compare audits over time, read the history file directly:

```bash
cat .claude/unifi-skills/audit-history.json
```

Each entry contains a `timestamp` and `overall_score`. Share this with the user to show improvement (or regression) after applying fixes. A healthy cadence is one audit per week or after any firewall change.

---

## Manual Procedure (fallback)

Use this procedure when the `run-audit.py` script is unavailable or the MCP server is not accessible via HTTP.

### Step 1: Gather data (batch all together)

Call via `unifi_batch`:
- `unifi_list_firewall_policies` — all policies
- `unifi_list_firewall_zones` — zone definitions
- `unifi_list_networks` — all networks/VLANs
- `unifi_list_firewall_groups` — Firewall groups (address/port) referenced by rules
- `unifi_get_dpi_stats` — DPI data (shows what traffic is actually flowing)

### Step 2: Policy analysis

For each policy, extract and analyze:
- **Source/destination zones and networks**
- **Action** (ALLOW, REJECT, DROP)
- **Protocol/port specificity**
- **Enabled/disabled state**
- **Rule ordering** (higher priority rules shadow lower ones)

### Step 3: Check for issues

**Conflicts:**
- Two rules matching the same traffic with different actions
- A broad ALLOW that undermines a specific REJECT (or vice versa, depending on order)

**Redundancies:**
- Rules that are strict subsets of other rules with the same action
- Disabled rules that duplicate enabled rules
- Rules targeting networks or groups that no longer exist

**Security gaps:**
- Inter-VLAN traffic allowed without explicit rules (check IoT → main network, guest → private)
- No egress filtering on high-risk VLANs (IoT devices should not reach everything)
- Missing rules for common best practices:
  - IoT VLAN should not access private networks
  - Guest VLAN should only access internet (not local resources)
  - Management VLAN should be restricted

**Unused rules:**
- Rules targeting IP groups with no members
- Rules for networks that have been deleted
- Rules that have been disabled for extended periods

### Step 4: Report

Present findings in this format:

```
## Firewall Audit Report

**Total Policies:** [count] ([enabled] enabled, [disabled] disabled)
**Zones:** [list]
**Networks:** [count]

### Critical Issues
[Issues that create security vulnerabilities]

### Warnings
[Redundancies, conflicts, or best practice violations]

### Recommendations
1. [Specific, actionable recommendation with which tool to use]
2. [...]

### Policy Summary Table
| # | Name | Action | Source | Destination | Status | Notes |
|---|------|--------|--------|-------------|--------|-------|
```

---

## Tips

- **Prefer the script.** `run-audit.py --format json` is faster, deterministic, and tracks history automatically. The manual procedure is a fallback only.
- **Consult the benchmarks doc.** `references/security-benchmarks.md` has the authoritative definition for every check ID (SEG-*, EGR-*, HYG-*, TOP-*). When a finding is unclear, look up the benchmark there.
- **Use the scoring rubric to set expectations.** `references/scoring-rubric.md` explains exactly how deductions are calculated. Show users their score in context: a 73/100 is "Needs Attention", not a failing grade.
- **Track scores over time.** A single audit is a snapshot. The real value is the trend — run an audit after every batch of firewall changes to confirm the score improved.
- **Focus on actionable findings.** Do not report "everything is fine" items. Surface critical issues first, then warnings.
- **Defer writes to firewall-manager.** When recommending changes, name the specific tool and parameters (from the `fix` block), then hand off to the firewall-manager skill for execution.
