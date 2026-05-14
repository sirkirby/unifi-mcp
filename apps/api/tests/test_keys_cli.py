"""CLI keys subcommand tests (subprocess)."""

import os
import re
import subprocess
from pathlib import Path


def _run_cli(*args: str, db_path: Path) -> subprocess.CompletedProcess:
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


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "state.db"
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(f"db:\n  path: {db_path}\n")
    r = _run_cli("migrate", "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode == 0, f"migrate failed: {r.stderr}"
    return db_path, cfg_path


def test_keys_create_emits_plaintext_once(tmp_path: Path) -> None:
    db_path, cfg_path = _bootstrap(tmp_path)
    r = _run_cli("keys", "create", "ci-test", "--scopes", "read,write", "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode == 0, f"create failed: {r.stderr}"
    combined = r.stdout + r.stderr
    assert re.search(r"unifi_(live|test)_[A-Z2-7]{22}", combined)


def test_keys_list_shows_active_and_no_plaintext(tmp_path: Path) -> None:
    db_path, cfg_path = _bootstrap(tmp_path)
    _run_cli("keys", "create", "k1", "--scopes", "read", "--config-path", str(cfg_path), db_path=db_path)
    r = _run_cli("keys", "list", "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode == 0
    out = r.stdout
    assert "k1" in out
    assert "read" in out
    assert "(active)" in out or "active" in out
    # Plaintext key body must NOT appear
    assert not re.search(r"unifi_(live|test)_[A-Z2-7]{22}", out)


def test_keys_revoke_marks_revoked(tmp_path: Path) -> None:
    db_path, cfg_path = _bootstrap(tmp_path)
    create = _run_cli("keys", "create", "k1", "--scopes", "read", "--config-path", str(cfg_path), db_path=db_path)
    m = re.search(r"unifi_(live|test)_[A-Z2-7]{22}", create.stdout + create.stderr)
    assert m, "no key emitted"
    plaintext = m.group(0)
    prefix = plaintext[:15]

    r = _run_cli("keys", "revoke", prefix, "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode == 0, f"revoke failed: {r.stderr}"

    listed = _run_cli("keys", "list", "--config-path", str(cfg_path), db_path=db_path)
    assert "(revoked)" in listed.stdout


def test_keys_revoke_unknown_prefix_errors(tmp_path: Path) -> None:
    db_path, cfg_path = _bootstrap(tmp_path)
    r = _run_cli("keys", "revoke", "unifi_live_NOPENOPENOPENOPE", "--config-path", str(cfg_path), db_path=db_path)
    assert r.returncode != 0
