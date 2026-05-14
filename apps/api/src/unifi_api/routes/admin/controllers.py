"""Admin UI routes for managing controllers (list / add / edit / delete + probe).

The page route is unauthenticated and returns the HTMX shell; all data
fragments and write actions are admin-scoped. This mirrors the dashboard
pattern — vanilla browser navigation never carries the localStorage Bearer,
so the shell loads first and HTMX fetches data with the Bearer attached
by admin.js. The credentials_blob column is NEVER rendered; edit forms
expose only is_set booleans per credential field. Empty form fields on
edit translate to None on the underlying update_controller call,
preserving existing credentials.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.config import ApiConfig
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import Controller
from unifi_api.routes.admin._common import render
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


def _cipher() -> ColumnCipher:
    return ColumnCipher(derive_key(ApiConfig.read_db_key()))


def _row_view(row: Controller) -> dict[str, Any]:
    """Display-safe row dict — never includes credentials_blob."""
    return {
        "id": row.id,
        "name": row.name,
        "base_url": row.base_url,
        "product_kinds": [p for p in row.product_kinds.split(",") if p],
        "verify_tls": row.verify_tls,
        "is_default": row.is_default,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _creds_is_set(row: Controller, cipher: ColumnCipher) -> dict[str, bool]:
    """Return is_set booleans for each credential field — never the values."""
    try:
        creds = json.loads(cipher.decrypt(row.credentials_blob))
    except Exception:
        return {"username": False, "password": False, "api_token": False}
    return {
        "username": bool(creds.get("username")),
        "password": bool(creds.get("password")),
        "api_token": bool(creds.get("api_token")),
    }


def _blank_to_none(value: str) -> str | None:
    """HTML form fields default to empty string; the server treats empty as 'unchanged'."""
    s = (value or "").strip()
    return s if s else None


def _parse_product_kinds(form_data: list[str]) -> list[str]:
    """FastAPI Form() with the same name multi-yields a list[str]."""
    return [p for p in form_data if p in ("network", "protect", "access")]


def _coerce_checkbox(value: str) -> bool:
    """Browser sends 'on' for checked checkboxes; absent = empty string."""
    return (value or "").strip().lower() in ("on", "true", "1", "yes")


@router.get("/admin/controllers", include_in_schema=False)
async def controllers_page(request: Request):
    """Unauthenticated HTMX shell — the table body fetches its rows separately."""
    return render(request, "controllers/list.html")


@router.get(
    "/admin/controllers/_table",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_table(request: Request):
    sm = request.app.state.sessionmaker
    async with sm() as session:
        rows = await list_controllers(session)
    return render(
        request,
        "controllers/_table.html",
        {"controllers": [_row_view(r) for r in rows]},
    )


@router.get(
    "/admin/controllers/_new_form",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_new_form(request: Request):
    return render(request, "controllers/_form.html", {"mode": "new"})


@router.post(
    "/admin/controllers/create",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_create(
    request: Request,
    name: str = Form(...),
    base_url: str = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    api_token: str = Form(""),
    product_kinds: list[str] = Form([]),
    verify_tls: str = Form(""),
    is_default: str = Form(""),
):
    sm = request.app.state.sessionmaker
    cipher = _cipher()
    payload = CreateControllerPayload(
        name=name,
        base_url=base_url,
        username=username.strip(),
        password=password,
        api_token=_blank_to_none(api_token),
        product_kinds=_parse_product_kinds(product_kinds),
        verify_tls=_coerce_checkbox(verify_tls),
        is_default=_coerce_checkbox(is_default),
    )
    async with sm() as session:
        await create_controller(session, cipher, payload)
        await session.commit()
    # Empty body — the form-slot is cleared; HX-Trigger refetches the table-body.
    return Response(
        status_code=200,
        content="",
        headers={"Cache-Control": "no-store", "HX-Trigger": "controllers-changed"},
    )


@router.get(
    "/admin/controllers/{cid}/_edit_form",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_edit_form(request: Request, cid: str):
    sm = request.app.state.sessionmaker
    cipher = _cipher()
    async with sm() as session:
        try:
            row = await get_controller(session, cid)
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")
    return render(
        request,
        "controllers/_form.html",
        {
            "mode": "edit",
            "controller": _row_view(row),
            "creds_is_set": _creds_is_set(row, cipher),
        },
    )


@router.post(
    "/admin/controllers/{cid}/update",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_update(
    request: Request,
    cid: str,
    name: str = Form(...),
    base_url: str = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    api_token: str = Form(""),
    product_kinds: list[str] = Form([]),
    verify_tls: str = Form(""),
    is_default: str = Form(""),
):
    sm = request.app.state.sessionmaker
    cipher = _cipher()
    async with sm() as session:
        try:
            await update_controller(
                session,
                cipher,
                cid,
                name=name,
                base_url=base_url,
                product_kinds=_parse_product_kinds(product_kinds),
                verify_tls=_coerce_checkbox(verify_tls),
                is_default=_coerce_checkbox(is_default),
                username=_blank_to_none(username),
                password=_blank_to_none(password),
                api_token=_blank_to_none(api_token),
            )
            await session.commit()
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")
        await request.app.state.manager_factory.invalidate_controller(cid)
        request.app.state.capability_cache.invalidate(cid)
    return Response(
        status_code=200,
        content="",
        headers={"Cache-Control": "no-store", "HX-Trigger": "controllers-changed"},
    )


@router.post(
    "/admin/controllers/{cid}/delete",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_delete(request: Request, cid: str):
    sm = request.app.state.sessionmaker
    async with sm() as session:
        try:
            await delete_controller(session, cid)
            await session.commit()
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")
    await request.app.state.manager_factory.invalidate_controller(cid)
    request.app.state.capability_cache.invalidate(cid)
    return Response(
        status_code=200,
        content="",
        headers={"Cache-Control": "no-store", "HX-Trigger": "controllers-changed"},
    )


@router.post(
    "/admin/controllers/{cid}/probe",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def controllers_probe(request: Request, cid: str):
    sm = request.app.state.sessionmaker
    async with sm() as session:
        try:
            await get_controller(session, cid)
        except ControllerNotFound:
            raise HTTPException(status_code=404, detail="controller not found")
    result = await request.app.state.manager_factory.probe_controller(cid)
    return render(
        request,
        "controllers/_probe_result.html",
        {"cid": cid, "result": result},
    )
