"""ADMIN-only account connection management; never implicitly probe the cloud."""

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate, SiteManagerConnectionPatch

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.services.sitemanager_management import manage_connection

router = APIRouter(
    prefix="/sitemanager/connection",
    tags=["Site Manager connection"],
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)


class SiteManagerConnectionOut(BaseModel):
    id: str
    name: str
    key_configured: bool
    revision: int
    created_at: str
    updated_at: str


class SiteManagerProbeOut(BaseModel):
    ok: bool
    latency_ms: int
    error_kind: str | None
    checked_at: str
    message: str | None = None


async def manage(request: Request, operation: str, payload=None):
    result = await manage_connection(
        request.app.state.sessionmaker,
        request.app.state.cipher,
        request.app.state.sitemanager_factory,
        operation,
        payload=payload,
        actor=request.state.api_key_prefix,
    )
    return result


@router.post("", status_code=201, response_model=SiteManagerConnectionOut)
async def create(request: Request, body: SiteManagerConnectionCreate):
    return (await manage(request, "create", body)).data


@router.get("", response_model=SiteManagerConnectionOut)
async def get(request: Request):
    return (await manage(request, "get")).data


@router.patch("", response_model=SiteManagerConnectionOut)
async def patch(request: Request, body: SiteManagerConnectionPatch):
    return (await manage(request, "update", body)).data


@router.delete("", status_code=204)
async def delete(request: Request):
    await manage(request, "delete")
    return Response(status_code=204)


@router.post("/probe", response_model=SiteManagerProbeOut)
async def probe(request: Request):
    result = await manage(request, "probe")
    return JSONResponse(result.data, status_code=result.status)
