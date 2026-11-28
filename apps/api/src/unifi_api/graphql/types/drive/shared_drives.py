"""UniFi Drive shared drives."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.scalars import BigInt
from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class DriveSharedDrive(Projection):
    id: str | None = strawberry.field(
        description="Shared drive id. Pass it as shared_drives[].id to the drive_*_nfs_connection actions."
    )
    name: str | None = strawberry.field(description="Shared drive name; NFS exports it as /var/nfs/shared/<name>")
    type: str | None = strawberry.field(description="Drive type, such as shared")
    status: str | None = strawberry.field(description="Drive status, such as active")
    storage_pool_id: str | None = strawberry.field(description="Storage pool the drive lives on")
    quota_bytes: BigInt | None = strawberry.field(description="Quota in bytes; absent when unlimited")
    used_bytes: BigInt | None = strawberry.field(description="Space used in bytes")
    role: str | None = strawberry.field(description="The logged-in account's role on the drive")
    member_count: int | None = strawberry.field(description="Number of members with access")
    encryption_status: str | None = strawberry.field(description="Encryption status, such as unencrypted")
    snapshot_enabled: bool | None = strawberry.field(description="Whether snapshots are enabled")
    remote_backup_enabled: bool | None = strawberry.field(description="Whether remote backup is enabled")

    _identity = "id"
    _columns = ["name", "type", "status", "used_bytes"]
