"""Wall type tools: create and update the project's custom wall materials.

Remaining race: the write lock is per process. An update sends the wall type
whole from the fresh read, so a change that another server process or the
browser editor makes to the same type between that read and the write is
overwritten silently.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_innerspace_mcp.arguments import (
    CONFIRM_FLOW,
    FAMILY,
    PARTIAL_UPDATE,
    AttenuationDb,
    Color,
    Confirm,
    ConfirmCreate,
    NewAttenuationDb,
    NewColor,
    NewTypeName,
    TypeName,
    input_schema,
)
from unifi_innerspace_mcp.runtime import server, wall_type_manager, write_failure, write_preview, write_result

logger = logging.getLogger(__name__)

WallTypeId = Annotated[str, Field(description=f"Wall type id, from innerspace_get_project. {FAMILY}")]
Transparent = Annotated[bool, Field(description="Whether the wall is drawn see-through.")]
NewTransparent = Annotated[bool | None, Field(description="Whether the wall is drawn see-through. Omit to keep.")]


@server.tool(
    name="innerspace_create_wall_type",
    input_schema=input_schema(
        name=TypeName,
        attenuation_db=AttenuationDb,
        color=Color,
        transparent=(Transparent, False),
        confirm=(ConfirmCreate, False),
    ),
    title="Create InnerSpace Wall Type",
    description=(
        'Creates a project wall type (a custom material). Walls use it with variant "custom" and its id. '
        + CONFIRM_FLOW
        + " "
        + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="wall_types",
    permission_action="create",
    auth="local_only",
)
async def innerspace_create_wall_type(
    name: TypeName,
    attenuation_db: AttenuationDb,
    color: Color,
    transparent: Transparent = False,
    confirm: ConfirmCreate = False,
) -> Dict[str, Any]:
    """Preview or create a wall type."""
    logger.info("innerspace_create_wall_type tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(
                await wall_type_manager.preview_create_wall_type(name, attenuation_db, color, transparent=transparent)
            )
        result = await wall_type_manager.apply_create_wall_type(name, attenuation_db, color, transparent=transparent)
        return write_result(result, applied="Wall type created and read back.")
    except Exception as e:
        return write_failure("create InnerSpace wall type", e)


@server.tool(
    name="innerspace_update_wall_type",
    input_schema=input_schema(
        wall_type_id=WallTypeId,
        name=(NewTypeName, None),
        attenuation_db=(NewAttenuationDb, None),
        color=(NewColor, None),
        transparent=(NewTransparent, None),
        confirm=(Confirm, False),
    ),
    title="Update InnerSpace Wall Type",
    description=(
        "Changes a project wall type. The change applies to every wall that uses it, on every plan; the preview "
        "counts them. " + PARTIAL_UPDATE + " " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="wall_types",
    permission_action="update",
    auth="local_only",
)
async def innerspace_update_wall_type(
    wall_type_id: WallTypeId,
    name: NewTypeName = None,
    attenuation_db: NewAttenuationDb = None,
    color: NewColor = None,
    transparent: NewTransparent = None,
    confirm: Confirm = False,
) -> Dict[str, Any]:
    """Preview or update a wall type."""
    logger.info("innerspace_update_wall_type tool called (confirm=%s)", confirm)
    changes = dict(name=name, attenuation_db=attenuation_db, color=color, transparent=transparent)
    try:
        if not confirm:
            return write_preview(await wall_type_manager.preview_update_wall_type(wall_type_id, **changes))
        result = await wall_type_manager.apply_update_wall_type(wall_type_id, **changes)
        return write_result(result, applied="Wall type updated and read back.")
    except Exception as e:
        return write_failure("update InnerSpace wall type", e)
