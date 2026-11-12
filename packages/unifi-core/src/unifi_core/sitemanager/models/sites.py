"""Site Manager sites: Network application sites across every host the account can see."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.sitemanager.models._coerce import as_dict, as_list, flag, number, scalars, text

_MAX_INTERNET_ISSUES = 50


class Site(BaseModel):
    """A Network site as the Site Manager API reports it."""

    model_config = ConfigDict(extra="ignore")

    site_id: str | None = Field(default=None, description="Site Manager site id")
    host_id: str | None = Field(default=None, description="Site Manager id of the host running the site")
    name: str | None = Field(default=None, description="Site name key")
    description: str | None = Field(default=None, description="Site display name")
    timezone: str | None = Field(default=None, description="Site timezone")
    gateway_mac: str | None = Field(default=None, description="MAC address of the site's gateway")
    permission: str | None = Field(default=None, description="The account's permission on the site")
    is_owner: bool | None = Field(default=None, description="Whether the API key's account owns the site")
    counts: dict[str, int] = Field(default_factory=dict, description="Device, client and configuration counts")
    gateway: dict[str, Any] = Field(default_factory=dict, description="Gateway model and threat-inspection state")
    isp: dict[str, Any] = Field(default_factory=dict, description="ISP name and organization")
    wan_uptime_percent: int | float | None = Field(default=None, description="WAN uptime percentage")
    internet_issues: list[dict[str, Any]] = Field(
        default_factory=list, description="Recent internet issue intervals, most recent API order"
    )


def site_from_api(raw: Any) -> Site:
    """Build a :class:`Site` from one ``/v1/sites`` entry."""
    site = as_dict(raw)
    meta = as_dict(site.get("meta"))
    statistics = as_dict(site.get("statistics"))
    counts = {
        key: value
        for key, value in as_dict(statistics.get("counts")).items()
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool)
    }
    issues = [scalars(issue) for issue in as_list(statistics.get("internetIssues"))[:_MAX_INTERNET_ISSUES]]
    return Site(
        site_id=text(site.get("siteId")),
        host_id=text(site.get("hostId")),
        name=text(meta.get("name")),
        description=text(meta.get("desc")),
        timezone=text(meta.get("timezone")),
        gateway_mac=text(meta.get("gatewayMac")),
        permission=text(site.get("permission")),
        is_owner=flag(site.get("isOwner")),
        counts=counts,
        gateway=scalars(statistics.get("gateway")),
        isp=scalars(statistics.get("ispInfo")),
        wan_uptime_percent=number(as_dict(statistics.get("percentages")).get("wanUptime")),
        internet_issues=[issue for issue in issues if issue],
    )
