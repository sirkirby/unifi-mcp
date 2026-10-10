"""Static packaging contract for the Claude Code and Codex plugin marketplaces.

Field rules follow the published manifest references:

- Claude Code: https://code.claude.com/docs/en/plugins-reference and
  https://code.claude.com/docs/en/plugins/marketplace-reference
- Codex: https://developers.openai.com/plugins/build/plugins and
  https://developers.openai.com/plugins/deploy/submission#manifest-fields

These checks prove the repository is internally consistent. They do not prove a
real client installs or launches a bundle.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MARKETPLACE = Path(".claude-plugin/marketplace.json")
CODEX_MARKETPLACE = Path(".agents/plugins/marketplace.json")
BUMP_WORKFLOW = Path(".github/workflows/bump-plugin-versions.yml")
SUPPORT_DOC = Path("docs/plugin-support.md")

PLUGIN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
# Same pattern the release workflow uses to rewrite package pins.
PACKAGE_PIN = re.compile(r"^(unifi-[a-z]+-mcp)==(.+)$")
ENV_REFERENCE = re.compile(r"^\$\{[A-Z0-9_]+(?::-[^}]*)?\}$")
AGENT_PLUGINS_SCHEMA = "https://agent-plugins.org/schemas/"
CODEX_INSTALL_POLICIES = {"AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"}
CODEX_INTERFACE_FIELDS = ("displayName", "shortDescription", "longDescription", "developerName", "category")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _relative_dir(root: Path, value: object, where: str, errors: list[str]) -> Path | None:
    """Resolve a ``./``-prefixed path that must stay inside ``root`` and exist."""
    if not isinstance(value, str) or not value.startswith("./"):
        errors.append(f"{where}: path {value!r} must be a string starting with './'")
        return None
    if ".." in Path(value).parts:
        errors.append(f"{where}: path {value!r} must not contain '..'")
        return None
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        errors.append(f"{where}: path {value!r} escapes {root}")
        return None
    if not resolved.exists():
        errors.append(f"{where}: path {value!r} does not exist")
        return None
    return resolved


def claude_marketplace_bundles(root: Path, errors: list[str]) -> dict[str, Path]:
    data = _load(root / CLAUDE_MARKETPLACE)
    where = str(CLAUDE_MARKETPLACE)
    if not PLUGIN_ID.match(data.get("name", "")):
        errors.append(f"{where}: marketplace name {data.get('name')!r} is not a valid plugin id part")
    if not (data.get("owner") or {}).get("name"):
        errors.append(f"{where}: owner.name is required")
    bundles: dict[str, Path] = {}
    for index, entry in enumerate(data.get("plugins", [])):
        name = entry.get("name", "")
        if not PLUGIN_ID.match(name):
            errors.append(f"{where}: plugins[{index}].name {name!r} is not a valid plugin id part")
        if name in bundles:
            errors.append(f"{where}: duplicate plugin name {name!r}")
        source = _relative_dir(root, entry.get("source"), f"{where} plugins[{index}].source", errors)
        if source is not None:
            bundles[name] = source
    return bundles


def codex_marketplace_bundles(root: Path, errors: list[str]) -> dict[str, Path]:
    data = _load(root / CODEX_MARKETPLACE)
    where = str(CODEX_MARKETPLACE)
    if not data.get("name"):
        errors.append(f"{where}: top-level name is required")
    if not (data.get("interface") or {}).get("displayName"):
        errors.append(f"{where}: interface.displayName is required")
    bundles: dict[str, Path] = {}
    for index, entry in enumerate(data.get("plugins", [])):
        entry_where = f"{where} plugins[{index}]"
        name = entry.get("name", "")
        if not KEBAB.match(name):
            errors.append(f"{entry_where}: name {name!r} must be kebab-case")
        if name in bundles:
            errors.append(f"{where}: duplicate plugin name {name!r}")
        source = entry.get("source")
        if isinstance(source, dict):
            if source.get("source") != "local":
                errors.append(f"{entry_where}: only local sources are expected in the repo marketplace")
                continue
            source = source.get("path")
        policy = entry.get("policy") or {}
        if policy.get("installation") not in CODEX_INSTALL_POLICIES:
            errors.append(f"{entry_where}: policy.installation must be one of {sorted(CODEX_INSTALL_POLICIES)}")
        if not policy.get("authentication"):
            errors.append(f"{entry_where}: policy.authentication is required")
        if not entry.get("category"):
            errors.append(f"{entry_where}: category is required")
        resolved = _relative_dir(root, source, f"{entry_where}.source", errors)
        if resolved is not None:
            bundles[name] = resolved
    return bundles


def check_claude_manifest(bundle: Path, expected_name: str | None, errors: list[str]) -> dict | None:
    path = bundle / ".claude-plugin" / "plugin.json"
    where = str(path.relative_to(bundle.parent.parent))
    if not path.is_file():
        errors.append(f"{where}: missing Claude manifest")
        return None
    data = _load(path)
    name = data.get("name", "")
    if not KEBAB.match(name):
        errors.append(f"{where}: name {name!r} must be kebab-case")
    if expected_name is not None and name != expected_name:
        errors.append(f"{where}: name {name!r} does not match marketplace entry {expected_name!r}")
    author = data.get("author")
    if not isinstance(author, dict) or not author.get("name"):
        errors.append(f"{where}: author must be an object with a name")
    for field in ("version", "description"):
        if not isinstance(data.get(field), str) or not data.get(field):
            errors.append(f"{where}: {field} must be a non-empty string")
    if "keywords" in data and not all(isinstance(k, str) for k in data["keywords"]):
        errors.append(f"{where}: keywords must be strings")
    return data


def resolve_codex_manifest(bundle: Path, errors: list[str]) -> dict | None:
    """Select the manifest Codex reads, following the documented fallback order.

    A portable root ``plugin.json`` is canonical. Its inline
    ``extensions.com.openai`` object replaces ``.codex-plugin/plugin.json``;
    when that object is absent the legacy overlay supplies OpenAI settings.
    Without a portable root, ``.codex-plugin/plugin.json`` is the whole manifest.
    """
    where = bundle.name
    portable = bundle / "plugin.json"
    legacy = bundle / ".codex-plugin" / "plugin.json"
    if portable.is_file():
        data = _load(portable)
        if not str(data.get("$schema", "")).startswith(AGENT_PLUGINS_SCHEMA):
            errors.append(f"{where}/plugin.json: portable manifest must declare the Agent Plugins $schema")
        openai = (data.get("extensions") or {}).get("com.openai")
        if isinstance(openai, dict):
            return {"layout": "portable", "identity": data, "openai": openai, "openai_source": portable}
        if legacy.is_file():
            return {"layout": "portable", "identity": data, "openai": _load(legacy), "openai_source": legacy}
        return {"layout": "portable", "identity": data, "openai": {}, "openai_source": None}
    if legacy.is_file():
        data = _load(legacy)
        return {"layout": "legacy", "identity": data, "openai": data, "openai_source": legacy}
    # Codex also accepts a Claude-compatible manifest, but advertised bundles
    # carry explicit Codex listing metadata.
    errors.append(f"{where}: no portable plugin.json or .codex-plugin/plugin.json for Codex")
    return None


def check_codex_manifest(bundle: Path, expected_name: str, errors: list[str]) -> dict | None:
    resolved = resolve_codex_manifest(bundle, errors)
    if resolved is None:
        return None
    where = bundle.name
    identity = resolved["identity"]
    if identity.get("name") != expected_name:
        errors.append(f"{where}: Codex manifest name {identity.get('name')!r} does not match {expected_name!r}")
    if resolved["layout"] == "legacy":
        for field in ("version", "description"):
            if not identity.get(field):
                errors.append(f"{where}: Codex format requires {field}")
        if not (identity.get("author") or {}).get("name"):
            errors.append(f"{where}: Codex format requires author.name")
        skills = identity.get("skills")
        for entry in skills if isinstance(skills, list) else [skills] if skills else []:
            _relative_dir(bundle, entry, f"{where} skills", errors)
        if "mcpServers" in identity:
            _relative_dir(bundle, identity["mcpServers"], f"{where} mcpServers", errors)
        interface = identity.get("interface")
        if not isinstance(interface, dict):
            errors.append(f"{where}: Codex format requires an interface object")
        else:
            for field in CODEX_INTERFACE_FIELDS:
                if not interface.get(field):
                    errors.append(f"{where}: interface.{field} is required")
            if not isinstance(interface.get("capabilities"), list):
                errors.append(f"{where}: interface.capabilities must be a list")
    return resolved


def mcp_config_path(bundle: Path, resolved: dict | None) -> Path:
    if resolved is not None and resolved["layout"] == "portable":
        return bundle / "mcp.json"
    return bundle / (resolved["identity"].get("mcpServers", "./.mcp.json") if resolved else ".mcp.json")


def app_package_names(root: Path) -> dict[str, set[str]]:
    """Map each workspace app package name to its console script names."""
    packages: dict[str, set[str]] = {}
    for pyproject in sorted((root / "apps").glob("*/pyproject.toml")):
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        packages[project.get("name", "")] = set(project.get("scripts", {}))
    return packages


def check_mcp_servers(
    path: Path, root: Path, errors: list[str], *, portable: bool, codex: bool = False
) -> dict[str, tuple[str, str]]:
    """Validate stdio launch definitions and return ``{server: (package, version)}``."""
    where = str(path.relative_to(root))
    if not path.is_file():
        errors.append(f"{where}: missing MCP configuration")
        return {}
    data = _load(path)
    if portable and not str(data.get("$schema", "")).startswith(AGENT_PLUGINS_SCHEMA):
        errors.append(f"{where}: portable mcp.json must declare the Agent Plugins $schema")
    packages = app_package_names(root)
    pins: dict[str, tuple[str, str]] = {}
    for server_name, server in (data.get("mcpServers") or {}).items():
        server_where = f"{where} mcpServers.{server_name}"
        if portable and server.get("type") != "stdio":
            errors.append(f"{server_where}: portable mcp.json must declare type 'stdio'")
        if server.get("type", "stdio") != "stdio":
            errors.append(f"{server_where}: expected a stdio server")
        if server.get("command") != "uvx":
            errors.append(f"{server_where}: command must be 'uvx'")
        matches = [PACKAGE_PIN.match(arg) for arg in server.get("args", [])]
        matches = [m for m in matches if m]
        if len(matches) != 1:
            errors.append(f"{server_where}: expected exactly one unifi-*-mcp==<version> pin")
            continue
        package, version = matches[0].groups()
        if not SEMVER.match(version):
            errors.append(f"{server_where}: pin version {version!r} is not X.Y.Z")
        if package not in packages:
            errors.append(f"{server_where}: {package!r} is not a workspace app package")
        elif package not in packages[package]:
            errors.append(f"{server_where}: {package!r} declares no console script of the same name for uvx")
        for key, value in (server.get("env") or {}).items():
            if codex and "${" in str(value):
                errors.append(f"{server_where}: Codex env {key} must not contain interpolation templates")
            elif not codex and not ENV_REFERENCE.match(str(value)):
                errors.append(f"{server_where}: env {key} must be a ${{VAR}} reference, not a literal")
        pins[server_name] = (package, version)
    return pins


def check_skills(bundle: Path, root: Path, errors: list[str]) -> list[str]:
    names: list[str] = []
    for skill in sorted((bundle / "skills").glob("*/SKILL.md")):
        where = str(skill.relative_to(root))
        text = skill.read_text(encoding="utf-8")
        parts = text.split("---\n", 2)
        if not text.startswith("---\n") or len(parts) < 3:
            errors.append(f"{where}: missing YAML frontmatter")
            continue
        frontmatter = yaml.safe_load(parts[1]) or {}
        if frontmatter.get("name") != skill.parent.name:
            errors.append(f"{where}: frontmatter name must match directory {skill.parent.name!r}")
        if not str(frontmatter.get("description") or "").strip():
            errors.append(f"{where}: frontmatter description is required")
        names.append(skill.parent.name)
    return names


def packaging_errors(root: Path) -> list[str]:
    errors: list[str] = []
    claude = claude_marketplace_bundles(root, errors)
    codex = codex_marketplace_bundles(root, errors)

    for name in sorted(set(claude) ^ set(codex)):
        listed = "Claude" if name in claude else "Codex"
        errors.append(f"{name}: advertised only in the {listed} marketplace")
    for name in sorted(set(claude) & set(codex)):
        if claude[name] != codex[name]:
            errors.append(f"{name}: marketplaces point at different directories")

    advertised = {path.resolve() for path in (*claude.values(), *codex.values())}
    for plugin_dir in sorted((root / "plugins").glob("*/.claude-plugin")):
        if plugin_dir.parent.resolve() not in advertised:
            check_claude_manifest(plugin_dir.parent, None, errors)

    workflow = (root / BUMP_WORKFLOW).read_text(encoding="utf-8")
    synced = set(re.findall(r'update_plugin_version "plugins/([a-z0-9-]+)"', workflow))

    for name in sorted(set(claude) | set(codex)):
        bundle = claude.get(name) or codex[name]
        claude_manifest = check_claude_manifest(bundle, name, errors)
        resolved = check_codex_manifest(bundle, name, errors)
        portable = resolved is not None and resolved["layout"] == "portable"
        # Validate Claude and Codex launch files independently.
        pins = check_mcp_servers(bundle / ".mcp.json", root, errors, portable=False)
        codex_path = mcp_config_path(bundle, resolved)
        portable_pins = check_mcp_servers(codex_path, root, errors, portable=portable, codex=True)
        skills = check_skills(bundle, root, errors)
        if not skills:
            errors.append(f"{name}: bundle ships no skills")
        if pins and f"{name}-setup" not in skills:
            errors.append(f"{name}: MCP bundle has no {name}-setup skill")

        versions = {"Claude manifest": (claude_manifest or {}).get("version")}
        if resolved is not None:
            versions["Codex manifest"] = resolved["identity"].get("version")
        versions.update({f".mcp.json {server} pin": version for server, (_, version) in pins.items()})
        versions.update({f"Codex MCP config {server} pin": version for server, (_, version) in portable_pins.items()})
        inline = (claude_manifest or {}).get("mcpServers")
        claude_mcp = bundle / ".mcp.json"
        if isinstance(inline, dict) and claude_mcp.is_file():
            # Claude loads .mcp.json first, then inline servers replace same-named ones.
            mcp_file = _load(claude_mcp).get("mcpServers", {})
            for server_name, server in inline.items():
                expected = {k: v for k, v in mcp_file.get(server_name, {}).items() if k not in {"type", "extensions"}}
                actual = {k: v for k, v in server.items() if k != "type"}
                if actual != expected:
                    errors.append(f"{name}: inline Claude mcpServers.{server_name} differs from the MCP config file")
        if len(set(versions.values())) != 1:
            errors.append(f"{name}: versions out of lockstep: {versions}")

        if pins:
            if name not in synced:
                errors.append(f"{name}: {BUMP_WORKFLOW} does not sync this bundle's versions")
            if portable:
                for required in ('"$plugin_dir/plugin.json"', '"$plugin_dir/mcp.json"'):
                    if required not in workflow:
                        errors.append(f"{name}: {BUMP_WORKFLOW} does not update portable {required}")
    return errors


def _copy_packaging_tree(destination: Path) -> Path:
    for relative in (CLAUDE_MARKETPLACE, CODEX_MARKETPLACE, BUMP_WORKFLOW):
        (destination / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, destination / relative)
    for pyproject in (REPO_ROOT / "apps").glob("*/pyproject.toml"):
        target = destination / pyproject.relative_to(REPO_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pyproject, target)
    shutil.copytree(REPO_ROOT / "plugins", destination / "plugins", ignore=shutil.ignore_patterns("scripts"))
    return destination


def _edit_json(path: Path, mutate) -> None:
    data = _load(path)
    mutate(data)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _advertised_bundles() -> list[str]:
    return sorted(claude_marketplace_bundles(REPO_ROOT, []))


def test_repository_packaging_is_consistent() -> None:
    errors = packaging_errors(REPO_ROOT)

    assert errors == [], "\n".join(errors)


def test_every_advertised_bundle_is_in_both_marketplaces() -> None:
    claude = claude_marketplace_bundles(REPO_ROOT, [])
    codex = codex_marketplace_bundles(REPO_ROOT, [])

    assert claude, "Claude marketplace advertises no bundles"
    assert set(claude) == set(codex)


def test_support_doc_states_python_floor_and_current_versions() -> None:
    doc = (REPO_ROOT / SUPPORT_DOC).read_text(encoding="utf-8")
    floors = {
        tomllib.loads(path.read_text(encoding="utf-8"))["project"]["requires-python"]
        for path in (REPO_ROOT / "apps").glob("*/pyproject.toml")
    }

    assert floors == {">=3.13"}, "update the Python requirement in docs/plugin-support.md"
    assert "Python 3.13" in doc
    for label in ("`tested`", "`unsupported`", "`not tested`"):
        assert label in doc


def test_support_doc_states_setup_helper_runtime() -> None:
    doc = (REPO_ROOT / SUPPORT_DOC).read_text(encoding="utf-8")
    helpers = sorted((REPO_ROOT / "plugins").glob("*/scripts/*.sh")) + sorted(
        (REPO_ROOT / "plugins").glob("*/scripts/*.ps1")
    )
    floors = {
        match
        for helper in helpers
        for match in re.findall(r"sys\.version_info >= \((\d+), (\d+)\)", helper.read_text(encoding="utf-8"))
    }

    assert helpers, "no setup helpers found"
    assert len(floors) == 1, f"setup helpers disagree on the Python floor: {floors}"
    major, minor = floors.pop()
    assert f"Python {major}.{minor} or newer on `PATH`, or `uv`" in doc
    assert "needs `python3`" not in doc


@pytest.mark.parametrize("name", _advertised_bundles())
def test_setup_skill_names_the_scoped_claude_reconnect(name: str) -> None:
    bundle = REPO_ROOT / "plugins" / name
    servers = (_load(bundle / ".mcp.json").get("mcpServers") or {}) if (bundle / ".mcp.json").is_file() else {}
    if not servers:
        pytest.skip("bundle declares no MCP server")
    skill = (bundle / "skills" / f"{name}-setup" / "SKILL.md").read_text(encoding="utf-8")

    for server in servers:
        # Claude Code registers plugin servers as plugin:<plugin>:<server>; a cached
        # start failure is retried only by an explicit reconnect of that name.
        assert f"/mcp reconnect plugin:{name}:{server}" in skill


@pytest.mark.parametrize("name", _advertised_bundles())
def test_bundle_skill_frontmatter_is_valid(name: str) -> None:
    errors: list[str] = []

    assert check_skills(REPO_ROOT / "plugins" / name, REPO_ROOT, errors)
    assert errors == []


def test_broken_marketplace_source_path_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    _edit_json(root / CLAUDE_MARKETPLACE, lambda d: d["plugins"][0].update(source="./plugins/missing"))

    errors = packaging_errors(root)

    assert any("'./plugins/missing' does not exist" in error for error in errors)


def test_source_path_outside_marketplace_root_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    _edit_json(root / CODEX_MARKETPLACE, lambda d: d["plugins"][0]["source"].update(path="./../elsewhere"))

    errors = packaging_errors(root)

    assert any("must not contain '..'" in error for error in errors)


def test_package_pin_drift_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    mcp = root / "plugins" / name / ".mcp.json"

    def bump(data: dict) -> None:
        server = next(iter(data["mcpServers"].values()))
        server["args"] = [re.sub(r"==.*$", "==999.0.0", arg) for arg in server["args"]]

    _edit_json(mcp, bump)

    errors = packaging_errors(root)

    assert any(f"{name}: versions out of lockstep" in error for error in errors)


def test_unknown_package_name_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]

    def rename(data: dict) -> None:
        server = next(iter(data["mcpServers"].values()))
        server["args"] = [re.sub(r"^unifi-[a-z]+-mcp==", "unifi-bogus-mcp==", arg) for arg in server["args"]]

    _edit_json(root / "plugins" / name / ".mcp.json", rename)

    errors = packaging_errors(root)

    assert any("'unifi-bogus-mcp' is not a workspace app package" in error for error in errors)


def test_literal_env_value_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    _edit_json(
        root / "plugins" / name / ".mcp.json",
        lambda d: next(iter(d["mcpServers"].values()))["env"].update(UNIFI_HOST="192.0.2.1"),
    )

    errors = packaging_errors(root)

    assert any("env UNIFI_HOST must be a ${VAR} reference" in error for error in errors)


def test_bundle_missing_from_one_marketplace_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    _edit_json(root / CODEX_MARKETPLACE, lambda d: d.update(plugins=[p for p in d["plugins"] if p["name"] != name]))

    errors = packaging_errors(root)

    assert f"{name}: advertised only in the Claude marketplace" in errors


def test_bundle_not_synced_by_release_workflow_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    workflow = root / BUMP_WORKFLOW
    workflow.write_text(
        workflow.read_text(encoding="utf-8").replace(f'update_plugin_version "plugins/{name}"', "true"),
        encoding="utf-8",
    )

    errors = packaging_errors(root)

    assert any(f"{name}: {BUMP_WORKFLOW} does not sync" in error for error in errors)


def test_claude_author_string_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    _edit_json(root / "plugins" / "cross-product" / ".claude-plugin" / "plugin.json", lambda d: d.update(author="x"))

    errors = packaging_errors(root)

    assert any("cross-product/.claude-plugin/plugin.json: author must be an object" in error for error in errors)


def test_legacy_codex_manifest_is_used_without_portable_root(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    errors: list[str] = []

    resolved = check_codex_manifest(root / "plugins" / name, name, errors)

    assert errors == []
    assert resolved is not None
    assert resolved["layout"] == "legacy"
    assert resolved["openai_source"] == root / "plugins" / name / ".codex-plugin" / "plugin.json"
    assert mcp_config_path(root / "plugins" / name, resolved).name == ".mcp.codex.json"


def test_legacy_manifest_with_missing_skills_path_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    _edit_json(root / "plugins" / name / ".codex-plugin" / "plugin.json", lambda d: d.update(skills="./nope/"))

    errors = packaging_errors(root)

    assert any(f"{name} skills: path './nope/' does not exist" in error for error in errors)


def test_portable_root_takes_precedence_and_falls_back_to_legacy_overlay(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    bundle = root / "plugins" / name
    legacy = _load(bundle / ".codex-plugin" / "plugin.json")
    portable = {"$schema": f"{AGENT_PLUGINS_SCHEMA}1.0.0/plugin.schema.json", "name": name}
    portable.update({key: legacy[key] for key in ("version", "description", "author")})
    (bundle / "plugin.json").write_text(json.dumps(portable), encoding="utf-8")
    errors: list[str] = []

    resolved = check_codex_manifest(bundle, name, errors)

    assert errors == []
    assert resolved is not None
    assert resolved["layout"] == "portable"
    assert resolved["openai_source"] == bundle / ".codex-plugin" / "plugin.json"
    assert mcp_config_path(bundle, resolved).name == "mcp.json"


def test_inline_openai_extension_replaces_legacy_overlay(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    bundle = root / "plugins" / name
    interface = {"displayName": "Inline"}
    portable = {
        "$schema": f"{AGENT_PLUGINS_SCHEMA}1.0.0/plugin.schema.json",
        "name": name,
        "extensions": {"com.openai": {"interface": interface}},
    }
    (bundle / "plugin.json").write_text(json.dumps(portable), encoding="utf-8")

    resolved = resolve_codex_manifest(bundle, [])

    assert resolved is not None
    assert resolved["openai_source"] == bundle / "plugin.json"
    assert resolved["openai"]["interface"] == interface


def test_portable_layout_requires_schema_mcp_json_and_release_sync(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    bundle = root / "plugins" / name
    legacy = _load(bundle / ".codex-plugin" / "plugin.json")
    (bundle / "plugin.json").write_text(
        json.dumps({"name": name, "version": legacy["version"], "description": legacy["description"]}),
        encoding="utf-8",
    )

    errors = packaging_errors(root)

    assert f"{name}/plugin.json: portable manifest must declare the Agent Plugins $schema" in errors
    assert any("mcp.json: missing MCP configuration" in error for error in errors)


def test_bundle_without_any_codex_manifest_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    (root / "plugins" / name / ".codex-plugin" / "plugin.json").unlink()

    errors = packaging_errors(root)

    assert f"{name}: no portable plugin.json or .codex-plugin/plugin.json for Codex" in errors


@pytest.mark.parametrize("name", _advertised_bundles())
def test_codex_launch_avoids_literal_credential_templates(name: str) -> None:
    bundle = REPO_ROOT / "plugins" / name
    resolved = check_codex_manifest(bundle, name, [])
    config = _load(mcp_config_path(bundle, resolved))
    for server in config["mcpServers"].values():
        assert not server.get("env"), "Let the server use its defaults until setup supplies an environment"
        assert "${" not in json.dumps(server)


def test_codex_template_regression_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    bundle = root / "plugins" / name
    _edit_json(bundle / ".codex-plugin/plugin.json", lambda d: d.update(mcpServers="./.mcp.json"))

    assert any("Codex env" in error for error in packaging_errors(root))


def test_codex_package_pin_drift_is_reported(tmp_path: Path) -> None:
    root = _copy_packaging_tree(tmp_path)
    name = _advertised_bundles()[0]
    bundle = root / "plugins" / name
    path = mcp_config_path(bundle, check_codex_manifest(bundle, name, []))
    _edit_json(path, lambda d: next(iter(d["mcpServers"].values())).update(args=[name + "-mcp==999.0.0"]))

    assert any("versions out of lockstep" in error for error in packaging_errors(root))


@pytest.mark.parametrize("name", _advertised_bundles())
@pytest.mark.parametrize("filename", [".mcp.json", ".mcp.codex.json", ".claude-plugin/plugin.json"])
def test_every_client_package_pin_matches_plugin_version(name: str, filename: str) -> None:
    bundle = REPO_ROOT / "plugins" / name
    version = _load(bundle / ".codex-plugin/plugin.json")["version"]
    pins = check_mcp_servers(bundle / filename, REPO_ROOT, [], portable=False, codex="codex" in filename)

    assert pins == {name: (f"{name}-mcp", version)}


@pytest.mark.parametrize("name", _advertised_bundles())
def test_version_workflow_updates_every_client_pin(tmp_path: Path, name: str) -> None:
    root = _copy_packaging_tree(tmp_path)
    workflow = yaml.safe_load((root / BUMP_WORKFLOW).read_text())
    run = next(
        step["run"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "update_plugin_version()" in step.get("run", "")
    )
    # Exercise the real workflow functions without tag discovery, commits or publication.
    functions = run.split("NETWORK_VERSION=", 1)[0]
    subprocess.run(
        ["bash", "-c", functions + '\nupdate_plugin_version "$1" "$2"', "fixture", f"plugins/{name}", "999.0.0"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    bundle = root / "plugins" / name
    for filename in (".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
        assert _load(bundle / filename)["version"] == "999.0.0"
    for filename in (".mcp.json", ".mcp.codex.json", ".claude-plugin/plugin.json"):
        pins = check_mcp_servers(bundle / filename, root, [], portable=False, codex="codex" in filename)
        assert pins == {name: (f"{name}-mcp", "999.0.0")}, filename
