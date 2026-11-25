"""DriveQuery: read-only GraphQL fields for UniFi Drive.

Each field calls the same core manager method as the REST route and the
action, through :func:`unifi_api.services.drive.read_drive`, so a failure maps
to the same fixed text; here it surfaces as a GraphQL error code. Drive lists
are returned whole: Drive does not page them. Writes are actions only.
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.types import Info

from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.drive._base import DESCRIPTION
from unifi_api.graphql.types.drive.file_services import DriveFileServices, DriveNfsConnection
from unifi_api.graphql.types.drive.shared_drives import DriveSharedDrive
from unifi_api.graphql.types.drive.storage import DriveDisk, DriveStoragePool
from unifi_api.graphql.types.drive.system import DriveSystemInfo
from unifi_api.services.controllers import get_controller
from unifi_api.services.drive import ID_FAMILY, PRODUCT, map_drive_error, read_drive
from unifi_api.services.incident_evidence import require_product


async def _read(
    info: Info,
    controller: str,
    *,
    manager_attr: str,
    method: str,
    operation: str,
    args: tuple[Any, ...] = (),
    **kwargs: Any,
) -> Any:
    ctx: GraphQLContext = info.context
    async with ctx.sessionmaker() as session:
        row = await get_controller(session, str(controller))
    require_product(row, PRODUCT)
    key = f"drive/{controller}/{manager_attr}.{method}/{args!r}/{sorted(kwargs.items())!r}"

    async def _fetch() -> Any:
        return await read_drive(
            sessionmaker=ctx.sessionmaker,
            factory=ctx.manager_factory,
            controller_id=str(controller),
            manager_attr=manager_attr,
            method=method,
            operation=operation,
            args=args,
            kwargs=kwargs,
        )

    return await ctx.cache.get_or_fetch(key, _fetch)


def _project(info: Info, type_class: type, obj: Any, operation: str) -> Any:
    """Project one result; a result it cannot project maps like any other read failure."""
    ctx: GraphQLContext = info.context
    try:
        return type_class.from_manager_output(obj, redact_sensitive=ctx.redact_sensitive_fields)
    except Exception as exc:
        raise map_drive_error(exc, operation) from None


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

    @strawberry.field(permission_classes=[IsRead], description=f"Storage pools and their RAID groups. {DESCRIPTION}")
    async def storage_pools(self, info: Info, controller: strawberry.ID) -> list[DriveStoragePool]:
        operation = "list Drive storage pools"
        result = await _read(info, controller, manager_attr="storage_manager", method="list_pools", operation=operation)
        return [_project(info, DriveStoragePool, pool, operation) for pool in result]

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
