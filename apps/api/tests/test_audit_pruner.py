"""Tests for audit_log pruning service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from unifi_api.db.engine import create_engine
from unifi_api.db.models import AuditLog, Base
from unifi_api.db.session import get_sessionmaker
from unifi_api.services.audit_pruner import prune_audit


async def _seed(sm, ts_offsets_days: list[int]) -> None:
    """Insert one AuditLog row per offset (negative = past)."""
    now = datetime.now(timezone.utc)
    async with sm() as session:
        for offset in ts_offsets_days:
            session.add(
                AuditLog(
                    ts=now + timedelta(days=offset),
                    key_id_prefix="test",
                    controller=None,
                    target="test.tool",
                    outcome="ok",
                )
            )
        await session.commit()


async def _make_sm(tmp_path: Path):
    engine = create_engine(tmp_path / "state.db")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, get_sessionmaker(engine)


@pytest.mark.asyncio
async def test_prune_by_age_removes_old_rows(tmp_path: Path) -> None:
    engine, sm = await _make_sm(tmp_path)
    try:
        await _seed(sm, [-100, -10])
        result = await prune_audit(sm, max_age_days=30, max_rows=1_000_000)
        assert result == {"pruned": 1, "current_count": 1}

        # Surviving row should be the 10-day-old one.
        async with sm() as session:
            rows = (await session.execute(select(AuditLog))).scalars().all()
        assert len(rows) == 1
        ts = rows[0].ts
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400
        assert 9 < age_days < 11
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prune_by_max_rows_keeps_newest(tmp_path: Path) -> None:
    engine, sm = await _make_sm(tmp_path)
    try:
        # 10 rows: now-9, now-8, ..., now
        await _seed(sm, list(range(-9, 1)))
        result = await prune_audit(sm, max_age_days=365, max_rows=5)
        assert result == {"pruned": 5, "current_count": 5}

        # The 5 surviving rows must be the newest ones (offsets -4..0).
        async with sm() as session:
            rows = (await session.execute(select(AuditLog).order_by(AuditLog.ts.desc()))).scalars().all()
        assert len(rows) == 5
        now = datetime.now(timezone.utc)

        def _aware(ts: datetime) -> datetime:
            return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts

        ages = sorted((now - _aware(r.ts)).total_seconds() / 86400 for r in rows)
        # Surviving offsets should be roughly 0, 1, 2, 3, 4 days old.
        for expected, actual in zip([0, 1, 2, 3, 4], ages):
            assert abs(actual - expected) < 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_prune_noop_when_under_limits(tmp_path: Path) -> None:
    engine, sm = await _make_sm(tmp_path)
    try:
        await _seed(sm, [-1, -2, -3])
        result = await prune_audit(sm, max_age_days=90, max_rows=100)
        assert result == {"pruned": 0, "current_count": 3}
    finally:
        await engine.dispose()
