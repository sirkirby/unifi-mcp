"""Hold the canonical incident investigation skill to its evidence contract.

The skill may reach only read-only tools, must pass explicit budgets to both
evidence tools, and its worked reports must quote the golden client views they
cite exactly: every coverage number, evidence ID and timestamp, in the exact
citation format, with every mandatory follow-up offer and retention caveat.
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
SKILL_DIR = ROOT / "plugins/unifi-intelligence/skills/incident-investigation"
SKILL = SKILL_DIR / "SKILL.md"
EXAMPLES = SKILL_DIR / "references/report-examples.md"
CASES = ROOT / "tests/fixtures/incident_evidence/cases"
VIEWS = ROOT / "tests/fixtures/incident_evidence/views"

EVIDENCE_TOOLS = {"unifi_get_incident_evidence": "network", "protect_get_incident_evidence": "protect"}
BUDGETS = {"max_window_seconds", "max_events", "max_calls", "max_elapsed_ms", "max_records_returned"}
# Read-only camera<->device lookups the skill runs itself when the client lists them directly.
MAPPING_LOOKUPS = ("protect_get_camera", "unifi_get_client_details")
LOOKUP_RULES = (
    "run them yourself, once the user has confirmed the inputs, for every requested camera ID, without asking again",
    "State each `product_inventory` mapping with the uplink field you compared and both values",
    "never reach a lookup through `*_execute`",
    "Ask the user for the mapping only when there is no proof",
    "Leave `summary` at its default, `false`",
    "write the camera MAC as six lowercase colon-separated pairs",
    "with both written in that same lowercase colon form before comparing",
    "`unifi-network-mcp` 0.38.1 and `unifi-protect-mcp` 0.9.1 and later, "
    "the servers the Network and Protect plugins pin, list them directly",
)
# A described camera needs its ID or exact-identifier proof; nothing resolves it from a description.
CAMERA_INPUT_RULE = "a name, description or location never does"
# How the skill conducts itself with the user: (section heading, rule). A real client skipped the
# confirmation, paged without asking and summarised records instead of citing them.
CONDUCT_RULES = (
    ("Workflow", "Show the inputs and budgets, then end your turn and wait for the user's reply"),
    ("Workflow", "Ask nothing further unless nothing proves a mapping"),
    ("Workflow", "Each follow-up read waits for the user's yes"),
    ("1. Confirm the inputs", "Stop here, even when the request already names every input."),
    ("1. Confirm the inputs", "Make no lookup, evidence call or other controller read until the user confirms"),
    (
        "Safety",
        'Never page with `resume_after`, split the window, raise a budget or call `detail="full"` '
        "without the user's yes to that follow-up",
    ),
    ("4. Collect evidence", "call it only after the user says yes to it"),
    ("5. Read the evidence", "make no follow-up call until the user says yes to it"),
    (
        "Report",
        "Cite one line per record you report; a summary by type or count may follow the lines, never replace them",
    ),
    ("Report", "Copy every cited value exactly as returned: times, IDs, MACs and summaries."),
    ("Report", "Never reformat or round a time"),
    (
        "Report",
        "Any other change to a cited value is a shortening: end the line with "
        "`; shortened <field> in this report from <n> characters`",
    ),
    ("Report", "the uplink field compared and both values"),
)
CONFIRMATION_FIELDS = ("Window:", "Device:", "Cameras:", "Products:", "Budgets:")
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
RETENTION = (
    "Neither controller reports how long it keeps events (retention `unknown`), so events older than its "
    "retention may have been discarded without a trace."
)
SPLIT = "split the window"
RESUME = 'resume_after="<next_cursor>"'
OBSERVATION = re.compile(
    r"^- `(?P<evidence_id>[^`]+)` (?P<when>[0-9T:.Z-]+|time `[a-z_]+`) "
    r"\((?P<product>[a-z]+), `(?P<source_tool>[^`]+)`, record `(?P<record>[^`]+)`\): "
    r"(?P<summary>.*) `(?P<event_type>[^`]*)`; mapping `(?P<mapping>[a-z_]+)`(?P<rest>.*)$"
)
SHORTHAND = re.compile(r"^[A-Za-z]{1,3}/")


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
    """Network and Protect are required; the cloud worker is optional and never needed."""
    errors = structure_errors(text)
    if not re.search(r"^Requires: network, protect$", text, re.M):
        errors.append("Requires must be exactly network, protect")
    if not re.search(r"^Optional: worker$", text, re.M):
        errors.append("Optional must be exactly worker")
    return errors


def section(text: str, heading: str) -> str:
    """The body under a ``##`` or ``###`` heading, up to the next heading of that level or higher."""
    match = re.search(rf"^(#{{2,3}}) {re.escape(heading)}\n", text, re.M)
    if not match:
        return ""
    rest = text[match.end() :]
    end = re.search(rf"^#{{2,{len(match[1])}}} ", rest, re.M)
    return rest[: end.start()] if end else rest


