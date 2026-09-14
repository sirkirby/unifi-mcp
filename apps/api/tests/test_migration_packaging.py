"""Installed-wheel migration contracts."""

from __future__ import annotations

import os
import site
import subprocess
import venv
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_built_wheel_migrates_outside_source_tree(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--package", "unifi-api-server", "--wheel", "--out-dir", str(tmp_path)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(tmp_path.glob("unifi_api_server-*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert "unifi_api/alembic.ini" in archive.namelist()
        assert any(name.startswith("unifi_api/alembic/versions/") for name in archive.namelist())

    venv_dir = tmp_path / "venv"
    venv.EnvBuilder().create(venv_dir)
    python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site_packages = (
        venv_dir / "Lib/site-packages" if os.name == "nt" else next((venv_dir / "lib").glob("python*/site-packages"))
    )
    dependency_paths = [site.getsitepackages()[0], str(REPO_ROOT / "packages/unifi-core/src")]
    (site_packages / "test-dependencies.pth").write_text("\n".join(dependency_paths) + "\n", encoding="utf-8")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )
    (site_packages / "unifi_api/alembic.py").write_text(
        'raise RuntimeError("working-directory alembic module executed")\n', encoding="utf-8"
    )

    db_path = tmp_path / "state.db"
    config_path = tmp_path / "config.yaml"
    config_path.write_text("db:\n  path: state.db\n", encoding="utf-8")
    (tmp_path / "alembic.py").write_text(
        'raise RuntimeError("caller-controlled alembic module executed")\n', encoding="utf-8"
    )
    probe = """
import sys
from pathlib import Path
from typer.testing import CliRunner

import unifi_api
from unifi_api.cli import app

assert Path(unifi_api.__file__).is_relative_to(Path(sys.argv[1]))
result = CliRunner().invoke(app, ["migrate", "--config-path", sys.argv[2]])
if result.exit_code != 0:
    raise RuntimeError(f"installed-wheel migrate failed: {result.output!r}") from result.exception
"""
    env = dict(os.environ)
    env["UNIFI_API_DB_KEY"] = "test-passphrase"
    env["PATH"] = os.defpath
    env["PYTHONPATH"] = str(tmp_path)
    subprocess.run(
        [python, "-I", "-c", probe, str(venv_dir), str(config_path)],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert db_path.is_file()
