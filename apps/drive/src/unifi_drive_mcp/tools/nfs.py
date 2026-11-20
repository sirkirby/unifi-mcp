"""NFS client connection tools for the UniFi Drive MCP server.

Drive stores every NFS client in one list and its API replaces the list as a
whole. Each tool here reads the list, changes one client and writes the list
back with every other client unchanged. A confirmed write plans again from
fresh state under the manager's NFS lock, so concurrent writes from this server
run one after the other instead of dropping each other's clients.

The lock only covers this process. Drive keeps no version on the list, so a
write from another process (a second MCP server, or the API server, pointed at
the same NAS) that lands between the last re-read and the ``PUT`` is
overwritten without either call reporting it.
"""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter, ValidationError

from unifi_core.confirmation import create_preview, delete_preview, update_preview
from unifi_core.drive.managers.file_service_manager import NfsChange
from unifi_core.drive.models.services import NfsConnectionInput, NfsSharedDriveAccess
from unifi_core.exceptions import UniFiNotFoundError, UniFiValidationError
from unifi_drive_mcp.runtime import file_service_manager, server, tool_failure, tool_success

logger = logging.getLogger(__name__)

_GRANTS = TypeAdapter(List[NfsSharedDriveAccess])

_ADD_SHARED_DRIVES_DESCRIPTION = (
    'Shared drives the client may mount, e.g. [{"id": "<shared drive id>", "permission": "rw"}]. '
    "permission is rw (read-write, default) or ro (read-only). IDs come from drive_list_shared_drives."
)
_UPDATE_SHARED_DRIVES_DESCRIPTION = (
    'The client\'s new shared drive list, e.g. [{"id": "<shared drive id>", "permission": "ro"}]. It replaces '
    "the whole list. A drive the client already has keeps its current permission when permission is left "
    "out; a newly granted drive defaults to rw. IDs come from drive_list_shared_drives."
)


def _invalid(exc: ValidationError) -> Dict[str, Any]:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first.get("loc", ()))
    return {"success": False, "error": f"Invalid input{f' ({where})' if where else ''}: {first['msg']}"}


def _with_preview_context(response: Dict[str, Any], change: NfsChange) -> Dict[str, Any]:
    response["preview"]["unchanged_connections"] = change.unchanged_clients
    if change.warnings:
        response["warnings"] = [*response.get("warnings", []), *change.warnings]
    return response


