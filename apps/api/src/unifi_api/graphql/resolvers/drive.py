"""DriveQuery: read-only GraphQL fields for UniFi Drive.

Each field calls the same core manager method as the REST route and the
action, through :func:`unifi_api.services.console_product.read`, so a failure maps
to the same fixed text; here it surfaces as a GraphQL error code. Drive lists
are returned whole: Drive does not page them, except the system log, which
pages by cursor. Disk stats carry each disk's samples, which a query selects
only when it needs them. Writes are actions only.
"""

from __future__ import annotations

import strawberry
from strawberry.types import Info
from unifi_core.drive.models.logs import DEFAULT_LOG_LIMIT

from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.resolvers._console_product import ConsoleQueries
from unifi_api.graphql.types.drive._base import DESCRIPTION
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
from unifi_api.services.drive import DRIVE, ID_FAMILY, log_query

_queries = ConsoleQueries(DRIVE)
_read = _queries.read
_project = _queries.project


@strawberry.type(description=f"Read-only access to UniFi Drive resources. {ID_FAMILY}")
class DriveQuery:
    @strawberry.field(
        permission_classes=[IsRead],
        description=f"Identity, firmware and health of the NAS console. {DESCRIPTION}",
    )
    async def system_info(self, info: Info, controller: strawberry.ID) -> DriveSystemInfo:
        operation = "get Drive system info"
        result = await _read(
            info, controller, manager_attr="system_manager", method="get_system_info", operation=operation
        )
        return _project(info, DriveSystemInfo, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "One page of the NAS's system log, newest first. Pass nextCursor back as cursor, with the same "
            f"filters, for the next page. {DESCRIPTION}"
        ),
    )
    async def logs(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = DEFAULT_LOG_LIMIT,
        severities: list[str] | None = None,
        category: str | None = None,
        types: list[str] | None = None,
        keyword: str | None = None,
        scope: str | None = None,
        after: str | None = None,
        before: str | None = None,
        cursor: str | None = None,
    ) -> DriveLogPage:
        operation = "list Drive system log entries"
        query = log_query(
            operation,
            limit=limit,
            severities=severities,
            category=category,
            types=types,
            keyword=keyword,
            scope=scope,
            after=after,
            before=before,
            cursor=cursor,
        )
        result = await _read(
            info, controller, manager_attr="log_manager", method="list_logs", operation=operation, args=(query,)
        )
        return _project(info, DriveLogPage, result, operation)

    @strawberry.field(permission_classes=[IsRead], description=f"Storage pools and their RAID groups. {DESCRIPTION}")
    async def storage_pools(self, info: Info, controller: strawberry.ID) -> list[DriveStoragePool]:
        operation = "list Drive storage pools"
        result = await _read(info, controller, manager_attr="storage_manager", method="list_pools", operation=operation)
        return [_project(info, DriveStoragePool, pool, operation) for pool in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"Each storage pool's used space, split by what uses it. {DESCRIPTION}",
    )
    async def storage_usage(self, info: Info, controller: strawberry.ID) -> list[DriveStoragePoolUsage]:
        operation = "get Drive storage usage"
        result = await _read(info, controller, manager_attr="storage_manager", method="get_usage", operation=operation)
        return [_project(info, DriveStoragePoolUsage, pool, operation) for pool in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"Drive bays and SSD cache slots with the disk in each and its SMART health. {DESCRIPTION}",
    )
    async def disks(
        self,
        info: Info,
        controller: strawberry.ID,
        include_empty: bool = False,
        include_cache: bool = True,
    ) -> list[DriveDisk]:
        operation = "list Drive disks"
        result = await _read(
            info,
            controller,
            manager_attr="storage_manager",
            method="list_disks",
            operation=operation,
            include_empty=include_empty,
            include_cache=include_cache,
        )
        return [_project(info, DriveDisk, disk, operation) for disk in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"The NAS's network throughput right now, in KB/s. {DESCRIPTION}",
    )
    async def network_throughput(self, info: Info, controller: strawberry.ID) -> DriveNetworkThroughput:
        operation = "get Drive network throughput"
        result = await _read(
            info, controller, manager_attr="performance_manager", method="get_network_throughput", operation=operation
        )
        return _project(info, DriveNetworkThroughput, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"The NAS's fan mode and the modes it offers. {DESCRIPTION}",
    )
    async def fan_profile(self, info: Info, controller: strawberry.ID) -> DriveFanProfile:
        operation = "get Drive fan profile"
        result = await _read(
            info, controller, manager_attr="performance_manager", method="get_fan_profile", operation=operation
        )
        return _project(info, DriveFanProfile, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "Each disk's temperature, throughput and bad sectors over the last hours (1 to 2160), summarized per "
            f"disk, with per-bucket samples a query selects only when it needs them. {DESCRIPTION}"
        ),
    )
    async def disk_stats(self, info: Info, controller: strawberry.ID, hours: int = 24) -> DriveDiskStats:
        operation = "get Drive disk stats"
        result = await _read(
            info,
            controller,
            manager_attr="performance_manager",
            method="get_disk_stats",
            operation=operation,
            hours=hours,
        )
        return _project(info, DriveDiskStats, result, operation)

    @strawberry.field(permission_classes=[IsRead], description=f"Shared drives. {DESCRIPTION}")
    async def shared_drives(self, info: Info, controller: strawberry.ID) -> list[DriveSharedDrive]:
        operation = "list Drive shared drives"
        result = await _read(
            info, controller, manager_attr="shared_drive_manager", method="list_shared_drives", operation=operation
        )
        return [_project(info, DriveSharedDrive, drive, operation) for drive in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "One shared drive by id. Drive omits the protection flags and member count that the list includes. "
            f"{DESCRIPTION}"
        ),
    )
    async def shared_drive(self, info: Info, controller: strawberry.ID, drive_id: str) -> DriveSharedDrive:
        operation = "get Drive shared drive"
        result = await _read(
            info,
            controller,
            manager_attr="shared_drive_manager",
            method="get_shared_drive",
            operation=operation,
            args=(drive_id,),
        )
        return _project(info, DriveSharedDrive, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"Every shared and personal drive's snapshot settings and state. {DESCRIPTION}",
    )
    async def snapshot_overview(self, info: Info, controller: strawberry.ID) -> DriveSnapshotOverview:
        operation = "get Drive snapshot overview"
        result = await _read(
            info, controller, manager_attr="snapshot_manager", method="get_snapshot_overview", operation=operation
        )
        return _project(info, DriveSnapshotOverview, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            f"One shared drive's snapshots, newest first, by the shared drive's name, not its id. {DESCRIPTION}"
        ),
    )
    async def snapshots(self, info: Info, controller: strawberry.ID, shared_drive_name: str) -> list[DriveSnapshot]:
        operation = "list Drive snapshots"
        result = await _read(
            info,
            controller,
            manager_attr="snapshot_manager",
            method="list_snapshots",
            operation=operation,
            args=(shared_drive_name,),
        )
        return [_project(info, DriveSnapshot, snapshot, operation) for snapshot in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"Whether SMB, NFS and Time Machine are on, and the interfaces clients connect to. {DESCRIPTION}",
    )
    async def file_services(self, info: Info, controller: strawberry.ID) -> DriveFileServices:
        operation = "get Drive file services"
        result = await _read(
            info, controller, manager_attr="file_service_manager", method="get_file_services", operation=operation
        )
        return _project(info, DriveFileServices, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"NFS clients allowed to mount shared drives, with their export paths. {DESCRIPTION}",
    )
    async def nfs_connections(self, info: Info, controller: strawberry.ID) -> list[DriveNfsConnection]:
        operation = "list Drive NFS connections"
        result = await _read(
            info, controller, manager_attr="file_service_manager", method="list_nfs_connections", operation=operation
        )
        return [_project(info, DriveNfsConnection, connection, operation) for connection in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            f"Whether SMB Trash for personal drives is on, and whether every personal drive could move to it. "
            f"{DESCRIPTION}"
        ),
    )
    async def smb_advanced_settings(self, info: Info, controller: strawberry.ID) -> DriveSmbAdvancedSettings:
        operation = "get Drive SMB advanced settings"
        result = await _read(
            info,
            controller,
            manager_attr="file_service_manager",
            method="get_smb_advanced_settings",
            operation=operation,
        )
        return _project(info, DriveSmbAdvancedSettings, result, operation)

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"The rsync service, its account (never its password) and whether SSH is on. {DESCRIPTION}",
    )
    async def rsync_settings(self, info: Info, controller: strawberry.ID) -> DriveRsyncSettings:
        operation = "get Drive rsync settings"
        result = await _read(
            info, controller, manager_attr="file_service_manager", method="get_rsync_settings", operation=operation
        )
        return _project(info, DriveRsyncSettings, result, operation)

    @strawberry.field(permission_classes=[IsRead], description=f"The NAS's users. {DESCRIPTION}")
    async def users(self, info: Info, controller: strawberry.ID) -> list[DriveUser]:
        operation = "list Drive users"
        result = await _read(info, controller, manager_attr="user_manager", method="list_users", operation=operation)
        return [_project(info, DriveUser, user, operation) for user in result]

    @strawberry.field(
        permission_classes=[IsRead],
        description=f"The UniFi OS user groups that shared drive access can be granted to. {DESCRIPTION}",
    )
    async def groups(self, info: Info, controller: strawberry.ID) -> list[DriveGroup]:
        operation = "list Drive user groups"
        result = await _read(info, controller, manager_attr="user_manager", method="list_groups", operation=operation)
        return [_project(info, DriveGroup, group, operation) for group in result]
