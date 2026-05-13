"""Tests for shared skill script syncing."""
from pathlib import Path

from skills._build import sync_shared


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    plugins_dir = tmp_path / "plugins"
    shared_dir = tmp_path / "skills" / "_shared"
    shared_dir.mkdir(parents=True)
    (shared_dir / "config.py").write_text("# shared config\n")
    (shared_dir / "mcp_client.py").write_text("# shared client\n")
    monkeypatch.setattr(sync_shared, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sync_shared, "PLUGINS_DIR", plugins_dir)
    monkeypatch.setattr(sync_shared, "SHARED_DIR", shared_dir)
    return plugins_dir, shared_dir


def _skill_scripts_dir(plugins_dir: Path, skill_name: str) -> Path:
    scripts_dir = plugins_dir / "unifi-network" / "skills" / skill_name / "scripts"
    scripts_dir.mkdir(parents=True)
    return scripts_dir


def test_skips_script_dirs_without_python_consumers(monkeypatch, tmp_path, capsys):
    plugins_dir, _shared_dir = _patch_paths(monkeypatch, tmp_path)
    scripts_dir = _skill_scripts_dir(plugins_dir, "firewall-auditor")
    (scripts_dir / "unifi-firewall-score").write_text("#!/usr/bin/env python3\n")

    assert sync_shared.find_skill_script_dirs() == []
    assert sync_shared.sync() is True
    assert not (scripts_dir / "config.py").exists()
    assert not (scripts_dir / "mcp_client.py").exists()
    assert "No Python-backed skill scripts" in capsys.readouterr().out


def test_syncs_script_dirs_with_python_consumers(monkeypatch, tmp_path):
    plugins_dir, _shared_dir = _patch_paths(monkeypatch, tmp_path)
    scripts_dir = _skill_scripts_dir(plugins_dir, "legacy-auditor")
    (scripts_dir / "run-audit.py").write_text("from mcp_client import MCPClient\n")

    assert sync_shared.find_skill_script_dirs() == [scripts_dir]
    assert sync_shared.sync() is True
    assert (scripts_dir / "config.py").read_text() == "# shared config\n"
    assert (scripts_dir / "mcp_client.py").read_text() == "# shared client\n"