def conduct_errors(text: str) -> list[str]:
    """The workflow stops for confirmation, asks before every follow-up read and cites every record it reports."""
    errors = [
        f"missing conduct rule: {rule}" for heading, rule in CONDUCT_RULES if rule not in flat(section(text, heading))
    ]
    order = [
        flat(section(text, "Workflow")).find(f"**{step}.**") for step in ("Confirmation", "Mapping lookups", "Evidence")
    ]
    if -1 in order or order != sorted(order):
        errors.append("workflow order must be confirmation, then mapping lookups, then evidence")
    block = re.search(r"```text\n(.*?)```", section(text, "1. Confirm the inputs"), re.S)
    for field in CONFIRMATION_FIELDS:
        if not block or not re.search(rf"^{re.escape(field)}", block[1], re.M):
            errors.append(f"confirmation block lacks {field}")
    return errors


def remove(text: str, phrase: str) -> str:
    """Delete one occurrence of a phrase, however the skill wraps its lines."""
    return re.sub(r"\s+".join(map(re.escape, phrase.split())), "", text, count=1)


def mapping_errors(text: str) -> list[str]:
    """Step 3 maps cameras with the read-only lookups itself and asks only without proof."""
    step = re.search(r"^### 3\. Establish camera mappings\n(.*?)(?=^### )", text, re.M | re.S)
    checks = re.search(r"^### 2\. Check the evidence tools\n(.*?)(?=^### )", text, re.M | re.S)
    if not step or not checks:
        return ["missing mapping or tool-check step"]
    errors = [
        f"mapping step names {name}"
        for name in sorted(set(re.findall(rf"\b{TOOL}\b", step[1])) - set(MAPPING_LOOKUPS) - DATA_NAMES)
    ]
    for name in MAPPING_LOOKUPS:
        if not re.search(rf"`{name}\(", step[1]):
            errors.append(f"mapping step does not call {name}")
        if f"`{name}`" not in checks[1]:
            errors.append(f"tool check does not record {name}")
    errors.extend(f"missing mapping rule: {rule}" for rule in LOOKUP_RULES if rule not in flat(step[1]))
    if CAMERA_INPUT_RULE not in flat(text) or "resolved in step 3" in flat(text):
        errors.append("described cameras must need an ID or exact-identifier proof")
    if re.search(r"unifi_get_client_details\([^)]*summary=True", text):
        errors.append("mapping lookup must keep summary=false")
    return errors


