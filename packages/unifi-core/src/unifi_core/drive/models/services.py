"""File services (SMB, NFS, Time Machine) and NFS client connections.

Read from ``/proxy/drive/api/v1/services/...``:

* ``{smb|nfs|time-machine}/settings`` -- ``{"enable": bool}``
* ``settings`` -- the console's network interfaces, i.e. where clients connect
* ``nfs/advanced-settings`` -- the NFS connection list. Its ``PUT`` replaces
  the whole list, so a change to one client is a read-modify-write of all of
  them; :func:`connections_for_put` builds that body from what was read.

NFS on this firmware is NFSv3 and maps every client uid to one Drive user, so
there is no squash option to set. A client mounts ``<nas>:/var/nfs/shared/<name>``.

Field model: :class:`NfsConnection` is the list/read shape;
:class:`NfsConnectionInput` is what the add/update tools accept. Its fields are
the connection's mutable fields (``MUTABLE_FIELDS``), so a connection read from
the list can be passed back unchanged.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from unifi_core.drive.models._coerce import as_dict, as_list, flag, text

FileService = Literal["smb", "nfs", "time_machine"]

#: Tool-facing service name -> the path segment Drive uses.
SERVICE_PATHS: dict[str, str] = {"smb": "smb", "nfs": "nfs", "time_machine": "time-machine"}

NfsPermission = Literal["rw", "ro"]

# Hostnames, IPv4/IPv6 addresses, CIDR ranges and '*' wildcards. Whitespace,
# parentheses and commas are refused: in an exports line they would let a
# client value carry export options.
_CLIENT = re.compile(r"[A-Za-z0-9*][A-Za-z0-9.:*/_\-\[\]]*")
_MAX_CLIENT_LENGTH = 253
_IP_CHARS = re.compile(r"[0-9A-Fa-f.:/]+")

# Keys Drive adds to a connection when it is read back; they are not part of
# what the PUT body sends.
_CONNECTION_READ_ONLY_KEYS = frozenset({"errorCodes"})
_GRANT_READ_ONLY_KEYS = frozenset({"name", "status", "encryptionStatus"})


class NetworkInterface(BaseModel):
    """A network interface clients can reach the NAS on."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, description="Interface name, such as enp0s0")
    interface: str | None = Field(default=None, description="Port type, such as ethernet or sfp+")
    connected: bool | None = Field(default=None, description="Whether the link is up")
    link_speed: str | None = Field(default=None, description="Negotiated link speed, such as 10 GbE")
    max_speed: str | None = Field(default=None, description="Maximum link speed of the port")
    address: str | None = Field(default=None, description="IP address clients connect to")
    mac: str | None = Field(default=None, description="Interface MAC address")


class FileServices(BaseModel):
    """Which file-sharing protocols are on, and where clients connect."""

    model_config = ConfigDict(extra="ignore")

    smb_enabled: bool | None = Field(default=None, description="Whether SMB is enabled")
    nfs_enabled: bool | None = Field(default=None, description="Whether NFS is enabled")
    time_machine_enabled: bool | None = Field(
        default=None, description="Whether Time Machine (over SMB) is enabled; it requires SMB"
    )
    custom_domain: str | None = Field(default=None, description="Custom domain clients use, if one is set")
    network_interfaces: list[NetworkInterface] = Field(
        default_factory=list, description="Interfaces clients can connect to"
    )


class NfsSharedDriveGrant(BaseModel):
    """One shared drive an NFS client may mount, and how."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(default=None, description="Shared drive id (from drive_list_shared_drives)")
    name: str | None = Field(default=None, description="Shared drive name", json_schema_extra={"mutable": False})
    status: str | None = Field(default=None, description="Shared drive status", json_schema_extra={"mutable": False})
    encryption_status: str | None = Field(
        default=None, description="Shared drive encryption status", json_schema_extra={"mutable": False}
    )
    permission: str | None = Field(default=None, description="rw (read-write) or ro (read-only)")
    export_path: str | None = Field(
        default=None,
        description="Path a client mounts, <nas>:<export_path>",
        json_schema_extra={"mutable": False},
    )


class NfsConnection(BaseModel):
    """An NFS client allowed to mount one or more shared drives."""

    model_config = ConfigDict(extra="ignore")

    client: str | None = Field(default=None, description="Client IP address or hostname")
    async_writes: bool | None = Field(default=None, description="Whether the export uses async writes")
    shared_drives: list[NfsSharedDriveGrant] = Field(default_factory=list, description="Shared drives it may mount")
    error_codes: list[Any] = Field(
        default_factory=list,
        description="Problems Drive reports for this connection, such as an unresolvable hostname",
        json_schema_extra={"mutable": False},
    )


class NfsSharedDriveAccess(BaseModel):
    """Input: a shared drive to grant an NFS client, and the permission.

    The read-only fields of a listed grant (``name``, ``status``,
    ``encryption_status``, ``export_path``) are accepted and ignored, so a grant
    copied from ``drive_list_nfs_connections`` can be passed back as is.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Shared drive id (from drive_list_shared_drives)", min_length=1, max_length=128)
    permission: NfsPermission = Field(default="rw", description="rw (read-write, default) or ro (read-only)")
    name: str | None = Field(default=None, description="Ignored; read-only")
    status: str | None = Field(default=None, description="Ignored; read-only")
    encryption_status: str | None = Field(default=None, description="Ignored; read-only")
    export_path: str | None = Field(default=None, description="Ignored; read-only")

    def to_controller(self) -> dict[str, Any]:
        return {"id": self.id, "permission": self.permission}


