"""Audit log pruning — by age and/or by row count."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from unifi_api.db.models import AuditLog


async def prune_audit(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    max_age_days: int,
    max_rows: int,
) -> dict:
    """Delete audit_log rows older than ``max_age_days``; then enforce ``max_rows``
    by deleting the oldest-first remaining rows beyond the cap.

    Returns:
        ``{"pruned": <int>, "current_count": <int>}`` — total rows deleted in this
        invocation (age + row-cap combined), and the row count after pruning.
    """

    pruned = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    async with sessionmaker() as session:
        # Phase 1 — age-based prune
        age_result = await session.execute(delete(AuditLog).where(AuditLog.ts < cutoff))
        pruned += age_result.rowcount or 0

        # Phase 2 — row-cap prune (oldest-first)
        current = (await session.execute(select(func.count(AuditLog.id)))).scalar_one()
        if current > max_rows:
            excess = current - max_rows
            ids_to_delete = (
                (await session.execute(select(AuditLog.id).order_by(AuditLog.ts.asc()).limit(excess))).scalars().all()
            )
            if ids_to_delete:
                cap_result = await session.execute(delete(AuditLog).where(AuditLog.id.in_(ids_to_delete)))
                pruned += cap_result.rowcount or 0

        await session.commit()

        current_count = (await session.execute(select(func.count(AuditLog.id)))).scalar_one()

    return {"pruned": pruned, "current_count": current_count}
