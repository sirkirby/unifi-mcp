"""Public empty admin shell and authenticated cloud-account fragments/actions."""

from fastapi import APIRouter, Depends, Request, Response
from pydantic import ValidationError
from unifi_core.sitemanager.models.connections import SiteManagerConnectionCreate, SiteManagerConnectionPatch

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.admin._common import render
from unifi_api.routes.sitemanager_connections import manage
from unifi_api.services.sitemanager_errors import SiteManagerAPIError, map_error

router = APIRouter()
secured = APIRouter(prefix="/admin/sitemanager", dependencies=[Depends(require_scope(Scope.ADMIN))])


@router.get("/admin/sitemanager", include_in_schema=False)
async def page(request: Request):
    return render(request, "sitemanager/page.html")


@secured.get("/_connection", include_in_schema=False)
async def connection(request: Request):
    data = None
    try:
        data = (await manage(request, "get")).data
    except SiteManagerAPIError as exc:
        if exc.kind != "sitemanager_not_configured":
            raise
    return render(request, "sitemanager/_connection.html", {"connection": data})


@secured.get("/_new_form", include_in_schema=False)
async def new_form(request: Request):
    return render(request, "sitemanager/_form.html", {"mode": "new"})


@secured.get("/_edit_form", include_in_schema=False)
async def edit_form(request: Request):
    data = (await manage(request, "get")).data
    return render(request, "sitemanager/_form.html", {"mode": "edit", "connection": data})


async def _input(request: Request, *, patch: bool):
    form = await request.form()
    data = dict(form)
    key = data.get("site_manager_api_key", "")
    if patch and isinstance(key, str) and not key.strip():
        data.pop("site_manager_api_key", None)
    model = SiteManagerConnectionPatch if patch else SiteManagerConnectionCreate
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        error = map_error(exc, "validate Site Manager connection", management=True)
    raise error from None


def _changed():
    return Response(headers={"Cache-Control": "no-store", "HX-Trigger": "sitemanager-changed"})


@secured.post("/create", include_in_schema=False)
async def create(request: Request):
    await manage(request, "create", await _input(request, patch=False))
    return _changed()


@secured.post("/update", include_in_schema=False)
async def update(request: Request):
    await manage(request, "update", await _input(request, patch=True))
    return _changed()


@secured.post("/delete", include_in_schema=False)
async def delete(request: Request):
    await manage(request, "delete")
    return _changed()


@secured.post("/probe", include_in_schema=False)
async def probe(request: Request):
    result = await manage(request, "probe")
    response = render(request, "sitemanager/_probe_result.html", {"result": result.data})
    response.status_code = result.status
    return response


router.include_router(secured)