def validate_client(value: Any) -> str:
    """Return a client IP, hostname, CIDR range or wildcard, or raise ``ValueError``."""
    if not isinstance(value, str):
        raise ValueError("client must be an IP address or hostname")
    client = value.strip()
    if not client or len(client) > _MAX_CLIENT_LENGTH or not (_CLIENT.fullmatch(client) or _is_ip(client)):
        raise ValueError(
            "client must be an IP address, hostname, CIDR range or wildcard pattern "
            "(letters, digits and . : / * - _ only)"
        )
    return client


def _is_ip(value: str) -> bool:
    """An IP address or CIDR range, such as an IPv6 value starting with ``::``.

    The character check comes first: ``ipaddress`` accepts an IPv6 scope id
    (``fe80::1%<anything>``), which could carry export options.
    """
    if not _IP_CHARS.fullmatch(value):
        return False
    try:
        ipaddress.ip_network(value, strict=False)
    except ValueError:
        return False
    return True


def is_world_client(client: str) -> bool:
    """Whether a client value lets any host mount: ``*`` or a ``/0`` range."""
    if set(client) <= {"*", "."}:
        return True
    if "/" not in client:
        return False
    try:
        return ipaddress.ip_network(client, strict=False).prefixlen == 0
    except ValueError:
        # NFS exports also parse shorthand such as ``0/0``, which ``ipaddress`` refuses.
        prefix = client.rsplit("/", 1)[1]
        return prefix.isdigit() and int(prefix) == 0


class NfsConnectionInput(BaseModel):
    """Input: an NFS client connection to add."""

    model_config = ConfigDict(extra="forbid")

    client: str = Field(description="Client IP address or hostname allowed to mount")
    shared_drives: list[NfsSharedDriveAccess] = Field(
        min_length=1, description="Shared drives the client may mount, each with rw or ro permission"
    )
    async_writes: bool = Field(
        default=False, description="Use async writes (faster, but data can be lost if the NAS loses power)"
    )

    @field_validator("client", mode="before")
    @classmethod
    def _client(cls, value: Any) -> str:
        return validate_client(value)

    @field_validator("shared_drives")
    @classmethod
    def _unique_drives(cls, value: list[NfsSharedDriveAccess]) -> list[NfsSharedDriveAccess]:
        ids = [grant.id for grant in value]
        if len(ids) != len(set(ids)):
            raise ValueError("shared_drives lists the same drive more than once")
        return value


#: Fields of a connection the add/update tools accept.
MUTABLE_FIELDS = frozenset({"client", "shared_drives", "async_writes"})
#: Fields that appear in list output only.
READ_ONLY_FIELDS = frozenset({"error_codes"})


def export_path(drive_name: str | None) -> str | None:
    return f"/var/nfs/shared/{drive_name}" if drive_name else None


def file_services_from_api(smb: Any, nfs: Any, time_machine: Any, settings: Any) -> FileServices:
    """Build :class:`FileServices` from the three service settings and the interface settings."""
    interfaces = [
        NetworkInterface(
            name=text(entry.get("interfaceName")),
            interface=text(entry.get("interface")),
            connected=flag(entry.get("connected")),
            link_speed=text(entry.get("linkSpeed")),
            max_speed=text(entry.get("maxSpeed")),
            address=text(entry.get("address")),
            mac=text(entry.get("mac")),
        )
        for entry in (as_dict(item) for item in as_list(as_dict(settings).get("networkInterfaces")))
    ]
    return FileServices(
        smb_enabled=flag(as_dict(smb).get("enable")),
        nfs_enabled=flag(as_dict(nfs).get("enable")),
        time_machine_enabled=flag(as_dict(time_machine).get("enable")),
        custom_domain=text(as_dict(settings).get("customDomain")),
        network_interfaces=interfaces,
    )


def nfs_connection_from_api(raw: Any) -> NfsConnection:
    connection = as_dict(raw)
    grants = []
    for item in as_list(connection.get("sharedDrives")):
        grant = as_dict(item)
        name = text(grant.get("name"))
        grants.append(
            NfsSharedDriveGrant(
                id=text(grant.get("id")),
                name=name,
                status=text(grant.get("status")),
                encryption_status=text(grant.get("encryptionStatus")),
                permission=text(grant.get("permission")),
                export_path=export_path(name),
            )
        )
    return NfsConnection(
        client=text(connection.get("client")),
        async_writes=flag(connection.get("async")),
        shared_drives=grants,
        error_codes=as_list(connection.get("errorCodes")),
    )


def nfs_connections_from_api(raw: Any) -> list[NfsConnection]:
    """The connection list from an ``nfs/advanced-settings`` body."""
    return [nfs_connection_from_api(entry) for entry in as_list(as_dict(raw).get("connections"))]


def connection_to_controller(connection: NfsConnectionInput) -> dict[str, Any]:
    """The ``PUT`` shape of one connection."""
    return {
        "client": connection.client,
        "async": connection.async_writes,
        "sharedDrives": [grant.to_controller() for grant in connection.shared_drives],
    }


def connection_for_put(raw: Any) -> dict[str, Any]:
    """An existing connection, as read, reduced to the ``PUT`` shape.

    Read-only keys Drive adds on read are dropped; any other key is kept, so a
    setting this module does not know about survives the round trip.
    """
    connection = {key: value for key, value in as_dict(raw).items() if key not in _CONNECTION_READ_ONLY_KEYS}
    connection["sharedDrives"] = [
        {key: value for key, value in as_dict(grant).items() if key not in _GRANT_READ_ONLY_KEYS}
        for grant in as_list(as_dict(raw).get("sharedDrives"))
    ]
    return connection


def connections_for_put(raw: Any) -> list[dict[str, Any]]:
    """Every existing connection from an ``nfs/advanced-settings`` body, in ``PUT`` shape."""
    return [connection_for_put(entry) for entry in as_list(as_dict(raw).get("connections")) if isinstance(entry, dict)]
