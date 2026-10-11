"""Validate shipped workflows against product manifests and relay registration.

Call examples use Python-style keyword arguments or batch operation dictionaries.
Payload fields are distinct from top-level tool parameters. Prose parameter names
use an explicit ``tool`` with ``parameter=value`` phrase.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = r"(?:unifi|protect|access)_[a-z][a-z0-9_]+"
# These are event/response field names and contract values, not tools (including in generated prose).
DATA_NAMES = {"access_denied", "access_granted", "access_end", "access_denial", "protect_camera_id"}
SERVERS = {"network", "protect", "access", "relay"}


def catalog() -> dict[str, tuple[str, dict]]:
    result = {}
    for product in ("network", "protect", "access"):
        path = next((ROOT / "apps" / product / "src").glob("*/tools_manifest.json"))
        for tool in json.loads(path.read_text())["tools"]:
            result[tool["name"]] = (product, tool["schema"]["input"])
    # Read the literal registration schema without importing controller code.
    path = ROOT / "packages/unifi-mcp-relay/src/unifi_mcp_relay/location_timeline.py"
    tree = ast.parse(path.read_text())
    schema = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "TOOL_INPUT_SCHEMA"
    )
    name = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "TOOL_NAME" for target in node.targets)
    )
    result[name] = ("relay", schema)
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
    assert not reference_errors(text, catalog())


@pytest.mark.parametrize("heading", ["Requirements", "Prerequisites", "Required MCP Server"])
def test_legacy_requirement_section_is_rejected(heading: str) -> None:
    text = skills()[0].read_text() + f"\n## {heading}\n\n- Network only; relay is optional.\n"
    assert f"legacy dependency section: {heading}" in structure_errors(text)