def skill_section_errors(text: str) -> list[str]:
    errors = [f"missing skill section: {s}" for s in SKILL_SECTIONS if not re.search(rf"^## {s}$", text, re.M)]
    report = re.search(r"^## Report\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    for section in REPORT_SECTIONS:
        if not report or f"**{section}:**" not in report[1]:
            errors.append(f"missing report section: {section}")
    for sentence in (ALL_CLEAR, "coverage_complete: true", RETENTION, SPLIT, RESUME, "full `evidence_id`"):
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


def records_line(selection: dict) -> str:
    returned, collected, omitted = selection["returned"], selection["collected"], selection["omitted"]
    return (
        f"returned {returned['total']} of {collected['total']} collected "
        f"(in-window {returned['in_window']} of {collected['in_window']}), "
        f"max_records_returned {selection['max_records_returned']}; "
        f"resumed after {selection['resume_after'] or 'none'} ({selection['before_resume']['total']} before it); "
        f"omitted {omitted['total']} (in-window {omitted['in_window']}, too large {selection['too_large']}), "
        f"limited by {selection['limited_by'] or 'none'}, next cursor {selection['next_cursor'] or 'none'}; "
        "a presentation limit, not a coverage gap."
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
        f"truncation `{coverage['truncation']}`, retention `{coverage['retention_coverage']}`; "
        f"received {counts['received']}, accepted {counts['accepted']}, "
        f"in-window {counts['in_window']}, out-of-window {counts['out_of_window']}, untimed {counts['untimed']}, "
        f"malformed {counts['malformed_dropped']}, duplicates {counts['duplicates_dropped']}, "
        f"conflicting {counts['conflicting']}, boundary-uncertain {counts['boundary_uncertain']}."
    )


def observation_errors(line: str, record: dict) -> list[str]:
    """An observation line must be the view record's citation, field by field."""
    match = OBSERVATION.match(line)
    if not match:
        return [f"citation is not in the required format: {record['evidence_id']}"]
    time = record["time"]
    expected = {
        "evidence_id": record["evidence_id"],
        "when": time["utc"] or f"time `{time['status']}`",
        "product": record["product"],
        "source_tool": record["source_tool"],
        "record": str(record["source_record_id"]),
        "summary": "(no summary)" if record["summary"] is None else record["summary"],
        "event_type": record["event_type"],
        "mapping": record["mapping"]["status"],
    }
    wrong = sorted(field for field, value in expected.items() if match[field] != value)
    wrong += [
        f"truncated {field}"
        for field, length in record["truncated"].items()
        if f"; truncated {field} from {length} characters" not in match["rest"]
    ]
    if not wrong:
        return []
    if set(wrong) <= {"event_type", "mapping"}:
        return [f"citation does not match event type or mapping: {record['evidence_id']}"]
    return [f"citation does not match {', '.join(wrong)}: {record['evidence_id']}"]


def shorthand_errors(body: str, records: dict[str, dict]) -> list[str]:
    """Records are cited by their full evidence ID; never a bare record ID or a product prefix."""
    errors = []
    record_ids = {str(record["source_record_id"]) for record in records.values()}
    for match in re.finditer(r"`([^`\n]+)`", body):
        token = match[1]
        if token.startswith("resume_after="):
            continue
        quoted_as_record = body[max(0, match.start() - 7) : match.start()] == "record "
        if SHORTHAND.match(token) or (token in record_ids and not quoted_as_record):
            errors.append(f"citation shorthand instead of a full evidence ID: {token}")
        elif "|" in token and token not in records:
            errors.append(f"cited evidence not in the view: {token}")
    return errors


def examples(text: str) -> dict[str, str]:
    return {m[1]: m[2] for m in re.finditer(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S)}


def example_case(body: str) -> str | None:
    match = re.search(r"^Golden view: `([a-z0-9_]+)`, max_records_returned [0-9]+$", body, re.M)
    return match[1] if match else None


def example_view(body: str) -> dict | None:
    """The golden client view an example is written from, or None if it names none."""
    match = re.search(r"^Golden view: `([a-z0-9_]+)`, max_records_returned ([0-9]+)$", body, re.M)
    path = VIEWS / f"{match[1]}.json" if match else None
    if path is None or not path.exists():
        return None
    views = {
        item["max_records_returned"]: item["expected"]
        for item in json.loads(path.read_text())["views"]
        if item["resume_after"] is None
    }
    return views.get(int(match[2]))


def report_sections(body: str) -> dict[str, str]:
    labels = "|".join(map(re.escape, REPORT_SECTIONS))
    return {
        m[1]: m[2] for m in re.finditer(rf"^\*\*({labels}):\*\*(.*?)(?=^\*\*(?:{labels}):\*\*|\Z)", body, re.M | re.S)
    }


def example_errors(body: str) -> list[str]:
    """A worked report must quote its golden view exactly and claim no more than it supports."""
    case = example_case(body)
    if case is None:
        return ["missing golden view"]
    view = example_view(body)
    if view is None:
        return [f"unknown golden view: {case}"]
    sections = report_sections(body)
    errors = [f"missing report section: {s}" for s in REPORT_SECTIONS if s not in sections]
    window = view["requested_window"]
    inputs = flat(sections.get("Incident and Inputs", ""))
    if f"UTC `{utc(window['start'])}` to `{utc(window['end'])}`" not in inputs:
        errors.append("inputs do not state the requested window in UTC")
    limits = view["budgets"]["limits"]
    if (
        f"Budget limits: window {limits['window_seconds']} s, events {limits['events']}, "
        f"calls {limits['calls']}, elapsed {limits['elapsed_ms']} ms." not in inputs
    ):
        errors.append("inputs do not state the budget limits")
    selection = view["record_selection"]
    if f"`max_records_returned={selection['max_records_returned']}`" not in inputs:
        errors.append("inputs do not state max_records_returned")

    coverage = sections.get("Coverage and Limitations", "")
    lines = coverage.splitlines()
    if f"Golden evidence set: {document_line(view)}" not in lines:
        errors.append("document line does not match overall, coverage_complete or budgets")
    if f"Golden evidence set records: {records_line(selection)}" not in lines:
        errors.append("records line does not match the view's record selection")
    expected_sources = {source["source_id"]: source_line(source) for source in view["sources"]}
    for source_id, line in expected_sources.items():
        if line not in lines:
            errors.append(f"source line does not match the fixture: {source_id}")
    for source_id in re.findall(r"^- `([a-z0-9_.]+)` \(", coverage, re.M):
        if source_id not in expected_sources:
            errors.append(f"source not in the fixture: {source_id}")

    records = {record["evidence_id"]: record for record in view["records"]}
    cited = []
    for line in sections.get("Observations", "").splitlines():
        match = re.match(r"- `([^`]*\|[^`]*)`", line)
        if not match:
            continue
        record = records.get(match[1])
        if record is None:
            errors.append(f"cited evidence not in the fixture: {match[1]}")
            continue
        cited.append(match[1])
        errors.extend(observation_errors(line, record))
    if cited != [evidence_id for evidence_id in records if evidence_id in cited]:
        errors.append("observations are not in the view's order")
    errors.extend(f"view record not cited: {evidence_id}" for evidence_id in records if evidence_id not in cited)
    errors.extend(shorthand_errors(body, records))

    text = flat(body)
    all_clear = view["overall"] == "empty" and view["coverage_complete"]
    if (ALL_CLEAR in text) != all_clear:
        errors.append("all-clear sentence does not match the evidence")
    if (COMPLETE in text) != view["coverage_complete"]:
        errors.append("complete-coverage sentence does not match the evidence")
    if any(source["outcome"] == "empty" for source in view["sources"]) and RETENTION not in text:
        errors.append("an empty source needs the retention sentence")
    needs_split = any("truncation_unknown" in source["partial_reasons"] for source in view["sources"])
    next_reads = flat(sections.get("Unanswered Questions and Next Reads", ""))
    if needs_split and SPLIT not in next_reads.lower():
        errors.append("truncation_unknown needs the split the window follow-up")
    cursor = selection["next_cursor"]
    if cursor is not None and f'resume_after="{cursor}"' not in next_reads:
        errors.append("omitted records need the follow-up that resumes after next_cursor")
    if "correlation" not in sections.get("Hypotheses", "").lower():
        errors.append("hypotheses are not labelled as correlation")
    return errors


def scenario(evidence: dict) -> set[str]:
    """The evidence shapes a golden view demonstrates."""
    found = {evidence["overall"]}
    if evidence["record_selection"]["omitted"]["total"]:
        found.add("omitted records")
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
        view = example_view(body)
        assert view, "every example names its golden view"
        covered |= scenario(view)
    required = {
        "complete",
        "empty",
        "partial source",
        "protect unavailable",
        "ambiguous mapping",
        "bad timestamp",
        "omitted records",
    }
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


def test_skill_maps_cameras_with_the_lookups_itself() -> None:
    assert not mapping_errors(SKILL.read_text()), mapping_errors(SKILL.read_text())


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (
            "run them\nyourself, once the user has confirmed the inputs, for every requested camera ID,"
            "\nwithout asking again",
            "run them yourself before asking anything",
            "missing mapping rule",
        ),
        (
            "State each `product_inventory` mapping with the uplink field you compared and\nboth values",
            "State each mapping as proven",
            "missing mapping rule",
        ),
        (
            "Ask the user for the mapping only when there is no proof",
            "Ask the user for the mapping",
            "missing mapping rule",
        ),
        ('`unifi_get_client_details(mac_address="<camera mac>")`', "the client record", "does not call"),
        (
            "Read the camera's `mac` with",
            "Read the camera's `mac` with `protect_list_cameras` or",
            "names protect_list_cameras",
        ),
        ("a name, description or\n  location never does", "a name is enough", "described cameras"),
        (
            '`unifi_get_client_details(mac_address="<camera mac>")`',
            '`unifi_get_client_details(mac_address="<camera mac>", summary=True)`',
            "summary=false",
        ),
        ("Leave `summary` at its default,\n  `false`", "Pass `summary`", "missing mapping rule"),
        (
            "write the camera MAC as\n  six lowercase colon-separated pairs",
            "pass the camera MAC as Protect returns it",
            "missing mapping rule",
        ),
        (
            "with both written in that same\n  lowercase colon form before comparing",
            "as returned",
            "missing mapping rule",
        ),
    ],
)
def test_mapping_step_mutations_are_rejected(old: str, new: str, expected: str) -> None:
    text = SKILL.read_text()
    assert old in text
    assert any(expected in error for error in mapping_errors(text.replace(old, new, 1)))


