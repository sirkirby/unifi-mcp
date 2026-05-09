# Firewall Auditor Scoring Rubric

This rubric defines the deterministic scoring model for firewall audits. All audits using this rubric produce a score between 0 and 100. The same findings always produce the same score, making results comparable across audits and over time.

---

## Score Structure

The total audit score is composed of four equal categories, each worth 25 points:

| Category | Max Points | Benchmarks |
|----------|-----------|------------|
| Segmentation | 25 | SEG-01 through SEG-04 |
| Egress Control | 25 | EGR-01 through EGR-03 |
| Rule Hygiene | 25 | HYG-01 through HYG-05 |
| Topology | 25 | TOP-01 through TOP-04 |
| **Total** | **100** | All 16 benchmarks |

---

## Deduction Values

Each finding deducts points from the category where the benchmark lives. Deductions are applied per finding instance, not per benchmark — a benchmark that fires on multiple objects (e.g., five offline devices) deducts once per instance.

| Severity | Deduction per Instance |
|----------|----------------------|
| critical | -5 points |
| warning | -2 points |
| informational | -1 point |

**Minimum per category:** 0 points. A category cannot go negative.

**Maximum total deduction:** unlimited instances can be found, but the floor of 0 per category caps the total minimum score at 0.

---

## Score Calculation

### Step 1: Collect findings

Run all benchmarks in `security-benchmarks.md`. For each benchmark, record:
- Benchmark ID
- Category
- Severity
- Number of instances found (N)

### Step 2: Calculate deductions per category

For each category, sum the deductions from all findings in that category:

```
category_deduction = sum(deduction_per_instance * N  for each finding in category)
category_score = max(0, 25 - category_deduction)
```

### Step 3: Sum category scores

```
total_score = segmentation_score + egress_score + hygiene_score + topology_score
```

### Step 4: Determine health threshold

| Score Range | Rating | Meaning |
|-------------|--------|---------|
| 80 – 100 | Healthy | Configuration follows best practices with minor gaps |
| 60 – 79 | Needs Attention | Notable gaps that should be addressed on a planned schedule |
| 0 – 59 | Critical | Significant security exposure requiring immediate remediation |

---

## Worked Example

**Findings from a sample audit:**

| Benchmark | Severity | Instances | Deduction |
|-----------|----------|-----------|-----------|
| SEG-01 | critical | 1 | -5 |
| SEG-04 | warning | 3 | -6 |
| EGR-02 | warning | 1 | -2 |
| HYG-04 | warning | 4 | -8 |
| HYG-03 | warning | 1 | -2 |
| TOP-02 | warning | 2 | -4 |

**Category scores:**

| Category | Max | Deduction | Score |
|----------|-----|-----------|-------|
| Segmentation | 25 | -11 (SEG-01: -5, SEG-04: -6) | 14 |
| Egress Control | 25 | -2 (EGR-02: -2) | 23 |
| Rule Hygiene | 25 | -10 (HYG-04: -8, HYG-03: -2) | 15 |
| Topology | 25 | -4 (TOP-02: -4) | 21 |
| **Total** | **100** | **-27** | **73** |

**Rating: Needs Attention** (score 73, range 60–79)

---

## Reporting Format

The `scripts/unifi-firewall-score` CLI emits the canonical score JSON, and the auditor skill renders a human-readable report on top of it. A typical render:

```
AUDIT SCORE: 73/100 — Needs Attention

  Segmentation:   14/25
  Egress Control: 23/25
  Rule Hygiene:   15/25
  Topology:       21/25

FINDINGS (12 total, 1 critical):
  [CRITICAL] SEG-01: IoT-to-LAN block rule missing — 1 instance
  [WARNING]  SEG-04: VLAN pair without explicit policy — 3 instances
  [WARNING]  EGR-02: DNS not forced through approved resolvers — 1 instance
  [WARNING]  HYG-03: Rule references non-existent object — 1 instance
  [WARNING]  HYG-04: Rule has missing or default name — 4 instances
  [WARNING]  TOP-02: Firmware update available — 2 instances
```

Per-instance counts in the findings list must equal the `count` field in the scoring CLI's output for that category (e.g., 4 segmentation instances = SEG-01 + 3×SEG-04). If they don't match, the report wasn't built from the same findings the CLI scored.

---

## Benchmark-to-Category Mapping

| Benchmark ID | Category | Default Severity | Max Single-Instance Deduction |
|---|---|---|---|
| SEG-01 | Segmentation | critical | 5 |
| SEG-02 | Segmentation | critical | 5 |
| SEG-03 | Segmentation | critical | 5 |
| SEG-04 | Segmentation | warning | 2 |
| EGR-01 | Egress Control | warning | 2 |
| EGR-02 | Egress Control | warning | 2 |
| EGR-03 | Egress Control | informational | 1 |
| HYG-01 | Rule Hygiene | warning | 2 |
| HYG-02 | Rule Hygiene | critical | 5 |
| HYG-03 | Rule Hygiene | warning | 2 |
| HYG-04 | Rule Hygiene | warning | 2 |
| HYG-05 | Rule Hygiene | warning | 2 |
| TOP-01 | Topology | critical | 5 |
| TOP-02 | Topology | warning | 2 |
| TOP-03 | Topology | warning | 2 |
| TOP-04 | Topology | informational | 1 |

---

## Design Notes

**Why per-instance deductions?** A network with one misconfigured VLAN pair is materially less exposed than one with eight. Per-instance scoring reflects real exposure more accurately than a flat pass/fail per benchmark.

**Why a 0-point floor per category?** A catastrophic segmentation failure should not obscure good hygiene and topology scores. Category floors preserve signal in each dimension.

**Why equal 25-point category weights?** Segmentation, egress, hygiene, and topology represent independent security properties of roughly equal operational importance. No single category should dominate the total.

**Consistency guarantee:** Given the same set of benchmark results as input, this rubric always produces the same score. There is no qualitative judgment in the calculation — only the deterministic logic above.
