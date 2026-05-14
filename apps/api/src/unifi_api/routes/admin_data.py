"""Admin-scoped data endpoints: diagnostics, logs, settings.

These power the /admin/ UI but are also useful for programmatic access.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.services.diagnostics import collect_diagnostics

router = APIRouter()


@router.get(
    "/diagnostics",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def get_diagnostics(request: Request) -> dict:
    return await collect_diagnostics(
        sessionmaker=request.app.state.sessionmaker,
        db_path=request.app.state.db_path,
        capability_cache=request.app.state.capability_cache,
        log_path=request.app.state.log_file_path,
        version=request.app.state.api_version,
        started_at=request.app.state.started_at,
    )


@router.get(
    "/logs",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def get_logs(
    request: Request,
    level: str | None = Query(None),
    logger: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
) -> dict:
    reader = request.app.state.log_reader
    return {
        "items": reader.tail(limit=limit, level=level, logger=logger, q=q),
        "file_size_bytes": reader.size_bytes,
    }


class SettingsBody(BaseModel):
    settings: dict[str, str]


@router.get(
    "/settings",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def get_settings(request: Request) -> dict:
    svc = request.app.state.settings_service
    return {"settings": await svc.get_all()}


@router.put(
    "/settings",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def put_settings(request: Request, body: SettingsBody) -> dict:
    svc = request.app.state.settings_service
    for k, v in body.settings.items():
        await svc.set_str(k, v)
    return {"settings": await svc.get_all()}
