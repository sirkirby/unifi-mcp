"""Credential-free Git fixtures for plugin admission and release writebacks."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("plugin_versions", ROOT / "scripts/plugin_versions.py")
assert spec and spec.loader
versions = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = versions
spec.loader.exec_module(versions)


def write(root: Path, path: str, data: dict) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data) + "\n")


def edit(root: Path, path: str, **fields) -> None:
    data = json.loads((root / path).read_text()) if (root / path).exists() else {}
    data.update(fields)
    write(root, path, data)


def log(root: Path, *plugins: str) -> None:
    """Add a changelog entry heading naming each "plugin version"."""
    path = root / versions.CHANGELOG
    path.write_text(path.read_text() + f"\n## 2026-01-01 — {', '.join(plugins)}\n\n- Change.\n")


def manifests(root: Path, version: str) -> None:
    for manifest in versions.MANIFESTS:
        edit(root, f"plugins/unifi-network/{manifest}", version=version)


def pins(root: Path, version: str) -> None:
    for filename in (".mcp.codex.json", ".claude-plugin/plugin.json"):
        edit(
            root,
            f"plugins/unifi-network/{filename}",
            mcpServers={"unifi-network": {"command": "uvx", "args": ["--from", f"unifi-network-mcp=={version}"]}},
        )


@pytest.fixture(scope="module")
def _repo_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the base fixture repo (git init + commit + tag) once per module.

    `repo` below copies this per test instead of repeating the full git init/
    config/add/commit/tag subprocess sequence (~7 git invocations) for every
    one of the ~40 tests that use it — a copy of this tiny repo is far
    cheaper than rebuilding it, and each test still gets its own isolated
    working tree to mutate and commit into.
    """
    template = tmp_path_factory.mktemp("repo-template")
    subprocess.run(["git", "init", "-q", str(template)], check=True)
    for manifest in versions.MANIFESTS:
        write(template, f"plugins/unifi-network/{manifest}", {"name": "unifi-network", "version": "1.0.0"})
    # As shipped: the Codex manifest names its server file by path.
    edit(template, "plugins/unifi-network/.codex-plugin/plugin.json", mcpServers="./.mcp.codex.json")
    pins(template, "0.37.0")
    for marketplace in versions.MARKETPLACES:
        write(template, marketplace, {"plugins": [{"name": "unifi-network"}]})
    (template / versions.CHANGELOG).write_text(f"# Changelog\n\n{versions.CHANGELOG_MARKER}\n")
    # Fixture identity and hooks are scoped to this disposable repository.
    versions.git(template, "config", "--local", "user.name", "Fixture")
    versions.git(template, "config", "--local", "user.email", "fixture@example.invalid")
    versions.git(template, "config", "--local", "commit.gpgsign", "false")
    versions.git(template, "config", "--local", "core.hooksPath", str(template / "no-hooks"))
    versions.git(template, "add", ".")
    versions.git(template, "commit", "-qm", "fixture")
    versions.git(template, "tag", "network/v0.37.0")
    versions.git(template, "branch", "base")
    return template


@pytest.fixture
def repo(tmp_path: Path, _repo_template: Path) -> Path:
    target = tmp_path / "repo"
    shutil.copytree(_repo_template, target)
    return target


def change_skill(root: Path) -> None:
    path = root / "plugins/unifi-network/skills/example/SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Changed shipped skill\n")


def test_change_without_bump_fails_including_untracked_files(repo: Path) -> None:
    change_skill(repo)
    with pytest.raises(ValueError, match="strictly greater"):
        versions.check(repo, "base")


@pytest.mark.parametrize("value", ["0.9.9", "1.0.0", "1.0.0+new-build", "1.0.0-rc.1"])
def test_decrease_or_equal_precedence_fails(repo: Path, value: str) -> None:
    change_skill(repo)
    manifests(repo, value)
    with pytest.raises(ValueError, match="strictly greater"):
        versions.check(repo, "base")


@pytest.mark.parametrize("value", ["v1.0.1", "1.01.0", "1.0", "1.0.1-01", "", 1])
def test_invalid_semver_fails(repo: Path, value) -> None:
    manifests(repo, value)
    with pytest.raises(ValueError, match="invalid semver"):
        versions.check(repo, "base")


def test_disagreeing_manifests_fail(repo: Path) -> None:
    edit(repo, "plugins/unifi-network/.codex-plugin/plugin.json", version="1.0.1")
    with pytest.raises(ValueError, match="manifests disagree"):
        versions.check(repo, "base")


