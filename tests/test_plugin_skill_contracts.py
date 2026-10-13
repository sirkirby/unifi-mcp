"""Validate shipped workflows against product manifests and the worker's timeline definition.

Call examples use Python-style keyword arguments or batch operation dictionaries.
Payload fields are distinct from top-level tool parameters. Prose parameter names
use an explicit ``tool`` with ``parameter=value`` phrase.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if "plugin_tool_refs" not in sys.modules:
    sys.path.insert(0, str(ROOT / "scripts"))
    _spec = importlib.util.spec_from_file_location("plugin_tool_refs", ROOT / "scripts/plugin_tool_refs.py")
    sys.modules[_spec.name] = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(sys.modules[_spec.name])
refs = sys.modules["plugin_tool_refs"]
TOOL = r"(?:unifi|protect|access)_[a-z][a-z0-9_]+"
# These are event/response field names and contract values, not tools (including in generated prose).
DATA_NAMES = {"access_denied", "access_granted", "access_end", "access_denial", "protect_camera_id"}
SERVERS = {"network", "protect", "access", "worker"}
TIMELINE_TOOL = "apps/worker/worker/src/location-timeline-tool.json"


def catalog(*, pinned: bool = True) -> dict[str, tuple[str, dict]]:
    """Tool input schemas: the server releases plugins pin, or with ``pinned=False`` the workspace servers."""
    result = {}
    # Plugin skills call the server release their plugin pins; repository docs describe the workspace server.
    for product in ("network", "protect", "access"):
        manifest = (
            refs.pinned_manifest(ROOT, product)[1]
            if pinned
            else json.loads((ROOT / refs.manifest_path(product)).read_text(encoding="utf-8"))
        )
        for tool in manifest["tools"]:
            result[tool["name"]] = (product, tool["schema"]["input"])
    # The cloud worker serves this definition; skills reach it through a connected relay.
    timeline = json.loads((ROOT / TIMELINE_TOOL).read_text(encoding="utf-8"))
    result[timeline["name"]] = ("worker", timeline["inputSchema"])
    return result


def skills() -> list[Path]:
    return sorted(p for p in (ROOT / "plugins").glob("*/skills/*/SKILL.md") if not p.parent.name.endswith("-setup"))


def check_parameters(name: str, keys: set[str], tools: dict) -> list[str]:
    if name not in tools:
        return [f"unknown tool: {name}"]
    unknown = keys - tools[name][1].get("properties", {}).keys()
    return [f"{name}: unknown parameter {key}" for key in sorted(unknown)]


def reference_errors(text: str, tools: dict) -> list[str]:
    errors = [
        f"unknown tool: {name}" for name in sorted(set(re.findall(rf"\b{TOOL}\b", text)) - tools.keys() - DATA_NAMES)
    ]
    # Balanced call extraction supports multiline and nested dict/list payloads.
    for match in re.finditer(rf"\b({TOOL})\(", text):
        start = match.end()
        depth, quote, escaped = 1, None, False
        end = start
        for end in range(start, len(text)):
            char = text[end]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
        if depth:
            errors.append(f"unclosed call: {match[1]}")
            continue
        example = text[match.start() : end + 1].replace("…", "...")
        try:
            call = ast.parse(example, mode="eval").body
        except SyntaxError:
            errors.append(f"unparseable call: {example}")
            continue
        errors.extend(check_parameters(match[1], {kw.arg for kw in call.keywords if kw.arg}, tools))
        if match[1].endswith("_batch") and call.args:
            errors.append(f"{match[1]}: use named operations parameter")
        for node in ast.walk(call):
            if not isinstance(node, ast.Dict):
                continue
            pairs = {k.value: v for k, v in zip(node.keys, node.values, strict=True) if isinstance(k, ast.Constant)}
            tool = pairs.get("tool")
            if not isinstance(tool, ast.Constant) or not isinstance(tool.value, str):
                continue
            errors.extend(f"{tool.value}: unknown batch key {key}" for key in pairs.keys() - {"tool", "arguments"})
            arguments = pairs.get("arguments")
            if isinstance(arguments, ast.Dict):
                keys = {k.value for k in arguments.keys if isinstance(k, ast.Constant)}
                errors.extend(check_parameters(tool.value, keys, tools))
    # Inline prose examples, e.g. `protect_get_snapshot` with `include_image=true`.
    for match in re.finditer(rf"`({TOOL})` with `([a-z][a-z0-9_]*)=", text):
        errors.extend(check_parameters(match[1], {match[2]}, tools))
    return errors


def structure_errors(text: str) -> list[str]:
    errors = []
    dependencies = re.search(r"^## Dependencies\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    dependency_text = dependencies[1] if dependencies else ""
    for label in ("Requires", "Optional"):
        match = re.search(rf"^{label}: (.+)$", dependency_text, re.MULTILINE)
        if not match:
            errors.append(f"missing {label} declaration")
        elif set(match[1].split(", ")) - SERVERS - {"none"}:
            errors.append(f"invalid {label} declaration")
    for section in ("Dependencies", "Coverage and Limitations"):
        if not re.search(rf"^## {section}$", text, re.MULTILINE):
            errors.append(f"missing {section} section")
    # Keep server requirements in one place rather than competing legacy sections.
    for match in re.finditer(
        r"^#{1,6} (Requirements|Prerequisites|Required MCP Servers?)\s*$", text, re.MULTILINE | re.IGNORECASE
    ):
        errors.append(f"legacy dependency section: {match[1]}")
    return errors


# Without the worker a real client said so and then read the controllers through `*_execute` unasked.
WORKER_SKILL_RULES = (
    "stop with no tool call at all",
    "make none until the user agrees",
    "Never use `*_execute` or `*_batch`, even for a lookup",
    "Identifiers come from the user.",
    "make it only after the user says yes",
)


def worker_skill_errors(text: str) -> list[str]:
    """A skill that calls the worker's timeline requires it, says so plainly and never asks it for Access."""
    if not re.search(r"\bunifi_location_timeline\(", text):
        return []
    errors = []
    requires = re.search(r"^Requires: (.+)$", text, re.MULTILINE)
    if not requires or "worker" not in requires[1].split(", "):
        errors.append("timeline skill must require worker")
    if "This skill needs the cloud worker." not in text:
        errors.append("timeline skill must say it needs the cloud worker")
    # The worker reports Access as unsupported; Access comes from its own read.
    if any("access" in products for products in re.findall(r"\bproducts=\[([^\]]*)\]", text)):
        errors.append("timeline skill must not request Access from the timeline")
    flat = " ".join(text.split())
    errors.extend(f"missing timeline skill rule: {rule}" for rule in WORKER_SKILL_RULES if rule not in flat)
    return errors


