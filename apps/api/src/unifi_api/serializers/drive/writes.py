"""Drive write acknowledgements: the same ``data`` the Drive MCP server returns for a confirmed write.

Only confirmed writes reach these serializers; a preview is answered before any
manager is called. A write that stopped before its change was sent, or was sent
and never answered, raises instead and is answered by the action route with
``mutation_applied`` false or null, never as a success.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from unifi_api.serializers._base import RenderKind, Serializer, SerializerContractError, register_serializer

WRITE_TOOLS = (
    "drive_set_file_service",
    "drive_add_nfs_connection",
    "drive_update_nfs_connection",
    "drive_remove_nfs_connection",
)


def _connection(saved: Any) -> dict[str, Any] | None:
    if saved is None:
        return None
    if not isinstance(saved, BaseModel):
        raise SerializerContractError(f"NFS write read back {type(saved).__name__}, not a connection")
    return saved.model_dump(exclude_none=True)


def _data(tool_name: str, result: Any) -> dict[str, Any]:
    if tool_name == "drive_set_file_service":
        if not (isinstance(result, tuple) and len(result) == 2):
            raise SerializerContractError(f"tool '{tool_name}' returned {type(result).__name__}, not (change, state)")
        change, enabled = result
        return {"service": change.service, "enabled": enabled, "changed": change.changes_anything}
    if tool_name in ("drive_add_nfs_connection", "drive_update_nfs_connection"):
        if not (isinstance(result, tuple) and len(result) == 2):
            raise SerializerContractError(
                f"tool '{tool_name}' returned {type(result).__name__}, not (change, connection)"
            )
        return {"connection": _connection(result[1])}
    if tool_name == "drive_remove_nfs_connection":
        client = getattr(result, "client", None)
        if not isinstance(client, str):
            raise SerializerContractError(f"tool '{tool_name}' returned {type(result).__name__}, not an NFS change")
        return {"removed": client}
    raise SerializerContractError(f"tool '{tool_name}' is not a Drive write")


@register_serializer(tools={name: {"kind": RenderKind.DETAIL} for name in WRITE_TOOLS})
class DriveWriteSerializer(Serializer):
    """The confirmed write's result, read back from the NAS, shaped as on the MCP server."""

    @staticmethod
    def serialize(obj: Any) -> dict:
        raise SerializerContractError("Drive writes are shaped per tool")

    def serialize_action(self, result: Any, *, tool_name: str, redact_sensitive: bool = True) -> dict:
        return {
            "success": True,
            "data": self._redact(_data(tool_name, result), redact_sensitive=redact_sensitive),
            "render_hint": self._render_hint(self._kind_for_tool(tool_name)),
        }
