"""Audit log writer + subscriber fan-out.

Synchronous insert in the request transaction. Failures of the audit insert
itself propagate to the caller (we don't silently drop audit records).

After a successful insert, fan out the row dict to any registered subscribers
(SSE streams). Subscriber callbacks must not raise — exceptions are caught
per-callback so one failing subscriber doesn't break others.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from unifi_api.db.models import AuditLog

_log = logging.getLogger("unifi-api.audit")
_audit_subscribers: list[Callable[[dict], None]] = []


def add_audit_subscriber(cb: Callable[[dict], None]) -> Callable[[], None]:
    """Register a subscriber callback. Returns an unsubscribe callable."""
    _audit_subscribers.append(cb)

    def _unsub() -> None:
        try:
            _audit_subscribers.remove(cb)
        except ValueError:
            pass

    return _unsub


def _row_to_dict(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "ts": row.ts.isoformat(),
        "key_id_prefix": row.key_id_prefix,
        "controller": row.controller,
        "target": row.target,
        "outcome": row.outcome,
        "error_kind": row.error_kind,
        "detail": row.detail,
    }


async def write_audit(
    session: AsyncSession,
    *,
    key_id_prefix: str,
    controller: str | None,
    target: str,
    outcome: str,
    error_kind: str | None = None,
    detail: str | None = None,
) -> None:
    row = AuditLog(
        ts=datetime.now(timezone.utc),
        key_id_prefix=key_id_prefix,
        controller=controller,
        target=target,
        outcome=outcome,
        error_kind=error_kind,
        detail=detail,
    )
    session.add(row)
    await session.flush()  # populate row.id

    # Fan out to subscribers — protect each callback with try/except.
    payload = _row_to_dict(row)
    for cb in list(_audit_subscribers):
        try:
            cb(payload)
        except Exception:
            _log.warning("audit subscriber raised", exc_info=True)
