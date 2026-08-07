"""Standalone wheel contracts for the generated API action catalog."""

from __future__ import annotations

import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_api_declares_only_core_as_an_internal_runtime_dependency() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "apps/api/pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]
    internal = [dependency for dependency in dependencies if dependency.startswith("unifi-")]

    assert internal == ["unifi-core[network,protect,access]>=0.4.22,<0.5"]


def test_built_wheel_contains_and_loads_catalog_without_sibling_apps(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--package", "unifi-api-server", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("unifi_api_server-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert "unifi_api/action_catalog.json" in archive.namelist()
        unpacked = tmp_path / "wheel"
        archive.extractall(unpacked)

    probe = """
import importlib.util
import sys
sys.path.insert(0, sys.argv[1])
from unifi_api.services.manifest import ManifestRegistry
registry = ManifestRegistry.load()
assert len(registry) == 266
assert registry.has('unifi_list_clients')
assert registry.has('protect_list_cameras')
assert registry.has('access_list_doors')
for package in ('unifi_network_mcp', 'unifi_protect_mcp', 'unifi_access_mcp'):
    assert importlib.util.find_spec(package) is None, package
"""
    subprocess.run(
        [sys._base_executable, "-I", "-c", probe, str(unpacked)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
