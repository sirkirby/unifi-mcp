"""Audit log writer tests."""

from pathlib import Path

import pytest
from sqlalchemy import select
from unifi_api.db.engine import create_engine
from unifi_api.db.models import AuditLog, Base
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.audit import write_audit


@pytest.mark.asyncio
async def test_write_audit_inserts_row(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    async with sm() as session:
        await write_audit(
            session, key_id_prefix="unifi_live_AAAA", controller="cid1", target="unifi_list_clients", outcome="success"
        )
        await session.commit()
    async with sm() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
        assert len(rows) == 1
        assert rows[0].outcome == "success"
        assert rows[0].target == "unifi_list_clients"
    await engine.dispose()


@pytest.mark.asyncio
async def test_write_audit_with_error_kind(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = get_sessionmaker(engine)
    async with sm() as session:
        await write_audit(
            session,
            key_id_prefix="unifi_live_AAAA",
            controller=None,
            target="POST /v1/foo",
            outcome="denied",
            error_kind="insufficient_scope",
            detail="needed admin",
        )
        await session.commit()
    async with sm() as session:
        row = (await session.execute(select(AuditLog))).scalar_one()
        assert row.error_kind == "insufficient_scope"
        assert row.detail == "needed admin"
    await engine.dispose()
