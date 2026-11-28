"""The UniFi Drive read projections: tool type and REST resource for each."""

from unifi_api.graphql.types.drive.file_services import (
    DriveFileServices,
    DriveNfsConnection,
    DriveRsyncSettings,
    DriveSmbAdvancedSettings,
)
from unifi_api.graphql.types.drive.logs import DriveLogPage
from unifi_api.graphql.types.drive.performance import DriveDiskStats, DriveFanProfile, DriveNetworkThroughput
from unifi_api.graphql.types.drive.shared_drives import DriveSharedDrive
from unifi_api.graphql.types.drive.snapshots import DriveSnapshot, DriveSnapshotOverview
from unifi_api.graphql.types.drive.storage import DriveDisk, DriveStoragePool, DriveStoragePoolUsage
from unifi_api.graphql.types.drive.system import DriveSystemInfo
from unifi_api.graphql.types.drive.users import DriveGroup, DriveUser

# tool -> (resource path under /v1/sites/{site_id}/, projection, kind)
REGISTRATIONS = {
    "drive_get_system_info": ("drive/system", DriveSystemInfo, "detail"),
    "drive_list_logs": ("drive/logs", DriveLogPage, "detail"),
    "drive_list_storage_pools": ("drive/storage-pools", DriveStoragePool, "list"),
    "drive_get_storage_usage": ("drive/storage-usage", DriveStoragePoolUsage, "list"),
    "drive_list_disks": ("drive/disks", DriveDisk, "list"),
    "drive_get_network_throughput": ("drive/network-throughput", DriveNetworkThroughput, "detail"),
    "drive_get_fan_profile": ("drive/fan-profile", DriveFanProfile, "detail"),
    "drive_get_disk_stats": ("drive/disk-stats", DriveDiskStats, "detail"),
    "drive_list_shared_drives": ("drive/shared-drives", DriveSharedDrive, "list"),
    "drive_get_shared_drive": ("drive/shared-drives/{drive_id}", DriveSharedDrive, "detail"),
    "drive_get_snapshot_overview": ("drive/snapshot-overview", DriveSnapshotOverview, "detail"),
    "drive_list_snapshots": ("drive/snapshots/shared/{shared_drive_name}", DriveSnapshot, "list"),
    "drive_get_file_services": ("drive/file-services", DriveFileServices, "detail"),
    "drive_get_smb_advanced_settings": ("drive/smb-advanced-settings", DriveSmbAdvancedSettings, "detail"),
    "drive_get_rsync_settings": ("drive/rsync-settings", DriveRsyncSettings, "detail"),
    "drive_list_nfs_connections": ("drive/nfs-connections", DriveNfsConnection, "list"),
    "drive_list_users": ("drive/users", DriveUser, "list"),
    "drive_list_groups": ("drive/groups", DriveGroup, "list"),
}


def register_types(registry):
    for name, (resource, projection, kind) in REGISTRATIONS.items():
        registry.register_tool_type(name, projection, kind)
        registry.register_type("drive", resource, projection)
