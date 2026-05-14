"""Model creation + insert/query smoke tests."""

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from unifi_api.db.engine import create_engine
from unifi_api.db.models import ApiKey, Base
from unifi_api.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_create_all_tables(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_api_key_insert_and_query(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    async with sm() as session:
        key = ApiKey(
            id=str(uuid.uuid4()),
            prefix="unifi_live_abcd",
            hash="$argon2id$...",
            scopes="read,write",
            name="test-key",
            created_at=datetime.now(timezone.utc),
        )
        session.add(key)
        await session.commit()
        rows = (await session.execute(select(ApiKey))).scalars().all()
        assert len(rows) == 1
        assert rows[0].name == "test-key"
    await engine.dispose()
