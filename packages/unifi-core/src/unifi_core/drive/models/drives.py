"""Shared drives from ``GET /proxy/drive/api/v2/drives``."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from unifi_core.drive.models._coerce import as_dict, flag, number, text


class SharedDrive(BaseModel):
    """A shared drive (Drive's name for a share)."""

    model_config = ConfigDict(extra="ignore")

    id: str | None = Field(
        default=None,
        description=(
            "Shared drive id. Pass it as shared_drives[].id to the drive_*_nfs_connection tools. "
            "These IDs are scoped to the UniFi Drive tool family."
        ),
    )
    name: str | None = Field(default=None, description="Shared drive name; NFS exports it as /var/nfs/shared/<name>")
    type: str | None = Field(default=None, description="Drive type, such as shared")
    status: str | None = Field(default=None, description="Drive status, such as active")
    storage_pool_id: str | None = Field(default=None, description="Storage pool the drive lives on")
    quota_bytes: int | None = Field(default=None, description="Quota in bytes; absent when unlimited")
    used_bytes: int | None = Field(default=None, description="Space used in bytes")
    role: str | None = Field(default=None, description="The logged-in account's role on the drive")
    member_count: int | None = Field(default=None, description="Number of members with access")
    encryption_status: str | None = Field(default=None, description="Encryption status, such as unencrypted")
    snapshot_enabled: bool | None = Field(default=None, description="Whether snapshots are enabled")
    remote_backup_enabled: bool | None = Field(default=None, description="Whether remote backup is enabled")


def shared_drive_from_api(raw: Any) -> SharedDrive:
    drive = as_dict(raw)
    protections = as_dict(drive.get("protections"))
    quota = number(drive.get("quota"))
    used = number(drive.get("usage"))
    members = number(drive.get("memberCount"))
    return SharedDrive(
        id=text(drive.get("id")),
        name=text(drive.get("name")),
        type=text(drive.get("type")),
        status=text(drive.get("status")),
        storage_pool_id=text(drive.get("storagePoolId")),
        # Drive reports an unlimited quota as -1.
        quota_bytes=int(quota) if quota is not None and quota >= 0 else None,
        used_bytes=int(used) if used is not None else None,
        role=text(drive.get("role")),
        member_count=int(members) if members is not None else None,
        encryption_status=text(protections.get("encryptionStatus")),
        snapshot_enabled=flag(protections.get("snapshotEnabled")),
        remote_backup_enabled=flag(protections.get("remoteBackupEnabled")),
    )