def test_skill_stops_for_confirmation_and_asks_before_follow_ups() -> None:
    assert not conduct_errors(SKILL.read_text()), conduct_errors(SKILL.read_text())


@pytest.mark.parametrize("rule", [rule for _, rule in CONDUCT_RULES], ids=lambda rule: rule[:40])
def test_dropping_a_conduct_rule_is_rejected(rule: str) -> None:
    text = remove(SKILL.read_text(), rule)
    assert text != SKILL.read_text()
    assert f"missing conduct rule: {rule}" in conduct_errors(text)


@pytest.mark.parametrize("field", CONFIRMATION_FIELDS)
def test_confirmation_block_field_is_required(field: str) -> None:
    text = SKILL.read_text().replace(f"\n{field} ", "\nRemoved ", 1)
    assert f"confirmation block lacks {field}" in conduct_errors(text)


def test_evidence_before_confirmation_is_rejected() -> None:
    text = (
        SKILL.read_text()
        .replace("**Confirmation.**", "**Confirm.**", 1)
        .replace("**Report** (step 6).", "**Report** (step 6).\n5. **Confirmation.** Confirm afterwards.", 1)
    )
    assert "workflow order must be confirmation, then mapping lookups, then evidence" in conduct_errors(text)


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
        ("Requires: network, protect", "Requires: network, worker", "Requires must be"),
        ("Requires: network, protect", "Requires: network", "Requires must be"),
        ("Optional: worker", "Optional: none", "Optional must be"),
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
        (
            "network_protect_real_shapes",
            "retention `unknown`; received 3",
            "retention `covered`; received 3",
            "source line",
        ),
        ("budget_exhaustion", "exhausted: calls, window.", "exhausted: calls.", "document line"),
        ("budget_exhaustion", "outcome `not_attempted`", "outcome `empty`", "source line"),
        ("healthy_empty", "overall `empty`", "overall `complete`", "document line"),
        ("network_protect_real_shapes", "omitted 3 (in-window 3", "omitted 0 (in-window 3", "records line"),
        ("network_protect_real_shapes", "|evt-net-0001` 2026", "|evt-net-0009` 2026", "not in the fixture"),
        ("network_protect_real_shapes", "12:10:05.250000Z (network", "12:11:05.250000Z (network", "citation"),
        (
            "network_protect_real_shapes",
            "(network, `unifi_list_events`, record `evt-net-0001`)",
            "(N, `evt-net-0001`)",
            "format",
        ),
        ("network_protect_real_shapes", "aa:bb:cc:00:20:01 has connected", "phone joined", "summary"),
        ("network_protect_real_shapes", "(`protect.events|str|evt-protect-0001`)", "(`evt-protect-0001`)", "shorthand"),
        ("network_protect_real_shapes", "(`network.events|str|evt-net-0001`)", "(`N/evt-net-0001`)", "shorthand"),
        ("mapping_outcomes", "mapping `ambiguous`", "mapping `verified`", "event type or mapping"),
        ("mapping_outcomes", "- `network.events|str|evt-net-1103`", "- `network.events|str|evt-net-1103`x", "format"),
        ("malformed_timestamps", "time `ambiguous_timezone`", "2026-08-08T12:20:00.000000Z", "citation"),
        (
            "malformed_timestamps",
            "(no summary) `CLIENT_CONNECTED_WIRELESS_2`; mapping `not_evaluated`.\n",
            "\n",
            "format",
        ),
        ("timeouts", "Coverage is partial.", "No events were recorded in the window by any source.", "all-clear"),
        ("timeouts", "Coverage is partial.", "Every source read the full window.", "complete-coverage"),
        ("timeouts", "Offer to split the window", "Offer to read", "split the window"),
        ("budget_exhaustion", "Offer to split the window", "Offer to read", "split the window"),
        (
            "network_protect_real_shapes",
            'resume_after="0|2026-08-08T12:10:07.500000Z|',
            'resume_after="0|2026-08-08T12:10:07.400000Z|',
            "resumes after next_cursor",
        ),
        ("healthy_empty", "No events were recorded in the window by any\nsource.", "", "all-clear"),
        ("healthy_empty", "Neither controller reports how long", "Nothing says how long", "retention sentence"),
        ("timeouts", "correlation", "link", "correlation"),
        ("healthy_empty", "UTC `2026-08-08T12:00:00Z`", "UTC `2026-08-08T11:00:00Z`", "requested window"),
        ("budget_exhaustion", "window 1800 s, events 500", "window 7200 s, events 500", "budget limits"),
        ("budget_exhaustion", "`max_records_returned=25`", "`max_records_returned=50`", "max_records_returned"),
        ("timeouts", "**Identity:**", "**Identities:**", "missing report section: Identity"),
        ("healthy_empty", "Golden view: `healthy_empty`", "Golden view: `no_such_case`", "unknown golden view"),
    ],
)
def test_example_mismatch_is_rejected(case: str, old: str, new: str, expected: str) -> None:
    body = _example(case)
    assert old in body, old
    broken = body.replace(old, new)
    assert any(expected in error for error in example_errors(broken)), example_errors(broken)


