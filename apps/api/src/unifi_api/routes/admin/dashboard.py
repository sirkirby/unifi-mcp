"""Admin UI dashboard — server-side rendered diagnostics fragment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.admin._common import render
from unifi_api.services.diagnostics import collect_diagnostics

router = APIRouter()


@router.get("/admin/", include_in_schema=False)
async def dashboard(request: Request):
    return render(request, "dashboard.html")


@router.get(
    "/admin/_diagnostics_html",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def diagnostics_html(request: Request):
    snapshot = await collect_diagnostics(
        sessionmaker=request.app.state.sessionmaker,
        db_path=request.app.state.db_path,
        capability_cache=request.app.state.capability_cache,
        log_path=request.app.state.log_file_path,
        version=request.app.state.api_version,
        started_at=request.app.state.started_at,
    )
    return render(request, "_diagnostics_fragment.html", {"d": snapshot})
