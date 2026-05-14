"""Admin UI: /admin/audit page (filters + pagination + live-tail + CSV export).

Page route is unauthenticated and returns the HTMX shell. The rows
fragment, the SSE live-tail, and the CSV export are admin-scoped (the
shell loads first and HTMX fetches data with the localStorage Bearer
attached by admin.js).
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.db.models import AuditLog
from unifi_api.routes.admin._common import render
from unifi_api.services.audit import add_audit_subscriber
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "admin"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def _row_view(r: AuditLog) -> dict[str, Any]:
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


def _build_filtered_query(
    *,
    controller: str | None,
    outcome: str | None,
    since: str | None,
    until: str | None,
    q: str | None,
):
    stmt = select(AuditLog)
    if controller:
        stmt = stmt.where(AuditLog.controller == controller)
    if outcome:
        stmt = stmt.where(AuditLog.outcome == outcome)
    if since:
        try:
            stmt = stmt.where(AuditLog.ts >= datetime.fromisoformat(since))
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid 'since' timestamp")
    if until:
        try:
            stmt = stmt.where(AuditLog.ts <= datetime.fromisoformat(until))
        except ValueError:
            raise HTTPException(status_code=400, detail="invalid 'until' timestamp")
    if q:
        stmt = stmt.where(AuditLog.target.ilike(f"%{q}%"))
    return stmt.order_by(AuditLog.ts.desc())


@router.get("/admin/audit", include_in_schema=False)
async def audit_page(request: Request):
    """Unauth HTMX shell — filters live in the page, rows arrive via _rows."""
    return render(request, "audit/list.html")


@router.get(
    "/admin/audit/_rows",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def audit_rows(
    request: Request,
    controller: str | None = Query(None),
    outcome: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    cursor: str | None = Query(None),
):
    sm = request.app.state.sessionmaker
    stmt = _build_filtered_query(
        controller=controller,
        outcome=outcome,
        since=since,
        until=until,
        q=q,
    )
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

    # Carry filter values forward in the "Load more" hx-get URL.
    filter_qs = "&".join(
        f"{k}={v}"
        for k, v in (
            ("controller", controller),
            ("outcome", outcome),
            ("since", since),
            ("until", until),
            ("q", q),
        )
        if v
    )

    return render(
        request,
        "audit/_rows.html",
        {
            "rows": [_row_view(r) for r in page],
            "next_cursor": next_cursor.encode() if next_cursor else None,
            "filter_qs": filter_qs,
            "limit": limit,
        },
    )


async def _admin_audit_event_stream(filter_fn):
    """SSE generator that emits server-rendered _row.html fragments per audit row.

    Module-level so tests can monkeypatch with a finite version. The HTML in
    each frame's data: must be on a single line — newlines in SSE data
    confuse parsers; we collapse whitespace before yielding.
    """
    queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)

    def _on_row(row: dict) -> None:
        if filter_fn is not None and not filter_fn(row):
            return
        try:
            queue.put_nowait(row)
        except asyncio.QueueFull:
            pass

    unsub = add_audit_subscriber(_on_row)
    try:
        while True:
            try:
                row = await asyncio.wait_for(queue.get(), timeout=30.0)
                html = _templates.get_template("audit/_row.html").render({"r": row})
                # Replace any newlines/whitespace with a single space so SSE
                # 'data:' line framing parses correctly.
                single = " ".join(html.split())
                yield (f"event: audit.row\nid: {row['id']}\ndata: {single}\n\n").encode()
            except asyncio.TimeoutError:
                yield b": keepalive\n\n"
    finally:
        unsub()


def _make_filter_fn(*, outcome, q):
    """Build a filter_fn closure for the live-tail subscriber."""
    if not outcome and not q:
        return None

    def _fn(row: dict) -> bool:
        if outcome and row.get("outcome") != outcome:
            return False
        if q and q.lower() not in str(row.get("target", "")).lower():
            return False
        return True

    return _fn


@router.get(
    "/admin/audit/_stream",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def audit_stream(
    request: Request,
    outcome: str | None = Query(None),
    q: str | None = Query(None),
):
    return StreamingResponse(
        _admin_audit_event_stream(_make_filter_fn(outcome=outcome, q=q)),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get(
    "/admin/audit/export.csv",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def audit_export_csv(
    request: Request,
    controller: str | None = Query(None),
    outcome: str | None = Query(None),
    since: str | None = Query(None),
    until: str | None = Query(None),
    q: str | None = Query(None),
):
    sm = request.app.state.sessionmaker
    stmt = _build_filtered_query(
        controller=controller,
        outcome=outcome,
        since=since,
        until=until,
        q=q,
    )
    async with sm() as session:
        rows = (await session.execute(stmt)).scalars().all()

    def _generate():
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            [
                "id",
                "ts",
                "key_id_prefix",
                "controller",
                "target",
                "outcome",
                "error_kind",
                "detail",
            ]
        )
        yield buf.getvalue()
        for r in rows:
            buf.seek(0)
            buf.truncate()
            writer.writerow(
                [
                    r.id,
                    r.ts.isoformat(),
                    r.key_id_prefix,
                    r.controller or "",
                    r.target,
                    r.outcome,
                    r.error_kind or "",
                    r.detail or "",
                ]
            )
            yield buf.getvalue()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": 'attachment; filename="audit.csv"',
        },
    )
