"""CLI keys subcommand tests.

One case runs the real ``unifi-api-server`` console script in a subprocess;
the rest call the Typer app in-process against a copy of a migrated database.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from unifi_api.cli import app

_KEY = re.compile(r"unifi_(live|test)_[A-Z2-7]{22}")


class _Result:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def state(tmp_path: Path, migrated_state_dir, monkeypatch) -> tuple[Path, Path]:
    """A fresh migrated database and config file for one test."""
    template, _ = migrated_state_dir
    db_path = tmp_path / "state.db"
    for item in template.glob("state.db*"):
        shutil.copy2(item, tmp_path / item.name)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"db:\n  path: {db_path}\n")
    monkeypatch.setenv("UNIFI_API_DB_KEY", "test-passphrase")
    monkeypatch.setenv("UNIFI_API_DB_PATH", str(db_path))
    return db_path, cfg_path


def _run_subprocess(*args: str, db_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["UNIFI_API_DB_KEY"] = "test-passphrase"
    env["UNIFI_API_DB_PATH"] = str(db_path)
    return subprocess.run(
        ["uv", "run", "--package", "unifi-api-server", "unifi-api-server", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _run_cli(*args: str, db_path: Path) -> _Result:
    result = CliRunner().invoke(app, list(args))
    return _Result(result.exit_code, result.output, result.output)


def test_keys_create_emits_plaintext_once(state) -> None:
    # Real console script, real interpreter: the entry point the operator runs.
    db_path, cfg_path = state
    r = _run_subprocess(
        "keys", "create", "ci-test", "--scopes", "read,write", "--config-path", str(cfg_path), db_path=db_path
    )
    assert r.returncode == 0, f"create failed: {r.stderr}"
    combined = r.stdout + r.stderr
    assert _KEY.search(combined)


def test_keys_list_shows_active_and_no_plaintext(state) -> None:
    db_path, cfg_path = state
    _run_cli("keys", "create", "k1", "--scopes", "read", "--config-path", str(cfg_path), db_path=db_path)
    r = _run_cli("keys", "list", "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode == 0
    out = r.stdout
    assert "k1" in out
    assert "read" in out
    assert "(active)" in out or "active" in out
    # Plaintext key body must NOT appear
    assert not _KEY.search(out)


def test_keys_revoke_marks_revoked(state) -> None:
    db_path, cfg_path = state
    create = _run_cli("keys", "create", "k1", "--scopes", "read", "--config-path", str(cfg_path), db_path=db_path)
    m = _KEY.search(create.stdout + create.stderr)
    assert m, "no key emitted"
    plaintext = m.group(0)
    prefix = plaintext[:15]

    r = _run_cli("keys", "revoke", prefix, "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode == 0, f"revoke failed: {r.stderr}"

    listed = _run_cli("keys", "list", "--config-path", str(cfg_path), db_path=db_path)
    assert "(revoked)" in listed.stdout


def test_keys_revoke_unknown_prefix_errors(state) -> None:
    db_path, cfg_path = state
    r = _run_cli("keys", "revoke", "unifi_live_NOPENOPENOPENOPE", "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode != 0
