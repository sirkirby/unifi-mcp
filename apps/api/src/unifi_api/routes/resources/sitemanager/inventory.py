"""Single-page account inventory with native upstream cursors."""

from fastapi import APIRouter, Query, Request

from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.sitemanager._base import DESCRIPTION
from unifi_api.graphql.types.sitemanager.devices import SiteManagerHostDevices
from unifi_api.graphql.types.sitemanager.hosts import SiteManagerHost
from unifi_api.graphql.types.sitemanager.sites import SiteManagerSite
from unifi_api.routes.resources.sitemanager._common import AccountReadRoute, read
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter(prefix="/sitemanager", route_class=AccountReadRoute, tags=["sitemanager/inventory"])


@router.get("/hosts", description=DESCRIPTION, response_model=Page[to_pydantic_model(SiteManagerHost)])
async def list_sitemanager_hosts(
    request: Request, page_size: int | None = Query(None, ge=1, le=500), cursor: str | None = None
):
    return await read(
        request,
        "sitemanager_list_hosts",
        {"page_size": page_size, "cursor": cursor},
        query_fields={"page_size", "cursor"},
    )


@router.get("/hosts/{host_id}", description=DESCRIPTION, response_model=Detail[to_pydantic_model(SiteManagerHost)])
async def get_sitemanager_host(request: Request, host_id: str, include_reported_state: bool = False):
    return await read(
        request,
        "sitemanager_get_host",
        {"host_id": host_id, "include_reported_state": include_reported_state},
        query_fields={"include_reported_state"},
    )


@router.get("/sites", description=DESCRIPTION, response_model=Page[to_pydantic_model(SiteManagerSite)])
async def list_sitemanager_sites(
    request: Request, page_size: int | None = Query(None, ge=1, le=500), cursor: str | None = None
):
    return await read(
        request,
        "sitemanager_list_sites",
        {"page_size": page_size, "cursor": cursor},
        query_fields={"page_size", "cursor"},
    )


@router.get("/devices", description=DESCRIPTION, response_model=Page[to_pydantic_model(SiteManagerHostDevices)])
async def list_sitemanager_devices(
    request: Request,
    host_ids: list[str] | None = Query(None),
    updated_since: str | None = None,
    page_size: int | None = Query(None, ge=1, le=500),
    cursor: str | None = None,
):
    return await read(
        request,
        "sitemanager_list_devices",
        {
            "host_ids": host_ids,
            "updated_since": updated_since,
            "page_size": page_size,
            "cursor": cursor,
        },
        query_fields={"host_ids", "updated_since", "page_size", "cursor"},
    )
