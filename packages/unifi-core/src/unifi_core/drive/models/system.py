"""The UniFi OS console a UniFi Drive runs on, from ``GET /api/system``.

``/api/system`` returns far more than this: the console's geographic location,
public IP, owner account and cloud identifiers. Only the fields below are kept.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.drive.models._coerce import as_dict, as_list, flag, number, text


class DriveSystemInfo(BaseModel):
    """Identity, firmware and health of the NAS console."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, description="Console name")
    hostname: str | None = Field(default=None, description="Console hostname")
    model: str | None = Field(default=None, description="Hardware model, such as UniFi Network Attached Storage Pro 8")
    shortname: str | None = Field(default=None, description="Hardware short name, such as UNASPRO8")
    mac: str | None = Field(default=None, description="Console MAC address")
    firmware_version: str | None = Field(default=None, description="UniFi OS firmware version")
    firmware_update_available: str | None = Field(
        default=None, description="Firmware version available as an update, if any"
    )
    device_state: str | None = Field(default=None, description="Console state, such as setup or updateAvailable")
    is_setup: bool | None = Field(default=None, description="Whether initial setup is complete")
    uptime_seconds: float | None = Field(default=None, description="Seconds since the console started")
    timezone: str | None = Field(default=None, description="Console timezone")
    cpu_load: float | None = Field(default=None, description="CPU load reported by the console, 0 to 1")
    cpu_temperature_c: float | None = Field(default=None, description="CPU temperature in degrees Celsius")
    memory_total_kb: int | None = Field(default=None, description="Total memory in KiB")
    memory_available_kb: int | None = Field(default=None, description="Available memory in KiB")


def _own_device(system: dict[str, Any]) -> dict[str, Any]:
    """The console's own entry in ``devices.unifiOS``, which carries the update status."""
    mac = text(system.get("mac"))
    for device in as_list(as_dict(system.get("devices")).get("unifiOS")):
        entry = as_dict(device)
        if entry.get("source") == "self" or (mac and entry.get("mac") == mac):
            return entry
    return {}


def system_info_from_api(raw: Any) -> DriveSystemInfo:
    """Build :class:`DriveSystemInfo` from a ``GET /api/system`` body."""
    system = as_dict(raw)
    hardware = as_dict(system.get("hardware"))
    device = _own_device(system)
    cpu = as_dict(system.get("cpu"))
    memory = as_dict(system.get("memory"))
    update = text(device.get("updateAvailable")) or text(as_dict(device.get("updateAvailable")).get("version"))
    total = number(memory.get("total"))
    available = number(memory.get("available"))
    return DriveSystemInfo(
        name=text(system.get("name")),
        hostname=text(system.get("hostname")),
        model=text(hardware.get("name")),
        shortname=text(hardware.get("shortname")),
        mac=text(system.get("mac")),
        firmware_version=text(hardware.get("firmwareVersion")) or text(device.get("firmware")),
        firmware_update_available=update,
        device_state=text(system.get("deviceState")),
        is_setup=flag(system.get("isSetup")),
        uptime_seconds=number(system.get("uptime")),
        timezone=text(system.get("timezone")),
        cpu_load=number(cpu.get("currentload")),
        cpu_temperature_c=number(cpu.get("temperature")),
        memory_total_kb=int(total) if total is not None else None,
        memory_available_kb=int(available) if available is not None else None,
    )
