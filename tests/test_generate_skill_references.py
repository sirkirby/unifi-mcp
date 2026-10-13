"""The skill reference check fails when a tool category has no marker section."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
for _name in ("plugin_tool_refs", "generate_skill_references"):
    if _name not in sys.modules:
        _spec = importlib.util.spec_from_file_location(_name, ROOT / "scripts" / f"{_name}.py")
        sys.modules[_name] = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(sys.modules[_name])
generator = sys.modules["generate_skill_references"]
git = sys.modules["plugin_tool_refs"].git

MANIFEST = "apps/network/src/unifi_network_mcp/tools_manifest.json"
REFERENCE = "plugins/unifi-network/skills/unifi-network/references/network-tools.md"


def _write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def _section(category: str) -> str:
    return f"<!-- AUTO:tools:{category} -->\n<!-- /AUTO:tools:{category} -->\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A plugin pinning a release whose manifest has tools in two categories."""
    git(tmp_path, "init", "-q")
    # Fixture identity and hooks are scoped to this disposable repository.
    git(tmp_path, "config", "--local", "user.name", "Fixture")
    git(tmp_path, "config", "--local", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "--local", "commit.gpgsign", "false")
    git(tmp_path, "config", "--local", "core.hooksPath", str(tmp_path / "no-hooks"))
    server = {"unifi-network": {"command": "uvx", "args": ["unifi-network-mcp==0.37.0"]}}
    _write(tmp_path, "plugins/unifi-network/.mcp.codex.json", json.dumps({"mcpServers": server}))
    _write(
        tmp_path,
        "plugins/unifi-network/.claude-plugin/plugin.json",
        json.dumps({"version": "1.0.0", "mcpServers": server}),
    )
    tools = {"unifi_list_things": "things", "unifi_get_widget": "widgets"}
    manifest = {
        "count": len(tools),
        "module_map": {name: f"unifi_network_mcp.tools.{category}" for name, category in tools.items()},
        "tools": [{"name": name, "description": f"Fixture {name}."} for name in tools],
    }
    _write(tmp_path, MANIFEST, json.dumps(manifest))
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "release")
    git(tmp_path, "tag", "network/v0.37.0")
    return tmp_path


@pytest.mark.parametrize(("sections", "expected"), [(["things"], 1), (["things", "widgets"], 0)])
def test_check_fails_when_a_category_has_no_marker_section(repo, sections, expected) -> None:
    _write(repo, REFERENCE, "# Network Server Tool Reference (2 tools)\n\n" + "".join(map(_section, sections)))
    assert (
        generator.run(repo, check_mode=False) == 0
    )  # generating fills what it can and never fails on a missing section
    assert generator.run(repo, check_mode=True) == expected


def test_a_section_the_pinned_release_has_no_tools_for_is_emptied(repo) -> None:
    stale = (
        "<!-- AUTO:tools:incident_evidence -->\n1 tools.\n\n| Tool | Type | Description |\n"
        "|------|------|-------------|\n| `unifi_get_incident_evidence` | Read | Not in the pinned release. |\n"
        "<!-- /AUTO:tools:incident_evidence -->\n"
    )
    _write(repo, REFERENCE, "# Network Server Tool Reference (2 tools)\n\n" + _section("things") + _section("widgets"))
    assert generator.run(repo, check_mode=False) == 0
    path = repo / REFERENCE
    path.write_text(path.read_text() + stale)
    # A hand-filled or once-released table for a category the pinned release lacks is drift.
    assert generator.run(repo, check_mode=True) == 1
    assert generator.run(repo, check_mode=False) == 0
    text = (repo / REFERENCE).read_text()
    assert _section("incident_evidence") in text and "unifi_get_incident_evidence" not in text
    assert generator.run(repo, check_mode=True) == 0
