"""Account-scoped GraphQL queries through the common leased read adapter."""

import strawberry
from strawberry.types import Info

from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.sitemanager._base import DESCRIPTION
from unifi_api.graphql.types.sitemanager.devices import SiteManagerHostDevicesPage
from unifi_api.graphql.types.sitemanager.hosts import SiteManagerHost, SiteManagerHostPage
from unifi_api.graphql.types.sitemanager.isp_metrics import SiteManagerIspMetrics, SiteManagerIspMetricsQueryResult
from unifi_api.graphql.types.sitemanager.sdwan import (
    SiteManagerSdwanConfig,
    SiteManagerSdwanConfigList,
    SiteManagerSdwanConfigStatus,
)
from unifi_api.graphql.types.sitemanager.sites import SiteManagerSitePage
from unifi_api.services.sitemanager_reads import read_sitemanager


@strawberry.input(description=DESCRIPTION)
class SiteManagerMetricsSiteInput:
    host_id: str
    site_id: str
    begin_timestamp: str | None = None
    end_timestamp: str | None = None


async def _read(info, name, args):
    ctx = info.context
    return await read_sitemanager(
        registry=ctx.manifest_registry,
        type_registry=ctx.type_registry,
        factory=ctx.sitemanager_factory,
        tool_name=name,
        args={key: value for key, value in args.items() if value is not None},
        redact_sensitive=ctx.redact_sensitive_fields,
        cache=ctx.cache,
    )


@strawberry.type(description=DESCRIPTION)
class SiteManagerQuery:
    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def hosts(self, info: Info, page_size: int | None = None, cursor: str | None = None) -> SiteManagerHostPage:
        result = await _read(info, "sitemanager_list_hosts", {"page_size": page_size, "cursor": cursor})
        return SiteManagerHostPage(items=result.data, next_cursor=result.meta["next_cursor"])

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def host(self, info: Info, host_id: str, include_reported_state: bool = False) -> SiteManagerHost:
        return (
            await _read(
                info,
                "sitemanager_get_host",
                {
                    "host_id": host_id,
                    "include_reported_state": include_reported_state,
                },
            )
        ).data

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def sites(self, info: Info, page_size: int | None = None, cursor: str | None = None) -> SiteManagerSitePage:
        result = await _read(info, "sitemanager_list_sites", {"page_size": page_size, "cursor": cursor})
        return SiteManagerSitePage(items=result.data, next_cursor=result.meta["next_cursor"])

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def devices(
        self,
        info: Info,
        host_ids: list[str] | None = None,
        updated_since: str | None = None,
        page_size: int | None = None,
        cursor: str | None = None,
    ) -> SiteManagerHostDevicesPage:
        result = await _read(
            info,
            "sitemanager_list_devices",
            {
                "host_ids": host_ids,
                "updated_since": updated_since,
                "page_size": page_size,
                "cursor": cursor,
            },
        )
        return SiteManagerHostDevicesPage(items=result.data, next_cursor=result.meta["next_cursor"])

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def isp_metrics(
        self,
        info: Info,
        metric_type: str = "1h",
        duration: str | None = None,
        begin_timestamp: str | None = None,
        end_timestamp: str | None = None,
        period_limit: int = 12,
    ) -> SiteManagerIspMetrics:
        result = await _read(
            info,
            "sitemanager_get_isp_metrics",
            {
                "metric_type": metric_type,
                "duration": duration,
                "begin_timestamp": begin_timestamp,
                "end_timestamp": end_timestamp,
                "period_limit": period_limit,
            },
        )
        return SiteManagerIspMetrics(items=result.data, next_cursor=None, count=result.meta["count"])

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def query_isp_metrics(
        self, info: Info, sites: list[SiteManagerMetricsSiteInput], metric_type: str = "1h", period_limit: int = 12
    ) -> SiteManagerIspMetricsQueryResult:
        return (
            await _read(
                info,
                "sitemanager_query_isp_metrics",
                {
                    "sites": [strawberry.asdict(site) for site in sites],
                    "metric_type": metric_type,
                    "period_limit": period_limit,
                },
            )
        ).data

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def sdwan_configs(self, info: Info) -> SiteManagerSdwanConfigList:
        result = await _read(info, "sitemanager_list_sdwan_configs", {})
        return SiteManagerSdwanConfigList(items=result.data, next_cursor=None)

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def sdwan_config(self, info: Info, config_id: str) -> SiteManagerSdwanConfig:
        return (await _read(info, "sitemanager_get_sdwan_config", {"config_id": config_id})).data

    @strawberry.field(permission_classes=[IsRead], description=DESCRIPTION)
    async def sdwan_config_status(self, info: Info, config_id: str) -> SiteManagerSdwanConfigStatus:
        return (await _read(info, "sitemanager_get_sdwan_config_status", {"config_id": config_id})).data
