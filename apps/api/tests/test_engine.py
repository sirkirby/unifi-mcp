"""Plain async engine + session factory tests."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text
from unifi_api.db.engine import create_engine
from unifi_api.db.session import get_sessionmaker


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["state%20literal.db", "state%2Fliteral.db", "state?mode=ro.db"])
@pytest.mark.parametrize("as_string", [False, True])
async def test_engine_opens_the_literal_existing_database(tmp_path: Path, filename: str, as_string: bool) -> None:
    db_path = tmp_path / filename
    with sqlite3.connect(db_path) as connection:
        connection.execute("CREATE TABLE marker (value TEXT)")
        connection.execute("INSERT INTO marker VALUES ('existing database')")

    engine = create_engine(str(db_path) if as_string else db_path)
    try:
        async with engine.connect() as connection:
            assert (await connection.execute(text("SELECT value FROM marker"))).scalar_one() == "existing database"
    finally:
        await engine.dispose()
    assert set(tmp_path.iterdir()) == {db_path}


@pytest.mark.asyncio
async def test_engine_creates_db(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    engine = create_engine(db_path)
    async with engine.connect() as conn:
        await conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO t (id) VALUES (1)"))
        await conn.commit()
    await engine.dispose()
    assert db_path.exists()


@pytest.mark.asyncio
async def test_engine_creates_parent_dirs(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "dir" / "state.db"
    engine = create_engine(db_path)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await engine.dispose()
    assert db_path.parent.is_dir()


@pytest.mark.asyncio
async def test_session_factory_yields_async_session(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "state.db")
    sm = get_sessionmaker(engine)
    async with sm() as session:
        result = await session.execute(text("SELECT 1"))
        assert result.scalar() == 1
    await engine.dispose()
