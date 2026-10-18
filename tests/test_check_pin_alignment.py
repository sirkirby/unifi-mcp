from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_pin_alignment.py"


def _module():
    spec = importlib.util.spec_from_file_location("check_pin_alignment", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _wheel_with_requirements(
    tmp_path: Path,
    requirements: list[str],
    *,
    version: str = "1.0.0",
) -> Path:
    wheel = tmp_path / "unifi_api_server-1.0.0-py3-none-any.whl"
    lines = ["Metadata-Version: 2.4", "Name: unifi-api-server", f"Version: {version}"]
    lines.extend(f"Requires-Dist: {requirement}" for requirement in requirements)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("unifi_api_server-1.0.0.dist-info/METADATA", "\n".join(lines) + "\n")
    return wheel


def _wheel(tmp_path: Path, requirement: str | None) -> Path:
    return _wheel_with_requirements(tmp_path, [] if requirement is None else [requirement])


def test_extracts_api_core_lower_bound_from_wheel_metadata(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel(tmp_path, "unifi-core[access,network,protect]>=0.4.23,<0.5")

    assert module.api_core_floor_from_wheel(wheel) == "0.4.23"


def test_extracts_network_core_lower_bound_from_wheel_metadata(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel(tmp_path, "unifi-core[network]>=0.4.32,<0.5")

    assert module.network_core_floor_from_wheel(wheel) == "0.4.32"


@pytest.mark.parametrize("requirement", [None, "unifi-core<0.5"])
def test_missing_core_floor_fails_closed(tmp_path: Path, requirement: str | None) -> None:
    module = _module()
    wheel = _wheel(tmp_path, requirement)

    with pytest.raises(RuntimeError):
        module.api_core_floor_from_wheel(wheel)


def test_api_floor_contract_is_valid_python() -> None:
    module = _module()

    compile(module._API_CATALOG_FLOOR_CONTRACT, "<api-catalog-floor-contract>", "exec")


def test_network_floor_contract_is_valid_python() -> None:
    module = _module()

    compile(module._NETWORK_CORE_FLOOR_CONTRACT, "<network-core-floor-contract>", "exec")


def test_security_floor_check_accepts_explicit_safe_wheel_metadata(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel_with_requirements(
        tmp_path,
        [
            "anyio>=4.14.2",
            "cryptography>=50.0.0",
            "PyJWT>=2.15.0",
            "python-multipart>=0.0.31",
            "starlette>=1.3.1",
            "click>=8.3.3",
            "multidict>=6.9.1",
            "Mako>=1.4.2",
        ],
    )

    ok, message = module.check_security_floors("unifi-api-server", wheel)

    assert ok is True
    assert "all advisory-safe" in message


def test_security_floor_check_rejects_missing_or_vulnerable_floor(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel_with_requirements(
        tmp_path,
        [
            "anyio>=4.12.0",
            "cryptography>=49.0.0",
            "PyJWT>=2.13.0",
            "python-multipart>=0.0.31",
            "starlette>=1.3.1",
        ],
    )

    ok, message = module.check_security_floors("unifi-api-server", wheel)

    assert ok is False
    assert "anyio>=4.14.2" in message
    assert "cryptography>=50.0.0" in message
    assert "click>=8.3.3" in message
    assert "pyjwt>=2.15.0" in message.lower()


def test_security_floor_check_honors_extra_markers_and_higher_floors(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel_with_requirements(tmp_path, ['PyJWT>=2.16.0; extra == "protect"', "multidict>=6.10.0"])

    ok, _ = module.check_security_floors("unifi-core", wheel)

    assert ok is True


def test_security_floor_check_rejects_inapplicable_marker(tmp_path: Path) -> None:
    module = _module()
    requirements = [f'{name}>={floor}; python_version < "3"' for name, floor in module.MCP_SECURITY_FLOORS.items()]
    wheel = _wheel_with_requirements(tmp_path, requirements)

    ok, message = module.check_security_floors("unifi-mcp-shared", wheel)

    assert ok is False
    assert "missing unconditional" in message


def test_security_floor_check_rejects_prerelease_below_final_floor(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel_with_requirements(
        tmp_path,
        [
            "anyio>=4.14.2",
            "cryptography>=50.0.0rc1",
            "PyJWT>=2.15.0",
            "python-multipart>=0.0.31",
            "starlette>=1.3.1",
            "click>=8.3.3",
        ],
    )

    ok, message = module.check_security_floors("unifi-api-server", wheel)

    assert ok is False
    assert "cryptography>=50.0.0" in message


def test_security_upgrade_installs_additional_workspace_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    commands: list[list[str]] = []

    monkeypatch.setattr(module.venv, "create", lambda *args, **kwargs: None)

    def fake_run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if len(command) >= 2 and command[-2] == "-c" and "importlib.metadata" in command[-1]:
            versions = "\n".join(
                f"{name}={floor}" for name, floor in module.SECURITY_FLOORS["unifi-network-mcp"].items()
            )
            return subprocess.CompletedProcess(command, 0, stdout=versions, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_capture", fake_run_capture)

    ok, _, _ = module.install_security_upgrade(
        "unifi-network-mcp",
        "/tmp/network.whl",
        tmp_path,
        tmp_path / "venv",
        additional_targets=("/tmp/shared.whl", "/tmp/core.whl"),
    )

    assert ok is True
    install_command = commands[1]
    assert install_command[-3:] == [
        "/tmp/network.whl",
        "/tmp/shared.whl",
        "/tmp/core.whl",
    ]


def test_release_candidate_wheel_rebuilds_dev_version_as_stable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    development = _wheel_with_requirements(tmp_path, [], version="0.6.10.dev5+gabc123")
    stable = tmp_path / "unifi_mcp_shared-0.6.10-py3-none-any.whl"
    calls: list[str | None] = []

    def fake_build_wheel(src: Path, out_dir: Path, *, pretend_version: str | None = None) -> Path:
        calls.append(pretend_version)
        if pretend_version is None:
            return development
        stable.touch()
        return stable

    monkeypatch.setattr(module, "build_wheel", fake_build_wheel)

    result = module.build_release_candidate_wheel(tmp_path / "shared", tmp_path)

    assert result == stable
    assert calls == [None, "0.6.10"]


def test_dependency_names_are_read_from_wheel_metadata(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel_with_requirements(
        tmp_path,
        ["unifi-mcp-shared>=0.6.10,<0.7", "unifi-core[network]>=0.4.37,<0.5"],
    )

    assert module.wheel_dependency_names(wheel) == {
        "unifi-mcp-shared",
        "unifi-core",
    }


def test_release_candidate_wheels_exclude_unpublished_core(tmp_path: Path) -> None:
    module = _module()
    shared = tmp_path / "unifi_mcp_shared-0.6.10-py3-none-any.whl"
    core = tmp_path / "unifi_core-0.4.38.dev1-py3-none-any.whl"

    assert module.release_candidate_wheels(
        {
            "unifi-mcp-shared": shared,
            "unifi-core": core,
        }
    ) == (shared,)


def test_core_floor_contract_installs_branch_shared_wheel(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module()
    commands: list[list[str]] = []

    monkeypatch.setattr(module.venv, "create", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "core_floor_from_wheel", lambda *args: "0.4.37")

    def fake_run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="contract passed", stderr="")

    monkeypatch.setattr(module, "run_capture", fake_run_capture)

    ok, _ = module.check_core_floor_contract(
        tmp_path / "network.whl",
        tmp_path / "venv",
        package_label="Network",
        core_extras="network",
        contract="print('contract passed')",
        additional_targets=("/tmp/shared.whl",),
    )

    assert ok is True
    assert commands[0][-2:] == [
        str(tmp_path / "network.whl"),
        "/tmp/shared.whl",
    ]


# --- import walk and upstream attribute scan --------------------------------

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "check-pin-alignment.yml"


def _install_fixture(site: Path, files: dict[str, str], *, dist: str = "fixturepkg") -> None:
    """Lay out a fake installed distribution (modules plus dist-info/RECORD) under ``site``."""
    for relative, content in files.items():
        path = site / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    info = site / f"{dist}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.4\nName: {dist}\nVersion: 1.0\n")
    records = [f"{relative},," for relative in files if relative.startswith(f"{dist}/")]
    records.append(f"{info.name}/METADATA,,")
    (info / "RECORD").write_text("\n".join(records) + "\n")


# A stand-in for the PyPI-resolved (or floor) upstream: it has `old_helper` and
# `Client.old_method`, but not the newer `new_helper` / `Client.new_method`.
UPSTREAM_STUB = {
    "unifi_core/__init__.py": "",
    "unifi_core/auth.py": (
        "def old_helper():\n    return 1\n\nclass Client:\n    def old_method(self):\n        return 1\n"
    ),
}


def _run_script(script: str, site: Path) -> subprocess.CompletedProcess[str]:
    # -S keeps the interpreter off the repo's site-packages so only the fixture
    # (via PYTHONPATH) provides `unifi_core` and the fixture distribution.
    return subprocess.run(
        [sys.executable, "-S", "-c", script],
        env={"PYTHONPATH": str(site)},
        capture_output=True,
        text=True,
        check=False,
    )


def _walk(site: Path) -> subprocess.CompletedProcess[str]:
    return _run_script(_module().walk_imports_script("fixturepkg", "fixturepkg"), site)


def _scan(site: Path) -> subprocess.CompletedProcess[str]:
    return _run_script(_module().upstream_api_scan_script("fixturepkg", "fixturepkg"), site)


def _namespace_fixture(tmp_path: Path, tool_source: str) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    _install_fixture(
        site,
        {
            **UPSTREAM_STUB,
            "fixturepkg/__init__.py": "",
            # `tools` has no __init__.py, exactly like unifi_network_mcp/tools.
            "fixturepkg/tools/clients.py": tool_source,
        },
    )
    return site


def test_pkgutil_walk_skips_namespace_subpackage_modules(tmp_path: Path) -> None:
    """The control for the regression below: why the old walk could never see the module."""
    site = _namespace_fixture(tmp_path, "x = 1\n")

    result = _run_script(
        "import pkgutil, fixturepkg\n"
        "print([m.name for m in pkgutil.walk_packages(fixturepkg.__path__, 'fixturepkg.')])\n",
        site,
    )

    assert result.returncode == 0, result.stderr
    assert "fixturepkg.tools.clients" not in result.stdout


def test_walk_imports_fails_on_symbol_missing_from_upstream_in_namespace_subpackage(tmp_path: Path) -> None:
    site = _namespace_fixture(tmp_path, "from unifi_core.auth import new_helper\n")

    result = _walk(site)

    assert result.returncode == 1
    assert "fixturepkg.tools.clients" in result.stdout
    assert "new_helper" in result.stdout


def test_walk_imports_passes_when_namespace_subpackage_symbols_exist(tmp_path: Path) -> None:
    site = _namespace_fixture(tmp_path, "from unifi_core.auth import old_helper\n")

    result = _walk(site)

    assert result.returncode == 0, result.stdout
    assert "imported 2 modules of fixturepkg" in result.stdout


def test_walk_imports_still_reports_undeclared_dependencies(tmp_path: Path) -> None:
    site = _namespace_fixture(tmp_path, "import undeclared_third_party\n")

    result = _walk(site)

    assert result.returncode == 1
    assert "fixturepkg.tools.clients -> missing dependency: undeclared_third_party" in result.stdout


def test_walk_imports_ignores_non_import_errors_at_import_time(tmp_path: Path) -> None:
    site = _namespace_fixture(tmp_path, "raise RuntimeError('needs a live controller')\n")

    assert _walk(site).returncode == 0


def test_walk_imports_fails_when_the_distribution_ships_no_modules(tmp_path: Path) -> None:
    site = tmp_path / "site"
    site.mkdir()
    _install_fixture(site, {**UPSTREAM_STUB, "otherpkg/__init__.py": ""})

    result = _walk(site)

    assert result.returncode == 1
    assert "no modules of fixturepkg found" in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        "import unifi_core.auth as auth\nauth.new_helper()\n",
        "import unifi_core.auth\nunifi_core.auth.new_helper()\n",
        "from unifi_core import auth\nauth.new_helper()\n",
        "from unifi_core.auth import Client\nClient.new_method\n",
    ],
)
def test_upstream_scan_fails_on_attribute_missing_from_upstream(tmp_path: Path, source: str) -> None:
    site = _namespace_fixture(tmp_path, source)

    result = _scan(site)

    assert result.returncode == 1
    assert "fixturepkg/tools/clients.py:" in result.stdout
    assert "not provided by the installed upstream" in result.stdout


@pytest.mark.parametrize(
    "source",
    [
        "import unifi_core.auth as auth\nauth.old_helper()\n",
        "import unifi_core.auth\nunifi_core.auth.old_helper()\n",
        "from unifi_core.auth import Client\nClient.old_method\n",
        # Instances and parameters cannot be resolved statically: never a failure.
        "from unifi_core.auth import Client\nClient().whatever\n",
        "import unifi_core.auth as auth\ndef use(auth):\n    return auth.new_helper()\n",
        "import unifi_core.auth as auth\nauth = object()\nauth.new_helper\n",
    ],
)
def test_upstream_scan_passes_resolvable_and_unresolvable_uses(tmp_path: Path, source: str) -> None:
    site = _namespace_fixture(tmp_path, source)

    result = _scan(site)

    assert result.returncode == 0, result.stdout


def test_downstream_smoke_uses_the_file_list_walk(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module()
    scripts: list[str] = []
    pkg = module.Downstream(tmp_path, "unifi-network-mcp", "unifi_network_mcp.main", "unifi_network_mcp")
    monkeypatch.setattr(module, "wheel_dependency_names", lambda wheel: set())
    monkeypatch.setattr(module, "install_security_upgrade", lambda *args, **kwargs: (True, "upgraded", Path("py")))

    def fake_run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
        scripts.append(command[-1])
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_capture", fake_run_capture)

    ok, _ = module.check_downstream(pkg, tmp_path / "w.whl", tmp_path, tmp_path / "venv", ())

    assert ok is True
    assert scripts == [
        "import unifi_network_mcp.main",
        module.walk_imports_script("unifi-network-mcp", "unifi_network_mcp"),
    ]
    assert "walk_packages" not in scripts[1]


def test_floor_check_imports_every_module_and_scans_upstream_use(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module()
    commands: list[list[str]] = []
    pkg = module.Downstream(tmp_path, "unifi-protect-mcp", "unifi_protect_mcp.main", "unifi_protect_mcp")

    monkeypatch.setattr(module.venv, "create", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "core_floor_from_wheel", lambda *args: "0.4.63")

    def fake_run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(module, "run_capture", fake_run_capture)

    ok, message = module.check_core_floor_contract(
        tmp_path / "protect.whl",
        tmp_path / "venv",
        package_label="Protect",
        core_extras="protect",
        additional_targets=("unifi-mcp-shared==0.6.23",),
        pkg=pkg,
    )

    assert ok is True
    assert "unifi-core[protect]==0.4.63" in commands[0]
    assert "unifi-mcp-shared==0.6.23" in commands[0]
    assert [command[-1] for command in commands[2:]] == [
        module.walk_imports_script("unifi-protect-mcp", "unifi_protect_mcp"),
        module.upstream_api_scan_script("unifi-protect-mcp", "unifi_protect_mcp"),
    ]
    assert message == "Core floor 0.4.63: ok; ok"


def test_floor_check_without_extras_installs_bare_core(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module()
    commands: list[list[str]] = []

    monkeypatch.setattr(module.venv, "create", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "core_floor_from_wheel", lambda *args: "0.4.51")
    monkeypatch.setattr(
        module,
        "run_capture",
        lambda command: commands.append(command) or subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )

    ok, _ = module.check_core_floor_contract(
        tmp_path / "relay.whl", tmp_path / "venv", package_label="Relay", core_extras=""
    )

    assert ok is True
    assert "unifi-core==0.4.51" in commands[0]


def test_floor_check_failure_reports_script_output(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _module()
    pkg = module.Downstream(tmp_path, "unifi-protect-mcp", "unifi_protect_mcp.main", "unifi_protect_mcp")

    monkeypatch.setattr(module.venv, "create", lambda *args, **kwargs: None)
    monkeypatch.setattr(module, "core_floor_from_wheel", lambda *args: "0.4.63")

    def fake_run_capture(command: list[str]) -> subprocess.CompletedProcess[str]:
        if "walk" in command[-1] or "importlib.import_module(name)" in command[-1]:
            raise subprocess.CalledProcessError(1, command, output="  mod -> cannot import name 'x'", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_capture", fake_run_capture)

    ok, message = module.check_core_floor_contract(
        tmp_path / "protect.whl", tmp_path / "venv", package_label="Protect", core_extras="protect", pkg=pkg
    )

    assert ok is False
    assert "mod -> cannot import name 'x'" in message


def test_shared_floor_is_read_from_unconditional_requirement(tmp_path: Path) -> None:
    module = _module()

    assert module.shared_floor_from_wheel(_wheel(tmp_path, "unifi-mcp-shared>=0.6.23,<0.7")) == "0.6.23"
    assert module.shared_floor_from_wheel(_wheel(tmp_path, "unifi-core>=0.4.1")) is None


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """GitHub path filters: `*` stays inside one segment, `**` crosses segments."""
    out, index = "", 0
    while index < len(pattern):
        if pattern.startswith("**", index):
            out += ".*"
            index += 2
        elif pattern[index] == "*":
            out += "[^/]*"
            index += 1
        else:
            out += re.escape(pattern[index])
            index += 1
    return re.compile(out + "$")


def _workflow_paths() -> dict[str, list[str]]:
    workflow = yaml.safe_load(WORKFLOW.read_text())
    triggers = workflow.get("on", workflow.get(True))
    return {event: triggers[event]["paths"] for event in ("push", "pull_request")}


def test_workflow_triggers_on_every_gated_package_change() -> None:
    module = _module()
    repo = module.REPO
    packages = [path for path in module.UPSTREAM_PACKAGES.values()] + [pkg.src for pkg in module.DOWNSTREAM_PACKAGES]
    assert {path.name for path in packages} >= {"unifi-mcp-shared", "unifi-core", "unifi-mcp-relay", "network"}

    for event, patterns in _workflow_paths().items():
        matchers = [_glob_regex(pattern) for pattern in patterns]
        for package in packages:
            relative = package.relative_to(repo).as_posix()
            for changed in (f"{relative}/pyproject.toml", f"{relative}/src/some_pkg/sub/module.py"):
                assert any(matcher.match(changed) for matcher in matchers), f"{event}: {changed} does not trigger"
        for changed in ("scripts/check_pin_alignment.py", ".github/workflows/check-pin-alignment.yml"):
            assert any(matcher.match(changed) for matcher in matchers), f"{event}: {changed} does not trigger"


def test_workflow_triggers_on_force_included_api_files() -> None:
    for event, patterns in _workflow_paths().items():
        matchers = [_glob_regex(pattern) for pattern in patterns]
        for changed in ("apps/api/alembic/versions/0001_initial.py", "apps/api/alembic.ini"):
            assert any(matcher.match(changed) for matcher in matchers), f"{event}: {changed} does not trigger"


def test_workflow_push_and_pull_request_paths_match() -> None:
    paths = _workflow_paths()

    assert paths["push"] == paths["pull_request"]
