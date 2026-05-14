"""Admin UI routes for managing API keys (list / create / revoke).

The page route is unauthenticated and returns the HTMX shell; the row
listing fragment, create form, and revoke action are admin-scoped. This
mirrors the dashboard pattern — vanilla browser navigation never carries
the localStorage Bearer, so the shell loads first and HTMX fetches data
with the Bearer attached by admin.js. Plaintext keys are emitted exactly
once (in the create response) and never re-shown; listings show prefixes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy import select

from unifi_api.auth.api_key import ApiKeyEnv, generate_key, hash_key
from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.db.models import ApiKey
from unifi_api.routes.admin._common import render

router = APIRouter()


async def _list_keys(sm) -> list[ApiKey]:
    async with sm() as session:
        return list((await session.execute(select(ApiKey).order_by(ApiKey.created_at.desc()))).scalars().all())


@router.get("/admin/keys", include_in_schema=False)
async def keys_page(request: Request):
    """Unauthenticated HTMX shell — the table body fetches its rows separately."""
    return render(request, "keys/list.html")


@router.get(
    "/admin/keys/_table",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def keys_table(request: Request):
    rows = await _list_keys(request.app.state.sessionmaker)
    return render(request, "keys/_table.html", {"keys": rows})


@router.post(
    "/admin/keys/create",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def keys_create(
    request: Request,
    name: str = Form(...),
    scopes: str = Form("read"),
):
    """Generate a new API key and return the modal fragment containing the plaintext.

    The HX-Trigger header fires `keys-changed` on the body, which the table-body
    listens for to refetch its rows. This avoids the bare-tbody OOB swap parser
    quirk where browsers strip <tr> elements outside a <table>.
    """
    sm = request.app.state.sessionmaker
    material = generate_key(env=ApiKeyEnv.LIVE)
    async with sm() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes=scopes,
                name=name,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()
    response = render(
        request,
        "keys/_created_modal.html",
        {"plaintext": material.plaintext, "name": name, "scopes": scopes},
    )
    response.headers["HX-Trigger"] = "keys-changed"
    return response


@router.post(
    "/admin/keys/{key_id}/revoke",
    include_in_schema=False,
    dependencies=[Depends(require_scope(Scope.ADMIN))],
)
async def keys_revoke(request: Request, key_id: str):
    sm = request.app.state.sessionmaker
    async with sm() as session:
        row = await session.get(ApiKey, key_id)
        if row is None:
            raise HTTPException(status_code=404, detail="key not found")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(timezone.utc)
            await session.commit()
    # Empty body + HX-Trigger fires the table-body refetch (revoked rows show "revoked" status).
    return Response(
        status_code=200,
        content="",
        headers={"Cache-Control": "no-store", "HX-Trigger": "keys-changed"},
    )
