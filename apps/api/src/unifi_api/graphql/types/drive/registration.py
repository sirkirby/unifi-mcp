"""The seven UniFi Drive read projections: tool type and REST resource for each."""

from unifi_api.graphql.types.drive.file_services import DriveFileServices, DriveNfsConnection
from unifi_api.graphql.types.drive.shared_drives import DriveSharedDrive
from unifi_api.graphql.types.drive.storage import DriveDisk, DriveStoragePool
from unifi_api.graphql.types.drive.system import DriveSystemInfo

# tool -> (resource path under /v1/sites/{site_id}/, projection, kind)
REGISTRATIONS = {
    "drive_get_system_info": ("drive/system", DriveSystemInfo, "detail"),
    "drive_list_storage_pools": ("drive/storage-pools", DriveStoragePool, "list"),
    "drive_list_disks": ("drive/disks", DriveDisk, "list"),
    "drive_list_shared_drives": ("drive/shared-drives", DriveSharedDrive, "list"),
    "drive_get_shared_drive": ("drive/shared-drives/{drive_id}", DriveSharedDrive, "detail"),
    "drive_get_file_services": ("drive/file-services", DriveFileServices, "detail"),
    "drive_list_nfs_connections": ("drive/nfs-connections", DriveNfsConnection, "list"),
}


def register_types(registry):
    for name, (resource, projection, kind) in REGISTRATIONS.items():
        registry.register_tool_type(name, projection, kind)
        registry.register_type("drive", resource, projection)
