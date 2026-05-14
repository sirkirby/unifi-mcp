"""Health endpoints.

GET /health         - liveness, unauthenticated
GET /health/ready   - readiness, admin-scoped (DB connectivity check)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope

router = APIRouter()


@router.get("/health")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready", dependencies=[Depends(require_scope(Scope.ADMIN))])
async def readiness(request: Request) -> dict[str, str]:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        await session.execute(text("SELECT 1"))
    return {"status": "ready", "db": "ok"}
