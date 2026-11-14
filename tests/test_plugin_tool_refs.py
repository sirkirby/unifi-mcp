"""Credential-free Git fixtures for the plugin tool reference check."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("plugin_tool_refs", ROOT / "scripts/plugin_tool_refs.py")
assert spec and spec.loader
refs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = refs
spec.loader.exec_module(refs)
git = refs.git

MANIFEST = "apps/network/src/unifi_network_mcp/tools_manifest.json"
SKILL = "plugins/unifi-network/skills/example/SKILL.md"


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


def release_manifest(root: Path, *tools: str) -> None:
    write(root, MANIFEST, json.dumps({"tools": [{"name": name} for name in tools]}))


def pin(root: Path, version: str) -> None:
    server = {"unifi-network": {"command": "uvx", "args": [f"unifi-network-mcp=={version}"]}}
    write(root, "plugins/unifi-network/.mcp.codex.json", json.dumps({"mcpServers": server}))
    manifest = root / "plugins/unifi-network/.claude-plugin/plugin.json"
    write(root, str(manifest.relative_to(root)), json.dumps(dict(json.loads(manifest.read_text()), mcpServers=server)))


def release(root: Path, tag: str) -> None:
    git(root, "add", ".")
    git(root, "commit", "-qm", tag)
    git(root, "tag", tag)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    # Fixture identity and hooks are scoped to this disposable repository.
    git(tmp_path, "config", "--local", "user.name", "Fixture")
    git(tmp_path, "config", "--local", "user.email", "fixture@example.invalid")
    git(tmp_path, "config", "--local", "commit.gpgsign", "false")
    git(tmp_path, "config", "--local", "core.hooksPath", str(tmp_path / "no-hooks"))
    write(tmp_path, "plugins/unifi-network/.claude-plugin/plugin.json", json.dumps({"version": "1.0.0"}))
    pin(tmp_path, "0.37.0")
    release_manifest(tmp_path, "unifi_list_clients")
    release(tmp_path, "network/v0.37.0")
    return tmp_path


def test_tool_absent_from_pinned_release_fails(repo: Path) -> None:
    write(repo, SKILL, "Call `unifi_list_routes` first.\n")
    with pytest.raises(ValueError, match=r"SKILL.md:1: unifi_list_routes is not a tool in network/v0.37.0"):
        refs.check(repo)


def test_tool_passes_once_the_pinned_release_has_it(repo: Path) -> None:
    write(repo, SKILL, "Call `unifi_list_routes` first.\n")
    release_manifest(repo, "unifi_list_clients", "unifi_list_routes")
    release(repo, "network/v0.38.0")
    with pytest.raises(ValueError, match="unifi_list_routes"):
        refs.check(repo)  # Released, but the plugin still pins 0.37.0.
    pin(repo, "0.38.0")
    assert refs.check(repo) == 1


def test_unreleased_working_tree_manifest_does_not_count(repo: Path) -> None:
    write(repo, SKILL, "Call `unifi_list_routes` first.\n")
    release_manifest(repo, "unifi_list_clients", "unifi_list_routes")
    with pytest.raises(ValueError, match="unifi_list_routes"):
        refs.check(repo)


def test_missing_release_tag_says_to_fetch_tags(repo: Path) -> None:
    git(repo, "tag", "-d", "network/v0.37.0")
    write(repo, SKILL, "Use `unifi_list_clients`.\n")
    with pytest.raises(ValueError, match=r"network/v0.37.0 is missing; fetch tags"):
        refs.check(repo)


def test_release_without_manifest_is_reported(repo: Path) -> None:
    git(repo, "rm", "-q", MANIFEST)
    release(repo, "network/v0.38.0")
    pin(repo, "0.38.0")
    write(repo, SKILL, "Use `unifi_list_clients`.\n")
    with pytest.raises(ValueError, match=r"release network/v0.38.0 has no .*tools_manifest.json"):
        refs.check(repo)


def test_meta_tools_and_non_tool_identifiers_are_recognised(repo: Path) -> None:
    write(
        repo,
        SKILL,
        "`unifi_tool_index`, `unifi_execute`, `unifi_batch`, `unifi_batch_status`, `unifi_load_tools`.\n"
        "Import unifi_network_mcp; ignore `access_granted`, `access_denial` and `protect_camera_id`.\n"
        "Also x_unifi_secret and unifi_list_clients-like words.\n",
    )
    write(repo, "apps/network/src/unifi_network_mcp/__init__.py", "")
    assert refs.check(repo) == 5


WORKER_TOOLS = "apps/worker/worker/src/relay-object.ts"
TIMELINE_TS = 'const TIMELINE: ToolInfo = {\n  name: "unifi_location_timeline",\n  title: "Timeline",\n};\n'
TIMELINE_JSON = json.dumps({"name": "unifi_location_timeline", "title": "Timeline"}, indent=2)


def test_product_bundle_cannot_name_worker_tools(repo: Path) -> None:
    write(repo, WORKER_TOOLS, TIMELINE_TS)
    release(repo, "worker/v1.5.1")
    write(repo, SKILL, "Call `unifi_location_timeline`.\n")
    with pytest.raises(ValueError, match="unifi_location_timeline is not a tool in network/v0.37.0"):
        refs.check(repo)


def test_skills_only_bundle_checks_product_pins_and_released_worker(repo: Path) -> None:
    skill = "plugins/unifi-intelligence/skills/patrol/SKILL.md"
    write(repo, "plugins/unifi-intelligence/.claude-plugin/plugin.json", json.dumps({"version": "1.0.0"}))
    write(repo, skill, "Call `unifi_location_timeline`, then `unifi_list_clients`.\n")
    with pytest.raises(ValueError, match=r"not a tool in .* or no released worker \(no worker/v\* tag; fetch tags\)"):
        refs.check(repo)
    write(repo, WORKER_TOOLS, TIMELINE_TS)
    release(repo, "worker/v1.5.1")
    assert refs.check(repo) == 2


def test_worker_tool_defined_in_json_resolves(repo: Path) -> None:
    write(repo, "plugins/unifi-intelligence/.claude-plugin/plugin.json", json.dumps({"version": "1.0.0"}))
    write(repo, "plugins/unifi-intelligence/skills/patrol/SKILL.md", "Call `unifi_location_timeline`.\n")
    write(repo, "apps/worker/worker/src/location-timeline-tool.json", TIMELINE_JSON)
    with pytest.raises(ValueError, match="no released worker"):
        refs.check(repo)  # Defined in the workspace, but no worker release serves it yet.
    release(repo, "worker/v1.6.0")
    assert refs.check(repo) == 1


def test_relay_source_no_longer_provides_tools(repo: Path) -> None:
    write(repo, "plugins/unifi-intelligence/.claude-plugin/plugin.json", json.dumps({"version": "1.0.0"}))
    write(repo, "plugins/unifi-intelligence/skills/patrol/SKILL.md", "Call `unifi_location_timeline`.\n")
    write(repo, "packages/unifi-mcp-relay/src/unifi_mcp_relay/timeline.py", 'TOOL_NAME = "unifi_location_timeline"\n')
    release(repo, "relay/v0.3.18")
    with pytest.raises(ValueError, match="no released worker"):
        refs.check(repo)


def test_other_product_names_need_that_products_plugin(repo: Path) -> None:
    write(repo, SKILL, "Cross-check with `protect_list_cameras`.\n")
    with pytest.raises(ValueError, match="no unifi-protect plugin pins a protect release"):
        refs.check(repo)


@pytest.fixture
def cloud_repo(repo: Path) -> Path:
    server = {"unifi-sitemanager": {"args": ["unifi-sitemanager-mcp==0.1.0"]}}
    write(
        repo,
        "plugins/unifi-sitemanager/.claude-plugin/plugin.json",
        json.dumps({"version": "1.0.0", "mcpServers": server}),
    )
    write(repo, "plugins/unifi-sitemanager/.mcp.codex.json", json.dumps({"mcpServers": server}))
    manifest = json.loads((ROOT / refs.manifest_path("sitemanager")).read_text())
    write(repo, refs.manifest_path("sitemanager"), json.dumps(manifest))
    release(repo, "sitemanager/v0.1.0")
    return repo


def test_sitemanager_domain_and_meta_tools_resolve_from_own_pin(cloud_repo: Path) -> None:
    skill = "plugins/unifi-sitemanager/skills/example/SKILL.md"
    write(
        cloud_repo, skill, "`sitemanager_list_hosts`\n" + "\n".join(f"`sitemanager_{name}`" for name in refs.META_TOOLS)
    )
    assert refs.check(cloud_repo) == 6
    assert refs.pinned_tool_count(cloud_repo, "sitemanager") == 9


@pytest.mark.parametrize(
    "name", ["sitemanager_list_hostz", "sitemanager_get_support_bundle", "sitemanager_list_clients"]
)
def test_unknown_sitemanager_tool_is_reported(cloud_repo: Path, name: str) -> None:
    write(cloud_repo, "plugins/unifi-sitemanager/skills/example/SKILL.md", f"Call `{name}`.\n")
    with pytest.raises(ValueError, match=rf"SKILL.md:1: {name} is not a tool in sitemanager/v0.1.0"):
        refs.check(cloud_repo)


def test_sitemanager_workspace_addition_does_not_override_pin(cloud_repo: Path) -> None:
    path = refs.manifest_path("sitemanager")
    data = json.loads((cloud_repo / path).read_text())
    data["tools"].append({"name": "sitemanager_future_tool"})
    write(cloud_repo, path, json.dumps(data))
    write(cloud_repo, SKILL, "Call `sitemanager_future_tool`.\n")
    with pytest.raises(ValueError, match="sitemanager_future_tool is not a tool in sitemanager/v0.1.0"):
        refs.check(cloud_repo)


def test_sitemanager_reference_needs_its_own_plugin_pin(repo: Path) -> None:
    write(repo, SKILL, "Call `sitemanager_list_hosts`.\n")
    with pytest.raises(ValueError, match="no unifi-sitemanager plugin pins a sitemanager release"):
        refs.check(repo)


@pytest.mark.parametrize("product", ["network", "protect", "access"])
def test_existing_products_keep_manifest_total_count(monkeypatch, product: str) -> None:
    manifest = {"tools": [{"name": "domain"}, {"name": "meta"}], "module_map": {"domain": "things"}}
    monkeypatch.setattr(refs, "pinned_manifest", lambda root, name: ("fixture", manifest))
    assert refs.pinned_tool_count(ROOT, product) == 2


def test_sitemanager_product_bundle_cannot_use_worker_only_tools(cloud_repo: Path) -> None:
    write(cloud_repo, WORKER_TOOLS, 'const FIXTURE = {\n  name: "sitemanager_fixture_tool",\n};\n')
    release(cloud_repo, "worker/v1.0.0")
    write(cloud_repo, "plugins/unifi-sitemanager/skills/example/SKILL.md", "Call `sitemanager_fixture_tool`.\n")
    with pytest.raises(ValueError, match="sitemanager_fixture_tool is not a tool in sitemanager/v0.1.0"):
        refs.check(cloud_repo)
    (cloud_repo / "plugins/unifi-sitemanager/skills/example/SKILL.md").unlink()
    write(cloud_repo, "plugins/unifi-intelligence/skills/example/SKILL.md", "Call `sitemanager_fixture_tool`.\n")
    assert refs.check(cloud_repo) == 1
