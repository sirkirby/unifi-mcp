"""UniFi Drive file services (SMB, NFS, Time Machine) and NFS client connections."""

from __future__ import annotations

import strawberry
from strawberry.scalars import JSON

from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class DriveNetworkInterface(Projection):
    name: str | None = strawberry.field(description="Interface name, such as enp0s0")
    interface: str | None = strawberry.field(description="Port type, such as ethernet or sfp+")
    connected: bool | None = strawberry.field(description="Whether the link is up")
    link_speed: str | None = strawberry.field(description="Negotiated link speed, such as 10 GbE")
    max_speed: str | None = strawberry.field(description="Maximum link speed of the port")
    address: str | None = strawberry.field(description="IP address clients connect to")
    mac: str | None = strawberry.field(description="Interface MAC address")


@strawberry.type(description=DESCRIPTION)
class DriveFileServices(Projection):
    smb_enabled: bool | None = strawberry.field(description="Whether SMB is enabled")
    nfs_enabled: bool | None = strawberry.field(description="Whether NFS is enabled")
    time_machine_enabled: bool | None = strawberry.field(
        description="Whether Time Machine (over SMB) is enabled; it requires SMB"
    )
    custom_domain: str | None = strawberry.field(description="Custom domain clients use, if one is set")
    network_interfaces: list[DriveNetworkInterface] | None = strawberry.field(
        description="Interfaces clients can connect to"
    )

    _nested = {"network_interfaces": (DriveNetworkInterface, True)}
    _columns = ["smb_enabled", "nfs_enabled", "time_machine_enabled"]


@strawberry.type(description=DESCRIPTION)
class DriveNfsSharedDriveGrant(Projection):
    id: str | None = strawberry.field(description="Shared drive id")
    name: str | None = strawberry.field(description="Shared drive name")
    status: str | None = strawberry.field(description="Shared drive status")
    encryption_status: str | None = strawberry.field(description="Shared drive encryption status")
    permission: str | None = strawberry.field(description="rw (read-write) or ro (read-only)")
    export_path: str | None = strawberry.field(description="Path a client mounts, <nas>:<export_path>")


@strawberry.type(description=DESCRIPTION)
class DriveNfsConnection(Projection):
    client: str | None = strawberry.field(description="Client IP address or hostname")
    async_writes: bool | None = strawberry.field(description="Whether the export uses async writes")
    shared_drives: list[DriveNfsSharedDriveGrant] | None = strawberry.field(description="Shared drives it may mount")
    error_codes: JSON | None = strawberry.field(
        description="Problems Drive reports for this connection, such as an unresolvable hostname"
    )

    _nested = {"shared_drives": (DriveNfsSharedDriveGrant, True)}
    _identity = "client"
    _columns = ["client", "async_writes"]
