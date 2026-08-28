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

    # The floor version moves with routine core releases; assert the
    # dependency set and bound shape, not the exact floor.
    assert len(internal) == 1
    assert internal[0].startswith("unifi-core[network,protect,access]>=")
    assert internal[0].endswith(",<0.5")


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
import importlib.abc
import sys

blocked = ('unifi_network_mcp', 'unifi_protect_mcp', 'unifi_access_mcp')

class BlockSiblingApps(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in blocked or fullname.startswith(tuple(name + '.' for name in blocked)):
            raise ImportError(f'forbidden sibling-app import: {fullname}')
        return None

sys.path.insert(0, sys.argv[1])
sys.meta_path.insert(0, BlockSiblingApps())
from unifi_api.services.manifest import ManifestRegistry
registry = ManifestRegistry.load()
assert len(registry) == 271
assert registry.has('unifi_list_clients')
assert registry.has('protect_list_cameras')
assert registry.has('access_list_doors')
from unifi_api.server import create_app
assert create_app is not None
"""
    subprocess.run(
        [sys.executable, "-I", "-c", probe, str(unpacked)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
