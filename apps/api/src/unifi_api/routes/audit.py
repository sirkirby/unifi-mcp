"""Audit log query route — admin-scoped, paginated, filterable."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.db.models import AuditLog
from unifi_api.services.audit import add_audit_subscriber
from unifi_api.services.audit_pruner import prune_audit
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _row_to_dict(r: AuditLog) -> dict:
    return {
        "id": r.id,
        "ts": r.ts.isoformat(),
        "key_id_prefix": r.key_id_prefix,
        "controller": r.controller,
        "target": r.target,
        "outcome": r.outcome,
        "error_kind": r.error_kind,
        "detail": r.detail,
    }


def _audit_key(r: AuditLog) -> tuple:
    return (int(r.ts.timestamp() * 1000), str(r.id))


@router.get(
    "/audit",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def list_audit(
    request: Request,
    controller: str | None = Query(None),
    outcome: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
) -> dict:
    sm = request.app.state.sessionmaker

    stmt = select(AuditLog)
    if controller is not None:
        stmt = stmt.where(AuditLog.controller == controller)
    if outcome is not None:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if since is not None:
        try:
            stmt = stmt.where(AuditLog.ts >= datetime.fromisoformat(since))
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid 'since' timestamp")
    if until is not None:
        try:
            stmt = stmt.where(AuditLog.ts <= datetime.fromisoformat(until))
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid 'until' timestamp")
    if q is not None:
        stmt = stmt.where(AuditLog.target.ilike(f"%{q}%"))
    stmt = stmt.order_by(AuditLog.ts.desc())

    async with sm() as session:
        rows = (await session.execute(stmt)).scalars().all()

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(rows),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_audit_key,
    )

    return {
        "items": [_row_to_dict(r) for r in page],
        "next_cursor": next_cursor.encode() if next_cursor else None,
    }


@router.post(
    "/audit/prune",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def prune_endpoint(request: Request) -> dict:
    sm = request.app.state.sessionmaker
    svc = request.app.state.settings_service
    max_age = await svc.get_int("audit.retention.max_age_days", default=90)
    max_rows = await svc.get_int("audit.retention.max_rows", default=1_000_000)
    return await prune_audit(sm, max_age_days=max_age, max_rows=max_rows)


async def _audit_event_stream():
    """Async generator that yields SSE frames for audit rows.

    Module-level (not nested inside the route) so tests can monkeypatch it
    with a finite version that doesn't loop forever.
    """
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)

    def _on_row(row: dict) -> None:
        try:
            queue.put_nowait(row)
        except asyncio.QueueFull:
            pass  # drop newest if backpressured

    unsub = add_audit_subscriber(_on_row)
    try:
        while True:
            try:
                row = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield (f"event: audit.row\nid: {row['id']}\ndata: {json.dumps(row, default=str)}\n\n").encode()
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
    finally:
        unsub()


@router.get(
    "/streams/audit",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def stream_audit(request: Request) -> StreamingResponse:
    """SSE stream of audit rows. One frame per row inserted via write_audit."""
    return StreamingResponse(
        _audit_event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
