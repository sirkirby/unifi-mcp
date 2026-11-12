"""Site Manager hosts: the consoles and self-hosted servers linked to a UI account.

``userData`` is never returned: it holds the account holder's name, email and
role. ``reportedState`` is reduced to the fields below unless the caller asks
for one host's full state.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.sitemanager.models._coerce import as_dict, as_list, flag, text, timestamp

# reportedState entries left out of the full view: account identifiers, device
# location, and a large image-metadata blob with no operational content.
_FULL_STATE_EXCLUDED = frozenset({"anonid", "location", "uidb"})


class HostApplication(BaseModel):
    """One UniFi application (Network, Protect, Access, ...) on a host."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, description="Application name, such as network or protect")
    type: str | None = Field(default=None, description="Application type")
    version: str | None = Field(default=None, description="Installed version")
    state: str | None = Field(default=None, description="Lifecycle state reported by the console")
    status: str | None = Field(default=None, description="Status reported by the application")
    is_installed: bool | None = Field(default=None, description="Whether the application is installed")
    is_running: bool | None = Field(default=None, description="Whether the application is running")
    is_configured: bool | None = Field(default=None, description="Whether initial setup is complete")
    update_available: str | None = Field(default=None, description="Version available as an update, if any")


class Host(BaseModel):
    """A host as the Site Manager API reports it."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="Site Manager host id")
    hardware_id: str | None = Field(default=None, description="Hardware id")
    type: str | None = Field(default=None, description="Host type, such as console or network-server")
    ip_address: str | None = Field(default=None, description="Public IP address")
    owner: bool | None = Field(default=None, description="Whether the API key's account owns this host")
    is_blocked: bool | None = Field(default=None, description="Whether the host is blocked")
    registration_time: str | int | None = Field(default=None, description="When the host was registered")
    last_connection_state_change: str | int | None = Field(
        default=None, description="When the host last connected or disconnected"
    )
    latest_backup_time: str | int | None = Field(default=None, description="When the latest cloud backup was taken")
    name: str | None = Field(default=None, description="Console name")
    hostname: str | None = Field(default=None, description="Console hostname")
    state: str | None = Field(default=None, description="Connection state, such as connected")
    os_version: str | None = Field(default=None, description="UniFi OS or server version")
    model: str | None = Field(default=None, description="Hardware model name")
    shortname: str | None = Field(default=None, description="Hardware short name, such as UDMPROSE")
    firmware_version: str | None = Field(default=None, description="Hardware firmware version")
    mac: str | None = Field(default=None, description="Console MAC address")
    timezone: str | None = Field(default=None, description="Console timezone")
    release_channel: str | None = Field(default=None, description="Update release channel")
    applications: list[HostApplication] = Field(default_factory=list, description="Applications on the host")
    reported_state: dict[str, Any] | None = Field(
        default=None, description="Full state reported by the host; present only when requested"
    )


def _update_version(value: Any) -> str | None:
    """``updateAvailable`` is a version string on some releases and an object on others."""
    return text(value) or text(as_dict(value).get("version"))


def _application(raw: Any) -> HostApplication:
    app = as_dict(raw)
    return HostApplication(
        name=text(app.get("name")),
        type=text(app.get("type")),
        version=text(app.get("version")),
        state=text(app.get("state")),
        status=text(app.get("status")),
        is_installed=flag(app.get("isInstalled")),
        is_running=flag(app.get("isRunning")),
        is_configured=flag(app.get("isConfigured")),
        update_available=_update_version(app.get("updateAvailable")),
    )


def host_from_api(raw: Any, *, include_reported_state: bool = False) -> Host:
    """Build a :class:`Host` from one ``/v1/hosts`` entry."""
    host = as_dict(raw)
    state = as_dict(host.get("reportedState"))
    hardware = as_dict(state.get("hardware"))
    return Host(
        id=text(host.get("id")),
        hardware_id=text(host.get("hardwareId")),
        type=text(host.get("type")),
        ip_address=text(host.get("ipAddress")),
        owner=flag(host.get("owner")),
        is_blocked=flag(host.get("isBlocked")),
        registration_time=timestamp(host.get("registrationTime")),
        last_connection_state_change=timestamp(host.get("lastConnectionStateChange")),
        latest_backup_time=timestamp(host.get("latestBackupTime")),
        name=text(state.get("name")),
        hostname=text(state.get("hostname")),
        state=text(state.get("state")),
        os_version=text(state.get("version")),
        model=text(hardware.get("name")),
        shortname=text(hardware.get("shortname")),
        firmware_version=text(hardware.get("firmwareVersion")),
        mac=text(state.get("mac")),
        timezone=text(state.get("timezone")),
        release_channel=text(state.get("releaseChannel")),
        applications=[_application(app) for app in as_list(state.get("controllers")) if isinstance(app, dict)],
        reported_state=(
            {key: value for key, value in state.items() if key not in _FULL_STATE_EXCLUDED}
            if include_reported_state
            else None
        ),
    )
