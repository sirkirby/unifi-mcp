"""First-run admin-key bootstrap test."""

import os
import re
import subprocess
from pathlib import Path


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
    assert re.search(r"unifi_(live|test)_[A-Z2-7]{22}", combined), f"expected admin key in output: {combined!r}"


def test_second_migrate_does_not_emit_new_key(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"db:\n  path: {db_path}\n")
    r1 = _run_migrate(cfg_path, db_path)
    assert r1.returncode == 0
    r2 = _run_migrate(cfg_path, db_path)
    assert r2.returncode == 0
    combined = r2.stdout + r2.stderr
    assert not re.search(r"unifi_(live|test)_[A-Z2-7]{22}", combined), (
        f"second migrate must not emit a new admin key: {combined!r}"
    )
