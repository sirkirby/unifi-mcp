from __future__ import annotations

import importlib.util
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


def _wheel(tmp_path: Path, requirement: str | None) -> Path:
    wheel = tmp_path / "unifi_api_server-1.0.0-py3-none-any.whl"
    lines = ["Metadata-Version: 2.4", "Name: unifi-api-server", "Version: 1.0.0"]
    if requirement is not None:
        lines.append(f"Requires-Dist: {requirement}")
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("unifi_api_server-1.0.0.dist-info/METADATA", "\n".join(lines) + "\n")
    return wheel


def test_extracts_api_core_lower_bound_from_wheel_metadata(tmp_path: Path) -> None:
    module = _module()
    wheel = _wheel(tmp_path, "unifi-core[access,network,protect]>=0.4.23,<0.5")

    assert module.api_core_floor_from_wheel(wheel) == "0.4.23"


@pytest.mark.parametrize("requirement", [None, "unifi-core<0.5"])
def test_missing_core_floor_fails_closed(tmp_path: Path, requirement: str | None) -> None:
    module = _module()
    wheel = _wheel(tmp_path, requirement)

    with pytest.raises(RuntimeError):
        module.api_core_floor_from_wheel(wheel)
