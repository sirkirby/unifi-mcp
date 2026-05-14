"""AppSetting model creation + insert/query smoke tests."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from unifi_api.db.engine import create_engine
from unifi_api.db.models import AppSetting, Base
from unifi_api.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_app_setting_insert_and_query(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    async with sm() as session:
        setting = AppSetting(
            key="theme.default",
            value="auto",
            updated_at=datetime.now(timezone.utc),
        )
        session.add(setting)
        await session.commit()
        rows = (await session.execute(select(AppSetting))).scalars().all()
        assert len(rows) == 1
        assert rows[0].key == "theme.default"
        assert rows[0].value == "auto"
    await engine.dispose()
