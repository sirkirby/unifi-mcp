"""Attenuation tools: the attenuation objects of one floor plan, and the project's attenuation-object types.

Remaining race: the write lock is per process. An update sends each object or
type whole from the fresh read, so a change that another server process or the
browser editor makes to the same object or type between that read and the
write is overwritten silently.
"""

import logging
from typing import Annotated, Any, Dict

from mcp.types import ToolAnnotations
from pydantic import Field

from unifi_core.innerspace.models.writes import (
    MAX_CREATE,
    MAX_REMOVE,
    MAX_UPDATE,
    AttenuationObjectCreate,
    AttenuationObjectUpdate,
)
from unifi_innerspace_mcp.arguments import (
    CONFIRM_FLOW,
    FAMILY,
    PARTIAL_UPDATE,
    AttenuationDb,
    Color,
    Confirm,
    ConfirmCreate,
    Coordinates,
    NewAttenuationDb,
    NewColor,
    NewTypeName,
    PlanId,
    TypeName,
    WriteUnit,
    id_list,
    input_schema,
    item_list,
)
from unifi_innerspace_mcp.runtime import attenuation_manager, server, write_failure, write_preview, write_result

logger = logging.getLogger(__name__)

ObjectsToCreate = item_list(
    AttenuationObjectCreate,
    "Attenuation objects to create, at most 100: each a closed polygon (points x, y in unit, 4 to 100 points, "
    'the last repeating the first) and a variant; variant "custom" takes an attenuation_object_type_id.',
    MAX_CREATE,
)
ObjectsToUpdate = item_list(
    AttenuationObjectUpdate,
    "Attenuation objects to update, at most 100: each names its id and only the fields to change. points "
    'replaces the whole polygon; variant "custom" takes an attenuation_object_type_id. Each object is sent whole '
    "from a fresh read, so an edit made elsewhere to the same object after that read is overwritten; an object "
    "that is gone or moved to another plan is refused and nothing is sent.",
    MAX_UPDATE,
)
ObjectIds = id_list("attenuation objects", MAX_REMOVE)
ObjectTypeId = Annotated[str, Field(description=f"Attenuation-object type id, from innerspace_get_project. {FAMILY}")]


