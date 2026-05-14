"""Admin UI: /admin/logs page (filters + pagination + live-tail SSE).

Page route is unauthenticated and returns the HTMX shell. The rows fragment
and the SSE live-tail are admin-scoped (the shell loads first and HTMX
fetches data with the localStorage Bearer attached by admin.js).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.admin._common import render

router = APIRouter()


_TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "templates" / "admin"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


@router.get("/admin/logs", include_in_schema=False)
async def logs_page(request: Request):
    """Unauth HTMX shell — filters live in the page, rows arrive via _rows."""
    return render(request, "logs/list.html")


@router.get(
    "/admin/logs/_rows",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def logs_rows(
    request: Request,
    level: str | None = Query(None),
    logger: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    reader = request.app.state.log_reader
    # `tail` returns most-recent-first; over-fetch by `offset+limit`, then slice.
    rows = reader.tail(
        limit=offset + limit,
        level=level or None,
        logger=logger or None,
        q=q or None,
    )
    page = rows[offset : offset + limit]
    has_more = len(rows) > offset + limit

    filter_qs = "&".join(
        f"{k}={v}"
        for k, v in (
            ("level", level),
            ("logger", logger),
            ("q", q),
        )
        if v
    )

    return render(
        request,
        "logs/_rows.html",
        {
            "rows": page,
            "next_offset": offset + limit if has_more else None,
            "filter_qs": filter_qs,
            "limit": limit,
        },
    )


async def _admin_logs_event_stream(log_path: Path, filter_fn):
    """SSE generator that emits server-rendered _row.html fragments per new
    log line as the file grows. Module-level so tests can monkeypatch.

    Implementation: poll os.stat().st_size every 1s; on growth, read new bytes,
    parse JSON-per-line, apply filter_fn, render server-side, emit. On rotation
    (size shrinks below previous offset), reset the offset to 0.
    """
    log_path = Path(log_path)

    # Start at end-of-file so we don't replay history.
    try:
        offset = log_path.stat().st_size
    except FileNotFoundError:
        offset = 0

    while True:
        try:
            size = log_path.stat().st_size
        except FileNotFoundError:
            size = 0

        if size < offset:
            # File rotated — start from beginning.
            offset = 0

        if size > offset:
            try:
                with log_path.open("rb") as f:
                    f.seek(offset)
                    new_bytes = f.read(size - offset)
                offset = size
            except FileNotFoundError:
                offset = 0
                await asyncio.sleep(1.0)
                continue

            for raw_line in new_bytes.split(b"\n"):
                if not raw_line.strip():
                    continue
                try:
                    payload = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if filter_fn is not None and not filter_fn(payload):
                    continue
                html = _templates.get_template("logs/_row.html").render({"r": payload})
                single = " ".join(html.split())
                yield f"event: log.row\ndata: {single}\n\n".encode()

        # Heartbeat keepalive every iteration so proxies don't kill the connection.
        yield b": keepalive\n\n"
        await asyncio.sleep(1.0)


def _make_filter_fn(*, level, logger, q):
    """Build a filter_fn closure for the live-tail line filter."""
    if not (level or logger or q):
        return None
    level_norm = level.upper() if level else None

    def _fn(payload: dict) -> bool:
        if level_norm and str(payload.get("level", "")).upper() != level_norm:
            return False
        if logger and payload.get("logger") != logger:
            return False
        if q and q.lower() not in str(payload).lower():
            return False
        return True

    return _fn


@router.get(
    "/admin/logs/_stream",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def logs_stream(
    request: Request,
    level: str | None = Query(None),
    logger: str | None = Query(None),
    q: str | None = Query(None),
):
    log_path = request.app.state.log_file_path or Path("/dev/null")
    return StreamingResponse(
        _admin_logs_event_stream(
            log_path,
            _make_filter_fn(level=level, logger=logger, q=q),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
