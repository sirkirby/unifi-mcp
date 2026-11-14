"""Alembic up/down smoke."""

import os
import sqlite3
import subprocess
from pathlib import Path

import pytest


def _run_alembic(*args: str, db_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["UNIFI_API_DB_PATH"] = str(db_path)
    return subprocess.run(
        ["uv", "run", "--package", "unifi-api-server", "alembic", *args],
        cwd=Path(__file__).resolve().parents[1],  # apps/api
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("filename", ["migrate.db", "migrate%20literal.db"])
def test_migration_up_creates_tables(tmp_path: Path, filename: str) -> None:
    db_path = tmp_path / filename
    result = _run_alembic("-x", f"db_path={db_path}", "upgrade", "head", db_path=db_path)
    assert result.returncode == 0, f"alembic upgrade failed: {result.stderr}"
    assert db_path.is_file()
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() is not None

    import asyncio

    from sqlalchemy import text
    from unifi_api.db.engine import create_engine

    async def _check():
        engine = create_engine(db_path)
        async with engine.connect() as conn:
            tables = (await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))).scalars().all()
        await engine.dispose()
        return set(tables)

    tables = asyncio.run(_check())
    expected = {"schema_version", "api_keys", "controllers", "sessions", "audit_log", "alembic_version"}
    assert expected.issubset(tables), f"missing tables: {expected - tables}"


def test_migration_downgrade(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    _run_alembic("-x", f"db_path={db_path}", "upgrade", "head", db_path=db_path)
    result = _run_alembic("-x", f"db_path={db_path}", "downgrade", "base", db_path=db_path)
    assert result.returncode == 0


def test_upgrade_preserves_console_ciphertext_and_audit(tmp_path):
    db_path = tmp_path / "upgrade.db"
    result = _run_alembic("upgrade", "0002", db_path=db_path)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO controllers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "synthetic-console",
                "Console",
                "https://192.0.2.1",
                "network",
                b"opaque-console-ciphertext",
                1,
                0,
                "2026-01-01",
                "2026-01-01",
            ),
        )
        conn.execute(
            "INSERT INTO audit_log (ts,key_id_prefix,controller,target,outcome) VALUES (?,?,?,?,?)",
            ("2026-01-01", "(cli)", "synthetic-console", "create", "success"),
        )
    for _ in range(2):
        result = _run_alembic("upgrade", "head", db_path=db_path)
        assert result.returncode == 0, result.stderr
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT credentials_blob FROM controllers").fetchall() == [(b"opaque-console-ciphertext",)]
        assert conn.execute("SELECT controller,sitemanager_connection FROM audit_log").fetchall() == [
            ("synthetic-console", None)
        ]
        assert conn.execute("SELECT * FROM sitemanager_connections").fetchall() == []
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0003",)
    result = _run_alembic("downgrade", "0002", db_path=db_path)
    assert result.returncode == 0, result.stderr
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT credentials_blob FROM controllers").fetchone() == (b"opaque-console-ciphertext",)
        assert conn.execute("SELECT controller FROM audit_log").fetchone() == ("synthetic-console",)
        assert "sitemanager_connection" not in [r[1] for r in conn.execute("PRAGMA table_info(audit_log)")]
