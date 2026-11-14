"""Unpaged account SD-WAN configuration reads."""

from fastapi import APIRouter, Request

from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.sitemanager._base import DESCRIPTION
from unifi_api.graphql.types.sitemanager.sdwan import (
    SiteManagerSdwanConfig,
    SiteManagerSdwanConfigStatus,
    SiteManagerSdwanConfigSummary,
)
from unifi_api.routes.resources.sitemanager._common import AccountReadRoute, read
from unifi_api.services.pydantic_models import Detail, Page

router = APIRouter(prefix="/sitemanager", route_class=AccountReadRoute, tags=["sitemanager/sdwan"])


@router.get(
    "/sd-wan-configs", description=DESCRIPTION, response_model=Page[to_pydantic_model(SiteManagerSdwanConfigSummary)]
)
async def list_sitemanager_sdwan_configs(request: Request):
    return await read(request, "sitemanager_list_sdwan_configs", {}, query_fields=set())


@router.get(
    "/sd-wan-configs/{config_id}",
    description=DESCRIPTION,
    response_model=Detail[to_pydantic_model(SiteManagerSdwanConfig)],
)
async def get_sitemanager_sdwan_config(request: Request, config_id: str):
    return await read(request, "sitemanager_get_sdwan_config", {"config_id": config_id}, query_fields=set())


@router.get(
    "/sd-wan-configs/{config_id}/status",
    description=DESCRIPTION,
    response_model=Detail[to_pydantic_model(SiteManagerSdwanConfigStatus)],
)
async def get_sitemanager_sdwan_config_status(request: Request, config_id: str):
    return await read(request, "sitemanager_get_sdwan_config_status", {"config_id": config_id}, query_fields=set())
