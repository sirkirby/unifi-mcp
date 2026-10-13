"""Plugin tool counts and generated references follow the server release the plugin pins.

Credential-free Git fixtures: a release tag carries one tool manifest and the
workspace manifest has one more tool, as on a server PR that adds a tool. The
pinned manifest is read with ``git show <tag>:<manifest>`` from local tags.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(ROOT / "scripts"))
refs = _load("plugin_tool_refs", ROOT / "scripts/plugin_tool_refs.py")
generator = _load("generate_skill_references", ROOT / "scripts/generate_skill_references.py")
site = _load("docs_test_site_content", ROOT / "tests/docs/test_site_content.py")
git = refs.git

MANIFEST = "apps/network/src/unifi_network_mcp/tools_manifest.json"
REFERENCE = "plugins/unifi-network/skills/unifi-network/references/network-tools.md"
SKILL = "plugins/unifi-network/skills/unifi-network/SKILL.md"
RELEASED = ("unifi_list_clients", "unifi_get_client_details")
ADDED = "unifi_get_incident_evidence"


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def manifest(root: Path, *tools: str) -> None:
    write(
        root,
        MANIFEST,
        json.dumps(
            {
                "count": len(tools),
                "module_map": {name: "unifi_network_mcp.tools.clients" for name in tools},
                "tools": [
                    {"name": name, "description": f"Fixture tool {name}.", "schema": {"input": {"properties": {}}}}
                    for name in tools
                ],
            }
        ),
    )


def pin(root: Path, version: str) -> None:
    server = {"unifi-network": {"command": "uvx", "args": [f"unifi-network-mcp=={version}"]}}
    write(root, "plugins/unifi-network/.mcp.codex.json", json.dumps({"mcpServers": server}))
    write(
        root, "plugins/unifi-network/.claude-plugin/plugin.json", json.dumps({"version": "1.0.0", "mcpServers": server})
    )


def release(root: Path, tag: str) -> None:
    git(root, "add", ".")
    git(root, "commit", "-qm", tag)
    git(root, "tag", tag)


def skill_states(root: Path, count: int) -> None:
    write(root, SKILL, f"It provides {count} tools covering clients.\n")


def plugin_count_matches(root: Path) -> bool:
    """The plugin count surface check, against the release the plugin pins."""
    return site.states_count((root / SKILL).read_text(encoding="utf-8"), refs.pinned_tool_count(root, "network"))


def reference_tools(root: Path) -> str:
    return (root / REFERENCE).read_text(encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    # Fixture identity and hooks are scoped to this disposable repository.
    git(tmp_path, "config", "--local", "user.name", "Fixture")
    git(tmp_path, "config", "--local", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "--local", "commit.gpgsign", "false")
    git(tmp_path, "config", "--local", "core.hooksPath", str(tmp_path / "no-hooks"))
    pin(tmp_path, "0.37.0")
    manifest(tmp_path, *RELEASED)
    write(
        tmp_path,
        REFERENCE,
        "# Network Server Tool Reference (0 tools)\n\n## Clients\n\n"
        "<!-- AUTO:tools:clients -->\n<!-- /AUTO:tools:clients -->\n",
    )
    skill_states(tmp_path, len(RELEASED))
    release(tmp_path, "network/v0.37.0")
    generator.run(tmp_path, check_mode=False)
    git(tmp_path, "commit", "-qam", "generated references")
    # A server change adds a tool to the workspace manifest; nothing is tagged yet.
    manifest(tmp_path, *RELEASED, ADDED)
    return tmp_path


def test_a_workspace_tool_leaves_plugin_references_and_counts_on_the_pinned_release(repo: Path) -> None:
    assert generator.run(repo, check_mode=True) == 0
    assert generator.run(repo, check_mode=False) == 0
    text = reference_tools(repo)
    assert "(2 tools)" in text and ADDED not in text
    assert all(f"`{name}`" in text for name in RELEASED)
    assert plugin_count_matches(repo)


def test_plugin_text_stating_the_workspace_count_fails(repo: Path) -> None:
    skill_states(repo, len(RELEASED) + 1)
    assert not plugin_count_matches(repo)


def test_moving_the_pin_requires_the_new_count_and_references(repo: Path) -> None:
    release(repo, "network/v0.38.0")
    pin(repo, "0.38.0")
    # The plugin release moves the pin: the old references and count no longer pass.
    assert generator.run(repo, check_mode=True) == 1
    assert not plugin_count_matches(repo)

    # Generation brings the references and the skill's count to the new pin.
    assert generator.run(repo, check_mode=False) == 0
    assert generator.run(repo, check_mode=True) == 0
    assert "(3 tools)" in reference_tools(repo) and f"`{ADDED}`" in reference_tools(repo)
    assert "It provides 3 tools" in (repo / SKILL).read_text(encoding="utf-8")
    assert plugin_count_matches(repo)


def test_the_release_writeback_moves_references_and_counts_with_the_pin(repo: Path, monkeypatch) -> None:
    versions = _load("plugin_versions", ROOT / "scripts/plugin_versions.py")
    # The version guard needs marketplaces; tests/test_plugin_versions.py covers it.
    monkeypatch.setattr(versions, "check", lambda *args: None)
    release(repo, "network/v0.38.0")
    # The writeback's real server.json generator, invoked by the module as in CI.
    write(repo, "scripts/generate_server_manifest.py", (ROOT / "scripts/generate_server_manifest.py").read_text())
    versions.sync(repo)
    assert versions.plugin_state(repo / "plugins/unifi-network")[1] == {"unifi-network-mcp": "0.38.0"}
    assert generator.run(repo, check_mode=True) == 0
    assert f"`{ADDED}`" in reference_tools(repo)
    assert plugin_count_matches(repo)


def test_a_missing_pinned_tag_is_reported_not_replaced_by_the_workspace(repo: Path) -> None:
    pin(repo, "0.39.0")
    with pytest.raises(ValueError, match=r"pinned release tag network/v0\.39\.0 is missing; fetch tags"):
        generator.run(repo, check_mode=True)
