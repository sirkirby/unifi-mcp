"""Controllers CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.config import ApiConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.services.controllers import (
    ControllerNotFound,
    CreateControllerPayload,
    create_controller,
    delete_controller,
    get_controller,
    list_controllers,
    update_controller,
)

router = APIRouter()


class ControllerIn(BaseModel):
    name: str
    base_url: str
    username: str
    password: str
    api_token: str | None = None
    product_kinds: list[str]
    verify_tls: bool = True
    is_default: bool = False


class ControllerPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    product_kinds: list[str] | None = None
    verify_tls: bool | None = None
    is_default: bool | None = None
    username: str | None = None
    password: str | None = None
    api_token: str | None = None


class ControllerOut(BaseModel):
    id: str
    name: str
    base_url: str
    product_kinds: list[str]
    verify_tls: bool
    is_default: bool
    created_at: str
    updated_at: str


def _row_to_out(row) -> ControllerOut:
    return ControllerOut(
        id=row.id,
        name=row.name,
        base_url=row.base_url,
        product_kinds=[p for p in row.product_kinds.split(",") if p],
        verify_tls=row.verify_tls,
        is_default=row.is_default,
        created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


def _cipher() -> ColumnCipher:
    return ColumnCipher(derive_key(ApiConfig.read_db_key()))


@router.post(
    "/controllers",
    status_code=status.HTTP_201_CREATED,
    response_model=ControllerOut,
    dependencies=[Depends(require_scope(Scope.WRITE))],
)
async def post_controller(request: Request, body: ControllerIn) -> ControllerOut:
    sm = request.app.state.sessionmaker
    cipher = _cipher()
    async with sm() as session:
        row = await create_controller(session, cipher, CreateControllerPayload(**body.model_dump()))
        await session.commit()
        return _row_to_out(row)


@router.get(
    "/controllers",
    response_model=list[ControllerOut],
    dependencies=[Depends(require_scope(Scope.READ))],
)
async def list_endpoint(request: Request) -> list[ControllerOut]:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        rows = await list_controllers(session)
        return [_row_to_out(r) for r in rows]


@router.get(
    "/controllers/{cid}",
    response_model=ControllerOut,
    dependencies=[Depends(require_scope(Scope.READ))],
)
async def get_endpoint(request: Request, cid: str) -> ControllerOut:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        try:
            return _row_to_out(await get_controller(session, cid))
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")


@router.patch(
    "/controllers/{cid}",
    response_model=ControllerOut,
    dependencies=[Depends(require_scope(Scope.WRITE))],
)
async def patch_endpoint(request: Request, cid: str, body: ControllerPatch) -> ControllerOut:
    sm = request.app.state.sessionmaker
    cipher = _cipher()
    async with sm() as session:
        try:
            row = await update_controller(session, cipher, cid, **body.model_dump(exclude_unset=True))
            await session.commit()
            await request.app.state.manager_factory.invalidate_controller(cid)
            request.app.state.capability_cache.invalidate(cid)
            return _row_to_out(row)
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")


@router.delete(
    "/controllers/{cid}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def delete_endpoint(request: Request, cid: str) -> None:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        try:
            await delete_controller(session, cid)
            await session.commit()
            await request.app.state.manager_factory.invalidate_controller(cid)
            request.app.state.capability_cache.invalidate(cid)
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")


@router.get(
    "/controllers/{cid}/capabilities",
    dependencies=[Depends(require_scope(Scope.READ))],
)
async def capabilities_endpoint(request: Request, cid: str, refresh: bool = False) -> dict:
    cache = request.app.state.capability_cache
    if not refresh:
        hit = cache.get(cid)
        if hit is not None:
            return hit
    sm = request.app.state.sessionmaker
    async with sm() as session:
        try:
            controller = await get_controller(session, cid)
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")
    from unifi_api.services.controllers import probe_capabilities

    payload = await probe_capabilities(controller)
    cache.put(cid, payload)
    return payload


@router.post(
    "/controllers/{cid}/probe",
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def probe_endpoint(request: Request, cid: str) -> dict:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        try:
            await get_controller(session, cid)
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")
    return await request.app.state.manager_factory.probe_controller(cid)