def test_uncited_view_record_is_rejected() -> None:
    body = _example("mapping_outcomes")
    line = next(line for line in body.splitlines() if line.startswith("- `protect.events|str|evt-protect-1102`"))
    errors = example_errors(body.replace(line + "\n", ""))
    assert any("view record not cited: protect.events|str|evt-protect-1102" in error for error in errors), errors


def test_observations_out_of_view_order_are_rejected() -> None:
    body = _example("mapping_outcomes")
    lines = body.splitlines(keepends=True)
    first = next(i for i, line in enumerate(lines) if line.startswith("- `network.events|str|evt-net-1101`"))
    lines[first], lines[first + 1] = lines[first + 1], lines[first]
    assert any("view's order" in error for error in example_errors("".join(lines)))


def test_example_source_absent_from_fixture_is_rejected() -> None:
    invented = "- `access.events` (access, `access_list_events`): outcome `empty`.\n"
    body = _example("healthy_empty").replace("- `network.events` (", invented + "- `network.events` (", 1)
    assert any("source not in the fixture: access.events" in error for error in example_errors(body))


def test_missing_scenario_is_rejected() -> None:
    view = json.loads((VIEWS / "healthy_empty.json").read_text())["views"][0]["expected"]
    assert "ambiguous mapping" not in scenario(view) and "omitted records" not in scenario(view)


def test_a_cut_field_must_be_marked_in_its_citation() -> None:
    view = json.loads((VIEWS / "network_protect_real_shapes.json").read_text())["views"][0]["expected"]
    record = {**view["records"][0], "truncated": {"summary": 90_000}}
    line = (
        f"- `{record['evidence_id']}` {record['time']['utc']} ({record['product']}, `{record['source_tool']}`, "
        f"record `{record['source_record_id']}`): {record['summary']} `{record['event_type']}`; "
        f"mapping `{record['mapping']['status']}`"
    )
    assert any("truncated summary" in error for error in observation_errors(line + ".", record))
    assert observation_errors(line + "; truncated summary from 90000 characters.", record) == []
