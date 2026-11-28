"""The NAS console a UniFi Drive runs on."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.scalars import BigInt
from unifi_api.graphql.types.drive._base import Projection


@strawberry.type(description="Identity, firmware and health of the UniFi OS console that runs UniFi Drive.")
class DriveSystemInfo(Projection):
    name: str | None = strawberry.field(description="Console name")
    hostname: str | None = strawberry.field(description="Console hostname")
    model: str | None = strawberry.field(description="Hardware model, such as UniFi Network Attached Storage Pro 8")
    shortname: str | None = strawberry.field(description="Hardware short name, such as UNASPRO8")
    mac: str | None = strawberry.field(description="Console MAC address")
    firmware_version: str | None = strawberry.field(description="UniFi OS firmware version")
    firmware_update_available: str | None = strawberry.field(
        description="Firmware version available as an update, if any"
    )
    drive_version: str | None = strawberry.field(description="UniFi Drive application version")
    drive_update_available: str | None = strawberry.field(
        description="UniFi Drive application version available as an update, if any"
    )
    device_state: str | None = strawberry.field(description="Console state, such as setup or updateAvailable")
    is_setup: bool | None = strawberry.field(description="Whether initial setup is complete")
    uptime_seconds: float | None = strawberry.field(description="Seconds since the console started")
    timezone: str | None = strawberry.field(description="Console timezone")
    cpu_load: float | None = strawberry.field(description="CPU load reported by the console, 0 to 1")
    cpu_temperature_c: float | None = strawberry.field(description="CPU temperature in degrees Celsius")
    memory_total_kb: BigInt | None = strawberry.field(description="Total memory in KiB")
    memory_available_kb: BigInt | None = strawberry.field(description="Available memory in KiB")

    _columns = ["name", "model", "firmware_version", "drive_version", "device_state"]