def test_mismatched_pins_fail(repo: Path) -> None:
    edit(repo, "plugins/unifi-network/.mcp.codex.json", mcpServers={"network": {"args": ["unifi-network-mcp==0.38.0"]}})
    with pytest.raises(ValueError, match="mismatched pins"):
        versions.check(repo, "base")


def test_inline_pin_mismatch_fails(repo: Path) -> None:
    edit(
        repo,
        "plugins/unifi-network/.claude-plugin/plugin.json",
        mcpServers={"network": {"args": ["unifi-network-mcp==0.38.0"]}},
    )
    with pytest.raises(ValueError, match="mismatched pins between Claude and Codex"):
        versions.check(repo, "base")


@pytest.mark.parametrize("marketplace", versions.MARKETPLACES)
def test_marketplace_version_fails(repo: Path, marketplace: str) -> None:
    edit(repo, marketplace, plugins=[{"name": "unifi-network", "version": "1.0.0"}])
    with pytest.raises(ValueError, match="marketplace entry.*carries version"):
        versions.check(repo, "base")


def test_missing_base_fails_even_without_plugin_changes(repo: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/plugin_versions.py"),
            "check",
            "--root",
            str(repo),
            "--base",
            "missing-base",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "merge-base HEAD missing-base failed" in result.stderr


def test_unreleased_pin_fails_and_exact_workflow_tag_is_allowed(repo: Path) -> None:
    pins(repo, "0.38.0")
    manifests(repo, "1.1.0")
    log(repo, "unifi-network 1.1.0")
    with pytest.raises(ValueError, match="has no release tag"):
        versions.check(repo, "base", "protect/v0.38.0")
    versions.check(repo, "base", "network/v0.38.0")
    versions.git(repo, "tag", "network/v0.38.0")
    versions.check(repo, "base")


def test_version_only_bump_is_allowed(repo: Path) -> None:
    manifests(repo, "1.0.1")
    log(repo, "unifi-network 1.0.1")
    versions.check(repo, "base")


def test_changed_skill_with_bump_passes(repo: Path) -> None:
    change_skill(repo)
    manifests(repo, "1.0.1")
    log(repo, "unifi-network 1.0.1")
    versions.check(repo, "base")


def test_uses_merge_base_instead_of_tip(repo: Path) -> None:
    # A base branch ahead of this worker must not make its new version the baseline.
    versions.git(repo, "checkout", "-qb", "ahead")
    manifests(repo, "9.0.0")
    versions.git(repo, "add", ".")
    versions.git(repo, "commit", "-qm", "ahead")
    versions.git(repo, "checkout", "-")
    manifests(repo, "1.0.1")
    log(repo, "unifi-network 1.0.1")
    versions.check(repo, "ahead")


@pytest.mark.parametrize("client", versions.MANIFESTS)
def test_skills_only_plugin_checks_existing_manifests(repo: Path, client: str) -> None:
    write(repo, f"plugins/unifi-intelligence/{client}", {"name": "unifi-intelligence", "version": "1.0.0"})
    log(repo, "unifi-intelligence 1.0.0")
    versions.check(repo, "base")
    versions.git(repo, "add", ".")
    versions.git(repo, "commit", "-qm", "skills only")
    write(repo, f"plugins/unifi-intelligence/{client}", {"name": "unifi-intelligence", "version": "0.9.0"})
    with pytest.raises(ValueError, match="unifi-intelligence: changed plugin"):
        versions.check(repo, "HEAD")


def test_product_plugin_without_mcp_configs_fails(repo: Path) -> None:
    for filename in (".mcp.codex.json", ".claude-plugin/plugin.json"):
        data = json.loads((repo / "plugins/unifi-network" / filename).read_text())
        data.pop("mcpServers", None)
        write(repo, f"plugins/unifi-network/{filename}", data)
    (repo / "plugins/unifi-network/.mcp.codex.json").unlink()
    manifests(repo, "1.0.1")
    with pytest.raises(ValueError, match="unifi-network: missing MCP configs"):
        versions.check(repo, "base")


def test_renamed_plugin_is_checked_as_new(repo: Path) -> None:
    write(repo, "plugins/old-name/.claude-plugin/plugin.json", {"name": "old-name", "version": "1.1.0"})
    log(repo, "old-name 1.1.0", "new-name 1.0.0")
    versions.git(repo, "add", ".")
    versions.git(repo, "commit", "-qm", "old name")
    versions.git(repo, "branch", "-f", "base")
    versions.git(repo, "mv", "plugins/old-name", "plugins/new-name")
    edit(repo, "plugins/new-name/.claude-plugin/plugin.json", name="new-name", version="1.0.0")
    versions.check(repo, "base")
    versions.git(repo, "rm", "-rqf", "plugins/new-name")
    versions.check(repo, "base")


def test_plugin_needs_at_least_one_manifest(repo: Path) -> None:
    (repo / "plugins/unifi-intelligence").mkdir()
    with pytest.raises(ValueError, match="at least one plugin manifest"):
        versions.check(repo, "base")


@pytest.mark.parametrize(
    "plugin,old,new,expected",
    [
        ("1.4.9", "0.37.0", "0.37.1", "1.4.10"),
        ("1.4.9", "0.37.0", "0.38.0", "1.5.0"),
        ("1.4.9", "0.37.0", "1.0.0", "2.0.0"),
        ("0.4.9", "1.2.3", "1.2.4", "0.4.10"),
        ("0.4.9", "1.2.3", "1.3.0", "0.4.10"),
        ("0.4.9", "1.2.3", "2.0.0", "0.5.0"),
    ],
)
def test_pin_move_bump_rules(plugin: str, old: str, new: str, expected: str) -> None:
    assert versions.next_version(plugin, old, new) == expected


@pytest.mark.parametrize("new", ["0.37.0", "0.36.9"])
def test_pin_moves_must_advance(new: str) -> None:
    with pytest.raises(ValueError, match="pin must advance"):
        versions.next_version("1.0.0", "0.37.0", new)


@pytest.mark.parametrize("pin,expected", [("0.37.1", "1.0.1"), ("0.38.0", "1.1.0"), ("1.0.0", "2.0.0")])
def test_release_writeback_passes_guard_and_is_idempotent(repo: Path, pin: str, expected: str) -> None:
    versions.git(repo, "tag", f"network/v{pin}")
    # Real generator script, invoked by the module; no release/publication or client binary.
    script = repo / "scripts/generate_server_manifest.py"
    script.parent.mkdir()
    script.write_text((ROOT / "scripts/generate_server_manifest.py").read_text())
    versions.sync(repo)
    assert versions.plugin_state(repo / "plugins/unifi-network") == (expected, {"unifi-network-mcp": pin})
    assert json.loads((repo / "apps/network/server.json").read_text())["version"] == pin
    versions.check(repo, "base")
    changelog = (repo / versions.CHANGELOG).read_text()
    assert f"— unifi-network {expected}\n\n- Pins `unifi-network-mcp` [{pin}]" in changelog
    assert f"/releases/tag/network/v{pin})." in changelog
    before = versions.git(repo, "diff")
    versions.sync(repo)
    assert versions.git(repo, "diff") == before


def test_bump_without_changelog_entry_fails(repo: Path) -> None:
    change_skill(repo)
    manifests(repo, "1.0.1")
    log(repo, "unifi-network 1.0.10", "unifi-network-extra 1.0.1")
    with pytest.raises(ValueError, match="no entry heading naming unifi-network 1.0.1"):
        versions.check(repo, "base")
    (repo / versions.CHANGELOG).write_text((repo / versions.CHANGELOG).read_text() + "unifi-network 1.0.1\n")
    with pytest.raises(ValueError, match="no entry heading"):
        versions.check(repo, "base")


def test_one_writeback_records_every_plugin_it_bumped_newest_first(tmp_path: Path) -> None:
    (tmp_path / versions.CHANGELOG).write_text(f"# Changelog\n\n{versions.CHANGELOG_MARKER}\n\n## Older\n")
    versions.record_pin_moves(
        tmp_path,
        [
            ("unifi-network", "1.2.0", "unifi-network-mcp", "0.39.0"),
            ("unifi-protect", "1.1.4", "unifi-protect-mcp", "0.9.2"),
        ],
    )
    text = (tmp_path / versions.CHANGELOG).read_text()
    assert text.index("unifi-network 1.2.0, unifi-protect 1.1.4") < text.index("## Older")
    assert "[0.39.0](https://github.com/sirkirby/unifi-mcp/releases/tag/network/v0.39.0) and" in text
    assert versions.changelog_has(tmp_path, "unifi-protect", "1.1.4")


def test_writeback_refuses_a_changelog_without_its_marker(tmp_path: Path) -> None:
    (tmp_path / versions.CHANGELOG).write_text("# Changelog\n")
    with pytest.raises(ValueError, match="missing the entry marker"):
        versions.record_pin_moves(tmp_path, [("unifi-network", "1.2.0", "unifi-network-mcp", "0.39.0")])


def test_shipped_changelog_names_every_current_plugin_version() -> None:
    for bundle in sorted((ROOT / "plugins").iterdir()):
        if bundle.is_dir():
            version, _ = versions.plugin_state(bundle)
            assert versions.changelog_has(ROOT, bundle.name, version), f"{bundle.name} {version}"


def test_tag_discovery_does_not_depend_on_lexical_order() -> None:
    assert versions.latest_tag({"network/v0.9.0", "network/v0.10.0"}, "network") == "0.10.0"
    assert versions.latest_tag({"network/v2.0.0-rc.1", "network/v2.0.0"}, "network") == "2.0.0"
    assert versions.latest_tag({"v0.1.0", "v0.2.0"}, "network") == "0.2.0"
    assert versions.latest_tag({"core/v3.0.0", "relay/v2.0.0"}, "protect") is None


def test_pr_ci_and_precommit_share_guard() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/check-skill-references.yml").read_text())
    steps = workflow["jobs"]["check-drift"]["steps"]
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout"))
    assert checkout["with"]["fetch-depth"] == 0
    guard = next(step for step in steps if "make check-plugin-versions" in step.get("run", ""))
    assert guard["env"]["PLUGIN_BASE"] == "${{ github.event.pull_request.base.sha }}"
    makefile = (ROOT / "Makefile").read_text()
    assert "PLUGIN_VERSION_BASE ?= origin/main" in makefile
    assert "$(MAKE) check-plugin-versions" in makefile.split("pre-commit:\n", 1)[1]


def test_semver_precedence_orders_numeric_prereleases_and_ignores_build_metadata() -> None:
    ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.2", "1.0.0-alpha.10", "1.0.0-beta", "1.0.0-rc.1", "1.0.0"]
    keys = [versions.Version.parse(value).key for value in ordered]
    assert keys == sorted(keys)
    assert versions.Version.parse("1.0.0+one").key == versions.Version.parse("1.0.0+two").key


@pytest.mark.parametrize("stage", [False, True])
def test_tracked_plugin_edits_require_bump(repo: Path, stage: bool) -> None:
    config = json.loads((repo / "plugins/unifi-network/.mcp.codex.json").read_text())
    config["mcpServers"]["unifi-network"]["env"] = {"UNIFI_SETTINGS_FILE": "~/.config/unifi-mcp/network.env"}
    write(repo, "plugins/unifi-network/.mcp.codex.json", config)
    if stage:
        versions.git(repo, "add", ".")
    with pytest.raises(ValueError, match="strictly greater"):
        versions.check(repo, "base")


@pytest.mark.parametrize("product", ["network", "protect", "access"])
def test_update_pin_keeps_each_product_and_other_arguments(tmp_path: Path, product: str) -> None:
    bundle = tmp_path / f"unifi-{product}"
    for filename in versions.MANIFESTS:
        write(bundle, filename, {"name": bundle.name, "version": "1.3.7"})
    for filename in (".mcp.codex.json", ".claude-plugin/plugin.json"):
        edit(bundle, filename, mcpServers={bundle.name: {"args": ["--from", f"{bundle.name}-mcp==0.3.0", "--extra"]}})
    assert versions.update_pin(bundle, "0.4.0")
    assert versions.plugin_state(bundle) == ("1.4.0", {f"{bundle.name}-mcp": "0.4.0"})
    for filename in (".mcp.codex.json", ".claude-plugin/plugin.json"):
        args = json.loads((bundle / filename).read_text())["mcpServers"][bundle.name]["args"]
        assert args == ["--from", f"{bundle.name}-mcp==0.4.0", "--extra"]


def test_root_mcp_json_is_rejected(repo: Path) -> None:
    # OpenClaw would merge it into the bundled Codex server; Claude Code's servers are inline.
    edit(repo, "plugins/unifi-network/.mcp.json", mcpServers={})
    with pytest.raises(ValueError, match="root .mcp.json is unsupported"):
        versions.plugin_state(repo / "plugins/unifi-network")
