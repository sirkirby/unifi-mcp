"""Site Manager devices: UniFi devices grouped by the host that manages them."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.sitemanager.models._coerce import as_dict, as_list, flag, text, timestamp


class ManagedDevice(BaseModel):
    """One UniFi device. The API's ``uidb`` image metadata is left out."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="Site Manager device id")
    mac: str | None = Field(default=None, description="Device MAC address")
    name: str | None = Field(default=None, description="Device name")
    model: str | None = Field(default=None, description="Device model")
    shortname: str | None = Field(default=None, description="Device short name")
    ip: str | None = Field(default=None, description="Device IP address")
    product_line: str | None = Field(default=None, description="Product line, such as network or protect")
    status: str | None = Field(default=None, description="Connection status")
    version: str | None = Field(default=None, description="Firmware version")
    firmware_status: str | None = Field(default=None, description="Firmware status, such as upToDate")
    update_available: str | None = Field(default=None, description="Firmware version available as an update")
    is_console: bool | None = Field(default=None, description="Whether the device is the host console itself")
    is_managed: bool | None = Field(default=None, description="Whether the device is managed by the host")
    startup_time: str | int | None = Field(default=None, description="When the device last started")
    adoption_time: str | int | None = Field(default=None, description="When the device was adopted")
    note: str | None = Field(default=None, description="Operator note on the device")


class HostDevices(BaseModel):
    """The devices one host manages."""

    model_config = ConfigDict(extra="ignore")

    host_id: str | None = Field(default=None, description="Site Manager host id")
    host_name: str | None = Field(default=None, description="Host name")
    updated_at: str | int | None = Field(default=None, description="When the host last reported its devices")
    devices: list[ManagedDevice] = Field(default_factory=list, description="Devices managed by the host")


def _device(raw: Any) -> ManagedDevice:
    device = as_dict(raw)
    return ManagedDevice(
        id=text(device.get("id")),
        mac=text(device.get("mac")),
        name=text(device.get("name")),
        model=text(device.get("model")),
        shortname=text(device.get("shortname")),
        ip=text(device.get("ip")),
        product_line=text(device.get("productLine")),
        status=text(device.get("status")),
        version=text(device.get("version")),
        firmware_status=text(device.get("firmwareStatus")),
        update_available=text(device.get("updateAvailable")),
        is_console=flag(device.get("isConsole")),
        is_managed=flag(device.get("isManaged")),
        startup_time=timestamp(device.get("startupTime")),
        adoption_time=timestamp(device.get("adoptionTime")),
        note=text(device.get("note")),
    )


def host_devices_from_api(raw: Any) -> HostDevices:
    """Build a :class:`HostDevices` from one ``/v1/devices`` entry."""
    group = as_dict(raw)
    return HostDevices(
        host_id=text(group.get("hostId")),
        host_name=text(group.get("hostName")),
        updated_at=timestamp(group.get("updatedAt")),
        devices=[_device(device) for device in as_list(group.get("devices")) if isinstance(device, dict)],
    )
