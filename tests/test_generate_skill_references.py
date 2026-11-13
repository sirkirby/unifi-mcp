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


@pytest.fixture
def cloud_repo(repo: Path) -> Path:
    product = "sitemanager"
    servers = {"unifi-sitemanager": {"args": ["unifi-sitemanager-mcp==0.1.0"]}}
    _write(
        repo,
        "plugins/unifi-sitemanager/.claude-plugin/plugin.json",
        json.dumps({"version": "1.0.0", "mcpServers": servers}),
    )
    _write(repo, "plugins/unifi-sitemanager/.mcp.codex.json", json.dumps({"mcpServers": servers}))
    manifest_path = sys.modules["plugin_tool_refs"].manifest_path(product)
    _write(repo, manifest_path, (ROOT / manifest_path).read_text())
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "cloud release")
    git(repo, "tag", "sitemanager/v0.1.0")
    return repo


CLOUD_CATEGORIES = ("hosts", "sites", "devices", "isp_metrics", "sdwan")


def cloud_reference(repo: Path, categories=CLOUD_CATEGORIES) -> Path:
    path = generator.reference_path(repo, "sitemanager")
    _write(
        repo,
        str(path.relative_to(repo)),
        "# Site Manager Server Tool Reference (14 tools)\n\n" + "".join(map(_section, categories)),
    )
    return path


@pytest.mark.parametrize(
    "skill_text", ["It provides 99 read-only domain tools, plus 99 meta-tools.", "It provides 14 tools."]
)
def test_sitemanager_reference_uses_multiword_title_and_domain_count(cloud_repo: Path, skill_text: str) -> None:
    path = cloud_reference(cloud_repo)
    skill = generator.skill_dir(cloud_repo, "sitemanager") / "SKILL.md"
    skill.write_text(skill_text + "\n")
    assert generator.run(cloud_repo, check_mode=True) == 1
    assert path.read_text().startswith("# Site Manager Server Tool Reference (14 tools)")
    assert generator.run(cloud_repo, check_mode=False) == 0
    text = path.read_text()
    assert text.startswith("# Site Manager Server Tool Reference (9 read-only domain tools, plus 5 meta-tools)\n")
    assert skill.read_text() == "It provides 9 read-only domain tools, plus 5 meta-tools.\n"
    manifest = json.loads((ROOT / sys.modules["plugin_tool_refs"].manifest_path("sitemanager")).read_text())
    expected_names = set(manifest["module_map"])
    assert len(expected_names) == 9
    assert set(generator.group_by_category(manifest, "unifi_sitemanager_mcp.tools.")) == set(CLOUD_CATEGORIES)
    rows = [line.split("`")[1] for line in text.splitlines() if line.startswith("| `")]
    assert len(rows) == 9
    assert set(rows) == expected_names
    assert generator.run(cloud_repo, check_mode=True) == 0
    before = path.read_bytes(), skill.read_bytes()
    assert generator.run(cloud_repo, check_mode=False) == 0
    assert (path.read_bytes(), skill.read_bytes()) == before


@pytest.mark.parametrize("missing", CLOUD_CATEGORIES)
def test_sitemanager_check_requires_every_category(cloud_repo: Path, missing: str) -> None:
    cloud_reference(cloud_repo, [category for category in CLOUD_CATEGORIES if category != missing])
    assert generator.run(cloud_repo, check_mode=False) == 0
    assert generator.run(cloud_repo, check_mode=True) == 1


@pytest.mark.parametrize("product", ["network", "protect", "access"])
def test_existing_products_keep_their_generated_bytes(tmp_path: Path, monkeypatch, product: str) -> None:
    prefix = {"network": "unifi", "protect": "protect", "access": "access"}[product]
    name = f"{prefix}_list_things"
    manifest = {
        "module_map": {name: f"unifi_{product}_mcp.tools.things"},
        "tools": [{"name": name, "description": "Fixture tool."}, {"name": f"{prefix}_execute"}],
    }
    monkeypatch.setattr(generator, "pinned_manifest", lambda root, name: ("fixture", manifest))
    path = generator.reference_path(tmp_path, product)
    expected = (
        f"# {product.title()} Server Tool Reference (2 tools)\n\n"
        "<!-- AUTO:tools:things -->\n1 tools.\n\n| Tool | Type | Description |\n"
        f"|------|------|-------------|\n| `{name}` | Read | Fixture tool. |\n"
        "<!-- /AUTO:tools:things -->\n"
    )
    _write(tmp_path, str(path.relative_to(tmp_path)), expected)
    skill = generator.skill_dir(tmp_path, product) / "SKILL.md"
    skill.write_text("It provides 2 tools. A list of all 2 tools.\n")
    before = path.read_bytes(), skill.read_bytes()
    assert generator.run(tmp_path, check_mode=True) == 0
    assert generator.run(tmp_path, check_mode=False) == 0
    assert (path.read_bytes(), skill.read_bytes()) == before


@pytest.mark.parametrize("domain_count,meta_count", [(1, 5), (2, 3)])
def test_sitemanager_counts_are_derived_from_pinned_module_map(
    tmp_path: Path, monkeypatch, domain_count: int, meta_count: int
) -> None:
    names = [f"sitemanager_get_fixture_{index}" for index in range(domain_count)]
    meta_names = [
        f"sitemanager_{name}" for name in ("execute", "batch", "batch_status", "load_tools", "tool_index")[:meta_count]
    ]
    manifest = {
        "module_map": {name: "unifi_sitemanager_mcp.tools.hosts" for name in names},
        "tools": [{"name": name, "description": "Fixture tool."} for name in names + meta_names],
    }
    monkeypatch.setattr(generator, "pinned_manifest", lambda root, product: ("sitemanager/v0.2.0", manifest))
    path = cloud_reference(tmp_path, ["hosts"])
    skill = generator.skill_dir(tmp_path, "sitemanager") / "SKILL.md"
    meta_text = "\n".join(f"`{name}`" for name in meta_names)
    skill.write_text("It provides 9 read-only domain tools, plus 5 meta-tools.\n" + meta_text)
    assert generator.run(tmp_path, check_mode=False) == 0
    phrase = f"{domain_count} read-only domain tools, plus {meta_count} meta-tools"
    assert path.read_text().startswith(f"# Site Manager Server Tool Reference ({phrase})\n")
    assert skill.read_text() == f"It provides {phrase}.\n" + meta_text
    assert generator.run(tmp_path, check_mode=True) == 0
