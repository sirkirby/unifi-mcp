"""Hold the canonical incident investigation skill to its evidence contract.

The skill may reach only read-only tools, must pass explicit budgets to both
evidence tools, and its worked reports must quote the golden evidence sets they
cite exactly: every coverage number, evidence ID and timestamp.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from test_plugin_skill_contracts import DATA_NAMES, TOOL, structure_errors

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "plugins/cross-product/skills/incident-investigation"
SKILL = SKILL_DIR / "SKILL.md"
EXAMPLES = SKILL_DIR / "references/report-examples.md"
CASES = ROOT / "tests/fixtures/incident_evidence/cases"

EVIDENCE_TOOLS = {"unifi_get_incident_evidence": "network", "protect_get_incident_evidence": "protect"}
BUDGETS = {"max_window_seconds", "max_events", "max_calls", "max_elapsed_ms"}
REPORT_SECTIONS = (
    "Incident and Inputs",
    "Coverage and Limitations",
    "Observations",
    "Hypotheses",
    "Identity",
    "Unanswered Questions and Next Reads",
)
SKILL_SECTIONS = ("Dependencies", "Coverage and Limitations", "Safety", "Workflow", "Report")
ALL_CLEAR = "No events were recorded in the window by any source."
COMPLETE = "Every source read the full window."


def flat(text: str) -> str:
    return " ".join(text.split())


def read_only_annotations() -> dict[str, bool]:
    result = {}
    for product in ("network", "protect", "access"):
        path = next((ROOT / "apps" / product / "src").glob("*/tools_manifest.json"))
        for tool in json.loads(path.read_text())["tools"]:
            result[tool["name"]] = tool["annotations"].get("readOnlyHint") is True
    return result


def lazy_direct_tools() -> set[str]:
    names: set[str] = set()
    for product in ("network", "protect"):
        path = next((ROOT / "apps" / product / "src").glob("*/categories.py"))
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "LAZY_DIRECT_TOOLS":
                names.update(ast.literal_eval(node.value))
    return names


def read_only_errors(text: str, annotations: dict[str, bool]) -> list[str]:
    """Every tool the text names must be annotated readOnlyHint: true."""
    errors = []
    for name in sorted(set(re.findall(rf"\b{TOOL}\b", text)) - DATA_NAMES):
        if not annotations.get(name, False):
            errors.append(f"not a read-only tool: {name}")
    return errors


def evidence_call_errors(text: str, lazy: set[str]) -> list[str]:
    """Both evidence tools are called with explicit window and budgets, and listed directly in lazy mode."""
    errors = []
    calls: dict[str, list[set[str]]] = {name: [] for name in EVIDENCE_TOOLS}
    for block in re.findall(r"```python\n(.*?)```", text, re.DOTALL):
        for node in ast.walk(ast.parse(block)):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in calls:
                calls[node.func.id].append({kw.arg for kw in node.keywords if kw.arg})
    for name, found in calls.items():
        if len(found) != 1:
            errors.append(f"{name}: expected one example call, found {len(found)}")
        for keys in found:
            for key in sorted(({"start", "end", "mappings"} | BUDGETS) - keys):
                errors.append(f"{name}: example call omits {key}")
        if name not in lazy:
            errors.append(f"{name}: not listed directly in lazy registration mode")
    return errors


def dependency_errors(text: str) -> list[str]:
    """Network and Protect are required; the relay is optional and never needed."""
    errors = structure_errors(text)
    if not re.search(r"^Requires: network, protect$", text, re.M):
        errors.append("Requires must be exactly network, protect")
    if not re.search(r"^Optional: relay$", text, re.M):
        errors.append("Optional must be exactly relay")
    return errors


def skill_section_errors(text: str) -> list[str]:
    errors = [f"missing skill section: {s}" for s in SKILL_SECTIONS if not re.search(rf"^## {s}$", text, re.M)]
    report = re.search(r"^## Report\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    for section in REPORT_SECTIONS:
        if not report or f"**{section}:**" not in report[1]:
            errors.append(f"missing report section: {section}")
    for sentence in (ALL_CLEAR, "coverage_complete: true"):
        if sentence not in flat(text):
            errors.append(f"missing coverage rule: {sentence}")
    return errors


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utc(value: str) -> str:
    return parse(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def bool_text(value: bool | None) -> str:
    return "null" if value is None else str(value).lower()


def document_line(evidence: dict) -> str:
    window = evidence["requested_window"]
    seconds = int((parse(window["end"]) - parse(window["start"])).total_seconds())
    limits, usage = evidence["budgets"]["limits"], evidence["budgets"]["usage"]
    exhausted = ", ".join(evidence["budgets"]["exhausted"]) or "none"
    return (
        f"overall `{evidence['overall']}`, coverage_complete `{bool_text(evidence['coverage_complete'])}`; "
        f"budgets window {seconds}/{limits['window_seconds']} s, events {usage['events']}/{limits['events']}, "
        f"calls {usage['calls']}/{limits['calls']}, elapsed {usage['elapsed_ms']}/{limits['elapsed_ms']} ms; "
        f"exhausted: {exhausted}."
    )


def source_line(source: dict) -> str:
    coverage, page, counts = source["coverage"], source["coverage"]["pagination"], source["coverage"]["counts"]
    queried = coverage["queried_window"]
    window = f"queried {queried['start']} to {queried['end']}" if queried else "queried none"
    filters = ", ".join(f"{key}={value}" for key, value in sorted(coverage["filters"].items())) or "none"
    failure = f"`{source['failure']['kind']}`" if source["failure"] else "none"
    return (
        f"- `{source['source_id']}` ({source['product']}, `{source['source_tool']}`): "
        f"outcome `{source['outcome']}`; reasons {', '.join(source['partial_reasons']) or 'none'}; "
        f"failure {failure}; {window} (`{coverage['window_coverage']}`); filters {filters}; "
        f"returned {page['returned']}, cap {page['cap']}, has_more `{bool_text(page['has_more'])}`, "
        f"truncation `{coverage['truncation']}`; received {counts['received']}, accepted {counts['accepted']}, "
        f"in-window {counts['in_window']}, out-of-window {counts['out_of_window']}, untimed {counts['untimed']}, "
        f"malformed {counts['malformed_dropped']}, duplicates {counts['duplicates_dropped']}, "
        f"conflicting {counts['conflicting']}, boundary-uncertain {counts['boundary_uncertain']}."
    )


def observation_prefix(record: dict) -> str:
    time, provenance = record["time"], record["provenance"]
    when = time["utc"] or f"time `{time['status']}`"
    return (
        f"- `{record['evidence_id']}` {when} ({provenance['product']}, `{provenance['source_tool']}`, "
        f"record `{provenance['source_record_id']}`):"
    )


def examples(text: str) -> dict[str, str]:
    return {m[1]: m[2] for m in re.finditer(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S)}


def example_case(body: str) -> str | None:
    match = re.search(r"^Golden case: `([a-z0-9_]+)`$", body, re.M)
    return match[1] if match else None


def report_sections(body: str) -> dict[str, str]:
    labels = "|".join(map(re.escape, REPORT_SECTIONS))
    return {
        m[1]: m[2] for m in re.finditer(rf"^\*\*({labels}):\*\*(.*?)(?=^\*\*(?:{labels}):\*\*|\Z)", body, re.M | re.S)
    }


def example_errors(body: str) -> list[str]:
    """A worked report must quote its golden evidence set exactly and claim no more than it supports."""
    case = example_case(body)
    if case is None:
        return ["missing golden case"]
    path = CASES / f"{case}.json"
    if not path.exists():
        return [f"unknown golden case: {case}"]
    evidence = json.loads(path.read_text())["expected"]
    sections = report_sections(body)
    errors = [f"missing report section: {s}" for s in REPORT_SECTIONS if s not in sections]
    window = evidence["requested_window"]
    inputs = flat(sections.get("Incident and Inputs", ""))
    if f"UTC `{utc(window['start'])}` to `{utc(window['end'])}`" not in inputs:
        errors.append("inputs do not state the requested window in UTC")
    limits = evidence["budgets"]["limits"]
    if (
        f"Budget limits: window {limits['window_seconds']} s, events {limits['events']}, "
        f"calls {limits['calls']}, elapsed {limits['elapsed_ms']} ms." not in inputs
    ):
        errors.append("inputs do not state the budget limits")

    coverage = sections.get("Coverage and Limitations", "")
    if f"Golden evidence set: {document_line(evidence)}" not in coverage.splitlines():
        errors.append("document line does not match overall, coverage_complete or budgets")
    expected_sources = {source["source_id"]: source_line(source) for source in evidence["sources"]}
    lines = coverage.splitlines()
    for source_id, line in expected_sources.items():
        if line not in lines:
            errors.append(f"source line does not match the fixture: {source_id}")
    for source_id in re.findall(r"^- `([a-z0-9_.]+)` \(", coverage, re.M):
        if source_id not in expected_sources:
            errors.append(f"source not in the fixture: {source_id}")

    records = {record["evidence_id"]: record for record in evidence["records"]}
    for line in sections.get("Observations", "").splitlines():
        match = re.match(r"- `([^`]*\|[^`]*)`", line)
        if not match:
            continue
        record = records.get(match[1])
        if record is None:
            errors.append(f"cited evidence not in the fixture: {match[1]}")
            continue
        if not line.startswith(observation_prefix(record)):
            errors.append(f"citation does not match time, product, source tool or record ID: {match[1]}")
        if f"`{record['event_type']}`; mapping `{record['mapping']['status']}`" not in line:
            errors.append(f"citation does not match event type or mapping: {match[1]}")

    text = flat(body)
    all_clear = evidence["overall"] == "empty" and evidence["coverage_complete"]
    if (ALL_CLEAR in text) != all_clear:
        errors.append("all-clear sentence does not match the evidence")
    if (COMPLETE in text) != evidence["coverage_complete"]:
        errors.append("complete-coverage sentence does not match the evidence")
    if "correlation" not in sections.get("Hypotheses", "").lower():
        errors.append("hypotheses are not labelled as correlation")
    return errors


def scenario(evidence: dict) -> set[str]:
    """The evidence shapes a golden set demonstrates."""
    found = {evidence["overall"]}
    for source in evidence["sources"]:
        if {"budget_exhausted", "truncated", "truncation_unknown"} & set(source["partial_reasons"]):
            found.add("partial source")
        if source["product"] == "protect" and source["failure"] and source["outcome"] != "partial":
            found.add("protect unavailable")
    for record in evidence["records"]:
        if record["mapping"]["status"] == "ambiguous":
            found.add("ambiguous mapping")
        if record["time"]["status"] in {"malformed", "ambiguous_timezone", "out_of_window"}:
            found.add("bad timestamp")
    return found


# --- Shipped skill --------------------------------------------------------------


def test_skill_declares_local_product_dependencies() -> None:
    assert not dependency_errors(SKILL.read_text()), dependency_errors(SKILL.read_text())


def test_skill_has_required_sections() -> None:
    assert not skill_section_errors(SKILL.read_text()), skill_section_errors(SKILL.read_text())


@pytest.mark.parametrize("path", [SKILL, EXAMPLES], ids=lambda p: p.name)
def test_skill_references_only_read_only_tools(path: Path) -> None:
    errors = read_only_errors(path.read_text(), read_only_annotations())
    assert not errors, errors


def test_evidence_calls_are_explicit_and_lazy_reachable() -> None:
    errors = evidence_call_errors(SKILL.read_text(), lazy_direct_tools())
    assert not errors, errors


def test_examples_cover_every_required_scenario() -> None:
    covered: set[str] = set()
    for body in examples(EXAMPLES.read_text()).values():
        case = example_case(body)
        assert case, "every example names its golden case"
        covered |= scenario(json.loads((CASES / f"{case}.json").read_text())["expected"])
    required = {"complete", "empty", "partial source", "protect unavailable", "ambiguous mapping", "bad timestamp"}
    assert required <= covered, required - covered


@pytest.mark.parametrize("title", sorted(examples(EXAMPLES.read_text())))
def test_example_matches_its_golden_case(title: str) -> None:
    errors = example_errors(examples(EXAMPLES.read_text())[title])
    assert not errors, errors


# --- Each check rejects a deliberately broken input -------------------------------


@pytest.mark.parametrize(
    "addition",
    [
        'protect_reboot_camera(camera_id="cam-fixture-000a")',
        "`unifi_execute`",
        "`protect_batch`",
        "`unifi_no_such_tool`",
    ],
)
def test_mutating_or_unknown_tool_is_rejected(addition: str) -> None:
    text = SKILL.read_text() + f"\n{addition}\n"
    assert any(addition.strip("`").split("(")[0] in error for error in read_only_errors(text, read_only_annotations()))


@pytest.mark.parametrize("budget", sorted(BUDGETS))
def test_missing_explicit_budget_is_rejected(budget: str) -> None:
    text = re.sub(rf"^\s*{budget}=.*\n", "", SKILL.read_text(), count=1, flags=re.M)
    assert any(f"omits {budget}" in error for error in evidence_call_errors(text, lazy_direct_tools()))


def test_evidence_tool_missing_from_lazy_mode_is_rejected() -> None:
    lazy = lazy_direct_tools() - {"protect_get_incident_evidence"}
    assert any("not listed directly" in error for error in evidence_call_errors(SKILL.read_text(), lazy))


@pytest.mark.parametrize("section", [*SKILL_SECTIONS[2:], *REPORT_SECTIONS])
def test_missing_skill_section_is_rejected(section: str) -> None:
    text = SKILL.read_text().replace(f"## {section}\n", "").replace(f"**{section}:**", "")
    assert any(section in error for error in skill_section_errors(text))


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("Requires: network, protect", "Requires: network, relay", "Requires must be"),
        ("Requires: network, protect", "Requires: network", "Requires must be"),
        ("Optional: relay", "Optional: none", "Optional must be"),
    ],
)
def test_wrong_dependency_declaration_is_rejected(old: str, new: str, expected: str) -> None:
    text = SKILL.read_text().replace(old, new)
    assert any(expected in error for error in dependency_errors(text))


def _example(case: str) -> str:
    return next(body for body in examples(EXAMPLES.read_text()).values() if example_case(body) == case)


@pytest.mark.parametrize(
    ("case", "old", "new", "expected"),
    [
        ("network_protect_real_shapes", "received 3, accepted 3", "received 4, accepted 3", "source line"),
        ("budget_exhaustion", "exhausted: calls, window.", "exhausted: calls.", "document line"),
        ("budget_exhaustion", "outcome `not_attempted`", "outcome `empty`", "source line"),
        ("healthy_empty", "overall `empty`", "overall `complete`", "document line"),
        ("network_protect_real_shapes", "|evt-net-0003`", "|evt-net-0009`", "not in the fixture"),
        ("network_protect_real_shapes", "12:45:00.000000Z (network", "12:46:00.000000Z (network", "citation"),
        ("mapping_outcomes", "mapping `ambiguous`", "mapping `verified`", "event type or mapping"),
        ("malformed_timestamps", "time `ambiguous_timezone`", "2026-08-08T12:20:00.000000Z", "citation"),
        ("timeouts", "Coverage is partial.", "No events were recorded in the window by any source.", "all-clear"),
        ("timeouts", "Coverage is partial.", "Every source read the full window.", "complete-coverage"),
        ("healthy_empty", "No events were recorded in the window by any\nsource.", "", "all-clear"),
        ("timeouts", "correlation", "link", "correlation"),
        ("healthy_empty", "UTC `2026-08-08T12:00:00Z`", "UTC `2026-08-08T11:00:00Z`", "requested window"),
        ("budget_exhaustion", "window 1800 s, events 500", "window 7200 s, events 500", "budget limits"),
        ("timeouts", "**Identity:**", "**Identities:**", "missing report section: Identity"),
        ("healthy_empty", "Golden case: `healthy_empty`", "Golden case: `no_such_case`", "unknown golden case"),
    ],
)
def test_example_mismatch_is_rejected(case: str, old: str, new: str, expected: str) -> None:
    body = _example(case)
    assert old in body, old
    broken = body.replace(old, new)
    assert any(expected in error for error in example_errors(broken)), example_errors(broken)


def test_example_source_absent_from_fixture_is_rejected() -> None:
    invented = "- `access.events` (access, `access_list_events`): outcome `empty`.\n"
    body = _example("healthy_empty").replace("- `network.events` (", invented + "- `network.events` (", 1)
    assert any("source not in the fixture: access.events" in error for error in example_errors(body))


def test_missing_scenario_is_rejected() -> None:
    evidence = json.loads((CASES / "healthy_empty.json").read_text())["expected"]
    assert "ambiguous mapping" not in scenario(evidence)
