"""Explicit Site Manager sites read shapes."""

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.sitemanager._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class SiteManagerSite(Projection):
    site_id: str | None = strawberry.field(description="Site Manager site id")
    host_id: str | None = strawberry.field(description="Site Manager id of the host running the site")
    name: str | None = strawberry.field(description="Site name key")
    description: str | None = strawberry.field(description="Site display name")
    timezone: str | None = strawberry.field(description="Site timezone")
    gateway_mac: str | None = strawberry.field(description="MAC address of the site's gateway")
    permission: str | None = strawberry.field(description="The account's permission on the site")
    is_owner: bool | None = strawberry.field(description="Whether the API key's account owns the site")
    counts: JSON = strawberry.field(description="Device, client and configuration counts")
    gateway: JSON = strawberry.field(description="Gateway model and threat-inspection state")
    isp: JSON = strawberry.field(description="ISP name and organization")
    wan_uptime_percent: float | None = strawberry.field(description="WAN uptime percentage")
    internet_issues: list[JSON] = strawberry.field(description="Recent internet issue intervals, most recent API order")
    _columns = ["name", "host_id", "site_id"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerSitePage(Projection):
    items: list[SiteManagerSite]
    next_cursor: str | None
    _nested = {"items": (SiteManagerSite, True)}
