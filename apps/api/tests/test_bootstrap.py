"""First-run admin-key bootstrap test.

The first-migrate case runs the real console script in a subprocess. The
second-migrate case starts from the already-migrated template (itself a real
first ``migrate``, asserted to succeed) and runs ``migrate`` again in-process.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from unifi_api.cli import app

_KEY = re.compile(r"unifi_(live|test)_[A-Z2-7]{22}")


def _run_migrate(cfg_path: Path, db_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["UNIFI_API_DB_KEY"] = "test-passphrase"
    env["UNIFI_API_DB_PATH"] = str(db_path)
    return subprocess.run(
        ["uv", "run", "--package", "unifi-api-server", "unifi-api-server", "migrate", "--config-path", str(cfg_path)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_first_migrate_emits_admin_key(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"db:\n  path: {db_path}\n")
    r = _run_migrate(cfg_path, db_path)
    assert r.returncode == 0, f"migrate failed: stdout={r.stdout!r} stderr={r.stderr!r}"
    combined = r.stdout + r.stderr
    assert _KEY.search(combined), f"expected admin key in output: {combined!r}"


def test_second_migrate_does_not_emit_new_key(tmp_path: Path, migrated_state_dir, monkeypatch) -> None:
    template, first_output = migrated_state_dir
    # The shared template is a real first migrate; it must have succeeded.
    assert _KEY.search(first_output)
    db_path = tmp_path / "state.db"
    for item in template.glob("state.db*"):
        shutil.copy2(item, tmp_path / item.name)
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"db:\n  path: {db_path}\n")
    monkeypatch.setenv("UNIFI_API_DB_KEY", "test-passphrase")
    monkeypatch.setenv("UNIFI_API_DB_PATH", str(db_path))

    r2 = CliRunner().invoke(app, ["migrate", "--config-path", str(cfg_path)])
    assert r2.exit_code == 0
    assert not _KEY.search(r2.output), f"second migrate must not emit a new admin key: {r2.output!r}"
