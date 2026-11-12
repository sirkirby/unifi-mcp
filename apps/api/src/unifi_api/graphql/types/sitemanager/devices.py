"""Explicit Site Manager devices read shapes."""

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.sitemanager._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class SiteManagerManagedDevice(Projection):
    id: str | None = strawberry.field(description="Site Manager device id")
    mac: str | None = strawberry.field(description="Device MAC address")
    name: str | None = strawberry.field(description="Device name")
    model: str | None = strawberry.field(description="Device model")
    shortname: str | None = strawberry.field(description="Device short name")
    ip: str | None = strawberry.field(description="Device IP address")
    product_line: str | None = strawberry.field(description="Product line, such as network or protect")
    status: str | None = strawberry.field(description="Connection status")
    version: str | None = strawberry.field(description="Firmware version")
    firmware_status: str | None = strawberry.field(description="Firmware status, such as upToDate")
    update_available: str | None = strawberry.field(description="Firmware version available as an update")
    is_console: bool | None = strawberry.field(description="Whether the device is the host console itself")
    is_managed: bool | None = strawberry.field(description="Whether the device is managed by the host")
    startup_time: JSON | None = strawberry.field(description="When the device last started")
    adoption_time: JSON | None = strawberry.field(description="When the device was adopted")
    note: str | None = strawberry.field(description="Operator note on the device")
    _identity = "id"
    _columns = ["name", "status"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerHostDevices(Projection):
    host_id: str | None = strawberry.field(description="Site Manager host id")
    host_name: str | None = strawberry.field(description="Host name")
    updated_at: JSON | None = strawberry.field(description="When the host last reported its devices")
    devices: list[SiteManagerManagedDevice] = strawberry.field(description="Devices managed by the host")

    _nested = {"devices": (SiteManagerManagedDevice, True)}
    _columns = ["host_id"]


@strawberry.type(description=DESCRIPTION)
class SiteManagerHostDevicesPage(Projection):
    items: list[SiteManagerHostDevices]
    next_cursor: str | None
    _nested = {"items": (SiteManagerHostDevices, True)}