TIMELINE_SKILLS = [p for p in skills() if re.search(r"\bunifi_location_timeline\(", p.read_text())]


@pytest.mark.parametrize("path", TIMELINE_SKILLS, ids=lambda p: p.parent.name)
def test_timeline_skills_need_the_worker_and_read_access_separately(path: Path) -> None:
    assert not worker_skill_errors(path.read_text()), worker_skill_errors(path.read_text())


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("Requires: worker", "Requires: network", "must require worker"),
        ("This skill needs the cloud worker.", "", "must say it needs the cloud worker"),
        ("device_macs=[", 'products=["network", "access"], device_macs=[', "must not request Access"),
    ],
)
def test_timeline_skill_mutations_are_rejected(old: str, new: str, expected: str) -> None:
    text = (ROOT / "plugins/unifi-intelligence/skills/security-patrol/SKILL.md").read_text()
    assert old in text
    assert any(expected in error for error in worker_skill_errors(text.replace(old, new, 1)))


@pytest.mark.parametrize("path", TIMELINE_SKILLS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("rule", WORKER_SKILL_RULES, ids=lambda rule: rule[:30])
def test_dropping_a_timeline_skill_rule_is_rejected(path: Path, rule: str) -> None:
    text = path.read_text()
    # Remove every occurrence, however the skill wraps its lines.
    mutated = re.sub(r"\s+".join(map(re.escape, rule.split())), "", text)
    assert mutated != text
    assert f"missing timeline skill rule: {rule}" in worker_skill_errors(mutated)


# In lazy mode no directly listed read-only tool lists devices, cameras or doors; a real client offered such a
# listing and, when the user accepted, reached for a non-read-only `*_load_tools`.
INTELLIGENCE_SKILLS = sorted((ROOT / "plugins/unifi-intelligence/skills").glob("*/SKILL.md"))
OFFER_RULES = (
    "Offer only reads the directly listed read-only tools can make",
    "Never offer to list devices, cameras, access points or doors, and never reach for `*_load_tools`, "
    "`*_execute` or `*_batch`.",
    "When an identifier is missing, ask the user for it: they can find it in the UniFi app, or by running the "
    "product's own list tool in eager mode.",
)
LISTING_TOOL = re.compile(
    r"\b(?:unifi|protect|access)_(?:list_(?:devices|clients|cameras|doors|users|visitors)|load_tools)\b"
)
LISTING_OFFER = re.compile(r"\b(?:offer|offers|I can|let me|show)\b[^.]{0,60}\blist\b", re.IGNORECASE)


def offer_errors(text: str) -> list[str]:
    """Offers name only reads directly listed read-only tools can make; a missing identifier is asked for."""
    flat = " ".join(text.split())
    errors = [f"missing offer rule: {rule}" for rule in OFFER_RULES if rule not in flat]
    errors.extend(f"names a listing or loader tool: {name}" for name in sorted(set(LISTING_TOOL.findall(text))))
    # The rules themselves say what never to offer; any other sentence must not offer a listing.
    for sentence in re.split(r"(?<=[.!?])\s+", flat):
        if "never" not in sentence.lower() and LISTING_OFFER.search(sentence):
            errors.append(f"offers a listing: {sentence[:80]}")
    return errors


@pytest.mark.parametrize("path", INTELLIGENCE_SKILLS, ids=lambda p: p.parent.name)
def test_skills_offer_only_reads_they_can_make(path: Path) -> None:
    assert not offer_errors(path.read_text()), offer_errors(path.read_text())


@pytest.mark.parametrize("path", INTELLIGENCE_SKILLS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize(
    ("addition", "expected"),
    [
        ("\nIf the camera ID is missing, offer to list the user's cameras.\n", "offers a listing"),
        ("\nLet me list your access points so you can choose one.\n", "offers a listing"),
        ("\nI can list the devices on this site for you.\n", "offers a listing"),
        ("\nLoad the camera tools with `protect_load_tools` first.\n", "names a listing or loader tool"),
        ('\nShow candidates from `unifi_list_devices(search="door")`.\n', "names a listing or loader tool"),
    ],
)
def test_listing_offers_are_rejected(path: Path, addition: str, expected: str) -> None:
    assert any(expected in error for error in offer_errors(path.read_text() + addition))


@pytest.mark.parametrize("path", INTELLIGENCE_SKILLS, ids=lambda p: p.parent.name)
@pytest.mark.parametrize("rule", OFFER_RULES, ids=lambda rule: rule[:30])
def test_dropping_an_offer_rule_is_rejected(path: Path, rule: str) -> None:
    text = path.read_text()
    mutated = re.sub(r"\s+".join(map(re.escape, rule.split())), "", text)
    assert mutated != text
    assert f"missing offer rule: {rule}" in offer_errors(mutated)


@pytest.mark.parametrize("path", skills(), ids=lambda p: p.parent.name)
def test_shipped_skill_contract(path: Path) -> None:
    tools = catalog()
    text = path.read_text()
    assert not structure_errors(text), structure_errors(text)
    declared = set(re.findall(r"^(?:Requires|Optional): (.+)$", text, re.MULTILINE)[0].split(", "))
    declared.update(re.findall(r"^(?:Requires|Optional): (.+)$", text, re.MULTILINE)[1].split(", "))
    for source in [path, *sorted((path.parent / "references").glob("*"))]:
        if source.suffix not in (".md", ".yaml"):
            continue
        content = source.read_text()
        assert not reference_errors(content, tools), f"{source}: {reference_errors(content, tools)}"
        used = {tools[n][0] for n in re.findall(rf"\b{TOOL}\b", content) if n in tools}
        assert used <= declared, f"{source}: undeclared servers {used - declared}"


@pytest.mark.parametrize(
    ("example", "expected"),
    [
        ("`unifi_nonexistent_tool()`", "unknown tool"),
        ('`unifi_list_devices(nonexistent_parameter="x")`', "unknown parameter"),
        (
            'unifi_batch(operations=[{"tool": "unifi_list_devices", "arguments": {"nonexistent_parameter": 1}}])',
            "unknown parameter",
        ),
        ('unifi_batch(operations=[{"tool": "unifi_list_devices", "args": {}}])', "unknown batch key"),
        ("`unifi_list_devices` with `nonexistent_parameter=true`", "unknown parameter"),
    ],
)
def test_reference_mutations_are_rejected(example: str, expected: str) -> None:
    assert any(expected in error for error in reference_errors(example, catalog()))


@pytest.mark.parametrize("section", ["Coverage and Limitations", "Dependencies"])
def test_missing_section_is_rejected(section: str) -> None:
    text = skills()[0].read_text().replace(f"## {section}\n", "")
    assert f"missing {section} section" in structure_errors(text)


def test_missing_dependency_declaration_is_rejected() -> None:
    text = re.sub(r"^Requires:.*\n", "", skills()[0].read_text(), flags=re.MULTILINE)
    assert "missing Requires declaration" in structure_errors(text)


@pytest.mark.parametrize("scenario", ["Unavailable source", "Partial coverage", "Capped query"])
def test_incomplete_report_examples_are_present(scenario: str) -> None:
    path = ROOT / "plugins/unifi-protect/skills/security-digest/SKILL.md"
    text = path.read_text().split(f"### {scenario}\n", 1)[1].split("\n### ", 1)[0]
    for section in ("Coverage and Limitations", "Observations", "Hypotheses", "Identity"):
        assert f"**{section}:**" in text
    assert not re.search(r"all.clear|complete coverage|nothing to worry about", text, re.IGNORECASE)
    if scenario == "Capped query":
        assert "50/50" in text and "20/20" in text and "completeness unknown" in text


def test_documented_timeline_signature() -> None:
    text = (ROOT / "docs/cross-product.md").read_text()
    tools = catalog(pinned=False)
    assert not reference_errors(text, tools)
    accepted = tools["unifi_location_timeline"][1]["properties"].keys()
    section = text.split("## The Location Timeline Tool\n", 1)[1].split("\n## ", 1)[0]
    parameters = section.split("Parameters:\n", 1)[1].split("\n\n", 1)[0]
    assert accepted <= set(re.findall(r"`([a-z_]+)`", parameters)), "undocumented timeline parameters"
    example = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])
    assert example.keys() <= accepted


@pytest.mark.parametrize("heading", ["Requirements", "Prerequisites", "Required MCP Server"])
def test_legacy_requirement_section_is_rejected(heading: str) -> None:
    text = skills()[0].read_text() + f"\n## {heading}\n\n- Network only; relay is optional.\n"
    assert f"legacy dependency section: {heading}" in structure_errors(text)
