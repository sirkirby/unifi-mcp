"""Credential-free Git fixtures for plugin admission and release writebacks."""

from __future__ import annotations

import importlib.util
import json
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


def manifests(root: Path, version: str) -> None:
    for manifest in versions.MANIFESTS:
        edit(root, f"plugins/unifi-network/{manifest}", version=version)


def pins(root: Path, version: str) -> None:
    for filename in (".mcp.json", ".mcp.codex.json", ".claude-plugin/plugin.json"):
        edit(
            root,
            f"plugins/unifi-network/{filename}",
            mcpServers={"unifi-network": {"command": "uvx", "args": ["--from", f"unifi-network-mcp=={version}"]}},
        )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for manifest in versions.MANIFESTS:
        write(tmp_path, f"plugins/unifi-network/{manifest}", {"name": "unifi-network", "version": "1.0.0"})
    pins(tmp_path, "0.37.0")
    for marketplace in versions.MARKETPLACES:
        write(tmp_path, marketplace, {"plugins": [{"name": "unifi-network"}]})
    # Fixture identity and hooks are scoped to this disposable repository.
    versions.git(tmp_path, "config", "--local", "user.name", "Fixture")
    versions.git(tmp_path, "config", "--local", "user.email", "fixture@example.invalid")
    versions.git(tmp_path, "config", "--local", "commit.gpgsign", "false")
    versions.git(tmp_path, "config", "--local", "core.hooksPath", str(tmp_path / "no-hooks"))
    versions.git(tmp_path, "add", ".")
    versions.git(tmp_path, "commit", "-qm", "fixture")
    versions.git(tmp_path, "tag", "network/v0.37.0")
    versions.git(tmp_path, "branch", "base")
    return tmp_path


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
    with pytest.raises(ValueError, match="mismatched pins in inline"):
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
    with pytest.raises(ValueError, match="has no release tag"):
        versions.check(repo, "base", "protect/v0.38.0")
    versions.check(repo, "base", "network/v0.38.0")
    versions.git(repo, "tag", "network/v0.38.0")
    versions.check(repo, "base")


def test_version_only_bump_is_allowed(repo: Path) -> None:
    manifests(repo, "1.0.1")
    versions.check(repo, "base")


def test_changed_skill_with_bump_passes(repo: Path) -> None:
    change_skill(repo)
    manifests(repo, "1.0.1")
    versions.check(repo, "base")


def test_uses_merge_base_instead_of_tip(repo: Path) -> None:
    # A base branch ahead of this worker must not make its new version the baseline.
    versions.git(repo, "checkout", "-qb", "ahead")
    manifests(repo, "9.0.0")
    versions.git(repo, "add", ".")
    versions.git(repo, "commit", "-qm", "ahead")
    versions.git(repo, "checkout", "-")
    manifests(repo, "1.0.1")
    versions.check(repo, "ahead")


@pytest.mark.parametrize("client", versions.MANIFESTS)
def test_unlisted_skills_only_plugin_checks_existing_manifests(repo: Path, client: str) -> None:
    write(repo, f"plugins/cross-product/{client}", {"name": "cross-product", "version": "1.0.0"})
    versions.check(repo, "base")
    versions.git(repo, "add", ".")
    versions.git(repo, "commit", "-qm", "cross product")
    write(repo, f"plugins/cross-product/{client}", {"name": "cross-product", "version": "0.9.0"})
    with pytest.raises(ValueError, match="cross-product: changed plugin"):
        versions.check(repo, "HEAD")


def test_plugin_needs_at_least_one_manifest(repo: Path) -> None:
    (repo / "plugins/cross-product").mkdir()
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
    before = versions.git(repo, "diff")
    versions.sync(repo)
    assert versions.git(repo, "diff") == before


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
    config = json.loads((repo / "plugins/unifi-network/.mcp.json").read_text())
    config["mcpServers"]["unifi-network"]["env"] = {"UNIFI_TOOL_REGISTRATION_MODE": "eager"}
    write(repo, "plugins/unifi-network/.mcp.json", config)
    if stage:
        versions.git(repo, "add", ".")
    with pytest.raises(ValueError, match="strictly greater"):
        versions.check(repo, "base")


@pytest.mark.parametrize("product", ["network", "protect", "access"])
def test_update_pin_keeps_each_product_and_other_arguments(tmp_path: Path, product: str) -> None:
    bundle = tmp_path / f"unifi-{product}"
    for filename in versions.MANIFESTS:
        write(bundle, filename, {"name": bundle.name, "version": "1.3.7"})
    for filename in (".mcp.json", ".mcp.codex.json", ".claude-plugin/plugin.json"):
        edit(bundle, filename, mcpServers={bundle.name: {"args": ["--from", f"{bundle.name}-mcp==0.3.0", "--extra"]}})
    assert versions.update_pin(bundle, "0.4.0")
    assert versions.plugin_state(bundle) == ("1.4.0", {f"{bundle.name}-mcp": "0.4.0"})
    for filename in (".mcp.json", ".mcp.codex.json", ".claude-plugin/plugin.json"):
        args = json.loads((bundle / filename).read_text())["mcpServers"][bundle.name]["args"]
        assert args == ["--from", f"{bundle.name}-mcp==0.4.0", "--extra"]
