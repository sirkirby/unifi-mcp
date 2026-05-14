"""Alembic up/down smoke."""

import os
import subprocess
from pathlib import Path


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


def test_migration_up_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "migrate.db"
    result = _run_alembic("-x", f"db_path={db_path}", "upgrade", "head", db_path=db_path)
    assert result.returncode == 0, f"alembic upgrade failed: {result.stderr}"

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
