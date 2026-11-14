"""Explicit Site Manager hosts read shapes."""

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.sitemanager._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class SiteManagerHostApplication(Projection):
    name: str | None = strawberry.field(description="Application name, such as network or protect")
    type: str | None = strawberry.field(description="Application type")
    version: str | None = strawberry.field(description="Installed version")
    state: str | None = strawberry.field(description="Lifecycle state reported by the console")
    status: str | None = strawberry.field(description="Status reported by the application")
    is_installed: bool | None = strawberry.field(description="Whether the application is installed")
    is_running: bool | None = strawberry.field(description="Whether the application is running")
    is_configured: bool | None = strawberry.field(description="Whether initial setup is complete")
    update_available: str | None = strawberry.field(description="Version available as an update, if any")
    _columns = ["name", "state", "status"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerHost(Projection):
    id: str | None = strawberry.field(description="Site Manager host id")
    hardware_id: str | None = strawberry.field(description="Hardware id")
    type: str | None = strawberry.field(description="Host type, such as console or network-server")
    ip_address: str | None = strawberry.field(description="Public IP address")
    owner: bool | None = strawberry.field(description="Whether the API key's account owns this host")
    is_blocked: bool | None = strawberry.field(description="Whether the host is blocked")
    registration_time: JSON | None = strawberry.field(description="When the host was registered")
    last_connection_state_change: JSON | None = strawberry.field(
        description="When the host last connected or disconnected"
    )
    latest_backup_time: JSON | None = strawberry.field(description="When the latest cloud backup was taken")
    name: str | None = strawberry.field(description="Console name")
    hostname: str | None = strawberry.field(description="Console hostname")
    state: str | None = strawberry.field(description="Connection state, such as connected")
    os_version: str | None = strawberry.field(description="UniFi OS or server version")
    model: str | None = strawberry.field(description="Hardware model name")
    shortname: str | None = strawberry.field(description="Hardware short name, such as UDMPROSE")
    firmware_version: str | None = strawberry.field(description="Hardware firmware version")
    mac: str | None = strawberry.field(description="Console MAC address")
    timezone: str | None = strawberry.field(description="Console timezone")
    release_channel: str | None = strawberry.field(description="Update release channel")
    applications: list[SiteManagerHostApplication] = strawberry.field(description="Applications on the host")
    reported_state: JSON | None = strawberry.field(
        description="Full state reported by the host; present only when requested"
    )

    _nested = {"applications": (SiteManagerHostApplication, True)}
    _identity = "id"
    _columns = ["name", "state"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerHostPage(Projection):
    items: list[SiteManagerHost]
    next_cursor: str | None
    _nested = {"items": (SiteManagerHost, True)}