@server.tool(
    name="drive_list_nfs_connections",
    description=(
        "Lists the NFS clients allowed to mount shared drives, with the shared drives each may mount and "
        "the export path to mount. NFS here is NFSv3 and maps every client user to one Drive user "
        "(no squash option)."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="nfs_connection",
    permission_action="read",
)
async def drive_list_nfs_connections() -> Dict[str, Any]:
    """List NFS client connections."""
    try:
        connections = await file_service_manager.list_nfs_connections()
        return tool_success(
            {
                "connections": [connection.model_dump(exclude_none=True) for connection in connections],
                "count": len(connections),
            }
        )
    except Exception as exc:
        return tool_failure("list NFS connections", exc)


@server.tool(
    name="drive_add_nfs_connection",
    description=(
        "Allows a new NFS client (IP address or hostname) to mount one or more shared drives. Other "
        "clients are kept as they are. Drive checks the client name before saving. "
        "Requires confirm=true to execute; without it, returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="nfs_connection",
    permission_action="create",
)
async def drive_add_nfs_connection(
    client: Annotated[str, Field(description="Client IP address or hostname allowed to mount")],
    shared_drives: Annotated[List[NfsSharedDriveAccess], Field(description=_ADD_SHARED_DRIVES_DESCRIPTION)],
    async_writes: Annotated[
        bool, Field(description="Use async writes: faster, but writes can be lost on a NAS power loss (default false)")
    ] = False,
    confirm: Annotated[
        bool, Field(description="When true, saves the connection. When false (default), returns a preview.")
    ] = False,
) -> Dict[str, Any]:
    """Add an NFS client connection, with preview/confirm."""
    try:
        connection = NfsConnectionInput(client=client, shared_drives=shared_drives, async_writes=async_writes)
    except ValidationError as exc:
        return _invalid(exc)
    try:
        if confirm:
            _, saved = await file_service_manager.add_nfs_connection(connection)
            return tool_success({"connection": saved.model_dump(exclude_none=True) if saved else None})
        change = await file_service_manager.plan_add_nfs_connection(connection)
        preview = create_preview(
            resource_type="nfs_connection",
            resource_data=change.after.model_dump(exclude_none=True) if change.after else {},
            resource_name=change.client,
        )
        return _with_preview_context(preview, change)
    except UniFiValidationError as exc:
        return {"success": False, "error": f"Failed to add NFS connection: {exc}"}
    except Exception as exc:
        return tool_failure("add NFS connection", exc)


@server.tool(
    name="drive_update_nfs_connection",
    description=(
        "Changes an existing NFS client's shared drives and/or async writes. Pass only the fields you want "
        "to change — current values are automatically preserved. shared_drives, when passed, replaces the "
        "client's whole list. Other clients are kept as they are. "
        "Requires confirm=true to execute; without it, returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="nfs_connection",
    permission_action="update",
)
async def drive_update_nfs_connection(
    client: Annotated[str, Field(description="The client's IP address or hostname, as listed")],
    shared_drives: Annotated[
        Optional[List[NfsSharedDriveAccess]], Field(description=_UPDATE_SHARED_DRIVES_DESCRIPTION)
    ] = None,
    async_writes: Annotated[Optional[bool], Field(description="Use async writes")] = None,
    confirm: Annotated[
        bool, Field(description="When true, saves the change. When false (default), returns a preview.")
    ] = False,
) -> Dict[str, Any]:
    """Update an NFS client connection, with preview/confirm."""
    try:
        grants = _GRANTS.validate_python(shared_drives) if shared_drives is not None else None
    except ValidationError as exc:
        return _invalid(exc)
    try:
        if confirm:
            _, saved = await file_service_manager.update_nfs_connection(
                client, shared_drives=grants, async_writes=async_writes
            )
            return tool_success({"connection": saved.model_dump(exclude_none=True) if saved else None})
        change = await file_service_manager.plan_update_nfs_connection(
            client, shared_drives=grants, async_writes=async_writes
        )
        current = change.before.model_dump(exclude_none=True) if change.before else {}
        proposed = change.after.model_dump(exclude_none=True) if change.after else {}
        updates = {key: proposed.get(key) for key in ("shared_drives", "async_writes")}
        preview = update_preview(
            resource_type="nfs_connection",
            resource_id=change.client,
            resource_name=change.client,
            current_state=current,
            updates=updates,
        )
        return _with_preview_context(preview, change)
    except (UniFiNotFoundError, UniFiValidationError) as exc:
        return {"success": False, "error": f"Failed to update NFS connection: {exc}"}
    except Exception as exc:
        return tool_failure("update NFS connection", exc)


@server.tool(
    name="drive_remove_nfs_connection",
    description=(
        "Removes an NFS client, so it can no longer mount any shared drive. Other clients are kept as "
        "they are. No data on the shared drives is touched. "
        "Requires confirm=true to execute; without it, returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="nfs_connection",
    permission_action="delete",
)
async def drive_remove_nfs_connection(
    client: Annotated[str, Field(description="The client's IP address or hostname, as listed")],
    confirm: Annotated[
        bool, Field(description="When true, removes the connection. When false (default), returns a preview.")
    ] = False,
) -> Dict[str, Any]:
    """Remove an NFS client connection, with preview/confirm."""
    try:
        if confirm:
            change = await file_service_manager.remove_nfs_connection(client)
            return tool_success({"removed": change.client})
        change = await file_service_manager.plan_remove_nfs_connection(client)
        preview = delete_preview(
            resource_type="nfs_connection",
            resource_id=change.client,
            resource_name=change.client,
            resource_data=change.before.model_dump(exclude_none=True) if change.before else None,
        )
        return _with_preview_context(preview, change)
    except (UniFiNotFoundError, UniFiValidationError) as exc:
        return {"success": False, "error": f"Failed to remove NFS connection: {exc}"}
    except Exception as exc:
        return tool_failure("remove NFS connection", exc)