@server.tool(
    name="innerspace_create_attenuation_objects",
    input_schema=input_schema(
        plan_id=PlanId,
        objects=ObjectsToCreate,
        unit=WriteUnit,
        coordinates=(Coordinates, "frame"),
        confirm=(ConfirmCreate, False),
    ),
    title="Create InnerSpace Attenuation Objects",
    description=(
        "Creates attenuation objects (areas that weaken the signal, such as shelving or a car) on one floor plan. "
        + CONFIRM_FLOW
        + " "
        + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="attenuation",
    permission_action="create",
    auth="local_only",
)
async def innerspace_create_attenuation_objects(
    plan_id: PlanId,
    objects: ObjectsToCreate,
    unit: WriteUnit,
    coordinates: Coordinates = "frame",
    confirm: ConfirmCreate = False,
) -> Dict[str, Any]:
    """Preview or create attenuation objects."""
    logger.info("innerspace_create_attenuation_objects tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(
                await attenuation_manager.preview_create_attenuation_objects(
                    plan_id, objects, unit=unit, coordinates=coordinates
                )
            )
        result = await attenuation_manager.apply_create_attenuation_objects(
            plan_id, objects, unit=unit, coordinates=coordinates
        )
        return write_result(result, applied="Attenuation objects created and read back.")
    except Exception as e:
        return write_failure("create InnerSpace attenuation objects", e)


@server.tool(
    name="innerspace_update_attenuation_objects",
    input_schema=input_schema(
        plan_id=PlanId,
        objects=ObjectsToUpdate,
        unit=WriteUnit,
        coordinates=(Coordinates, "frame"),
        confirm=(Confirm, False),
    ),
    title="Update InnerSpace Attenuation Objects",
    description=(
        "Moves attenuation objects or changes their kind on one floor plan. Their ids are in innerspace_get_project "
        "with include_shapes. " + PARTIAL_UPDATE + " " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="attenuation",
    permission_action="update",
    auth="local_only",
)
async def innerspace_update_attenuation_objects(
    plan_id: PlanId,
    objects: ObjectsToUpdate,
    unit: WriteUnit,
    coordinates: Coordinates = "frame",
    confirm: Confirm = False,
) -> Dict[str, Any]:
    """Preview or update attenuation objects."""
    logger.info("innerspace_update_attenuation_objects tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(
                await attenuation_manager.preview_update_attenuation_objects(
                    plan_id, objects, unit=unit, coordinates=coordinates
                )
            )
        result = await attenuation_manager.apply_update_attenuation_objects(
            plan_id, objects, unit=unit, coordinates=coordinates
        )
        return write_result(result, applied="Attenuation objects updated and read back.")
    except Exception as e:
        return write_failure("update InnerSpace attenuation objects", e)


@server.tool(
    name="innerspace_remove_attenuation_objects",
    input_schema=input_schema(plan_id=PlanId, object_ids=ObjectIds, confirm=(Confirm, False)),
    title="Remove InnerSpace Attenuation Objects",
    description=(
        "Removes attenuation objects from one floor plan, at most 50 per call; their ids are in "
        "innerspace_get_project with include_shapes. The console has no undo. " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
    permission_category="attenuation",
    permission_action="delete",
    auth="local_only",
)
async def innerspace_remove_attenuation_objects(
    plan_id: PlanId, object_ids: ObjectIds, confirm: Confirm = False
) -> Dict[str, Any]:
    """Preview or remove attenuation objects."""
    logger.info("innerspace_remove_attenuation_objects tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(await attenuation_manager.preview_remove_attenuation_objects(plan_id, object_ids))
        result = await attenuation_manager.apply_remove_attenuation_objects(plan_id, object_ids)
        return write_result(result, applied="Attenuation objects removed and read back.")
    except Exception as e:
        return write_failure("remove InnerSpace attenuation objects", e)


@server.tool(
    name="innerspace_create_attenuation_object_type",
    input_schema=input_schema(name=TypeName, attenuation_db=AttenuationDb, color=Color, confirm=(ConfirmCreate, False)),
    title="Create InnerSpace Attenuation-Object Type",
    description=(
        'Creates a project attenuation-object type. Attenuation objects use it with variant "custom" and its id. '
        + CONFIRM_FLOW
        + " "
        + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="attenuation",
    permission_action="create",
    auth="local_only",
)
async def innerspace_create_attenuation_object_type(
    name: TypeName,
    attenuation_db: AttenuationDb,
    color: Color,
    confirm: ConfirmCreate = False,
) -> Dict[str, Any]:
    """Preview or create an attenuation-object type."""
    logger.info("innerspace_create_attenuation_object_type tool called (confirm=%s)", confirm)
    try:
        if not confirm:
            return write_preview(
                await attenuation_manager.preview_create_attenuation_object_type(name, attenuation_db, color)
            )
        result = await attenuation_manager.apply_create_attenuation_object_type(name, attenuation_db, color)
        return write_result(result, applied="Attenuation-object type created and read back.")
    except Exception as e:
        return write_failure("create InnerSpace attenuation-object type", e)


@server.tool(
    name="innerspace_update_attenuation_object_type",
    input_schema=input_schema(
        attenuation_object_type_id=ObjectTypeId,
        name=(NewTypeName, None),
        attenuation_db=(NewAttenuationDb, None),
        color=(NewColor, None),
        confirm=(Confirm, False),
    ),
    title="Update InnerSpace Attenuation-Object Type",
    description=(
        "Changes a project attenuation-object type. The change applies to every object that uses it, on every "
        "plan; the preview counts them. " + PARTIAL_UPDATE + " " + CONFIRM_FLOW + " " + FAMILY
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="attenuation",
    permission_action="update",
    auth="local_only",
)
async def innerspace_update_attenuation_object_type(
    attenuation_object_type_id: ObjectTypeId,
    name: NewTypeName = None,
    attenuation_db: NewAttenuationDb = None,
    color: NewColor = None,
    confirm: Confirm = False,
) -> Dict[str, Any]:
    """Preview or update an attenuation-object type."""
    logger.info("innerspace_update_attenuation_object_type tool called (confirm=%s)", confirm)
    changes = dict(name=name, attenuation_db=attenuation_db, color=color)
    try:
        if not confirm:
            return write_preview(
                await attenuation_manager.preview_update_attenuation_object_type(attenuation_object_type_id, **changes)
            )
        result = await attenuation_manager.apply_update_attenuation_object_type(attenuation_object_type_id, **changes)
        return write_result(result, applied="Attenuation-object type updated and read back.")
    except Exception as e:
        return write_failure("update InnerSpace attenuation-object type", e)
