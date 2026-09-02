from __future__ import annotations

import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

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
            "cryptography>=50.0.0",
            "PyJWT>=2.13.0",
            "python-multipart>=0.0.31",
            "starlette>=1.3.1",
            "click>=8.3.3",
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
            "cryptography>=49.0.0",
            "PyJWT>=2.13.0",
            "python-multipart>=0.0.31",
            "starlette>=1.3.1",
        ],
    )

    ok, message = module.check_security_floors("unifi-api-server", wheel)

    assert ok is False
    assert "cryptography>=50.0.0" in message
    assert "click>=8.3.3" in message


def test_security_floor_check_honors_extra_markers_and_higher_floors(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel_with_requirements(tmp_path, ['PyJWT>=2.14.0; extra == "protect"'])

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
            "cryptography>=50.0.0rc1",
            "PyJWT>=2.13.0",
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
