"""Recognition tools for UniFi Protect MCP server."""

import logging
from typing import Annotated, Any, Dict, List, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import preview_response, update_preview
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import (
    DeleteKnownFaceInput,
    DeleteKnownLicensePlateInput,
    MergeKnownFacesInput,
)
from unifi_core.protect.models.recognition import from_controller
from unifi_protect_mcp.runtime import recognition_manager, server

logger = logging.getLogger(__name__)


@server.tool(
    name="protect_list_known_faces",
    description=(
        "List UniFi Protect face recognition groups, including assigned Known Faces "
        "by default and unlabeled groups when group_types includes unknown. "
        "Returns metadata and controller image references only; image bytes are not fetched."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="recognition",
)
async def protect_list_known_faces(
    page: Annotated[
        Optional[int],
        Field(description="Optional 1-based Protect recognition page number."),
    ] = None,
    page_size: Annotated[
        int,
        Field(description="Maximum number of face groups to return (default 100).", ge=1, le=1000),
    ] = 100,
    min_confidence: Annotated[
        int,
        Field(description="Minimum recognition confidence filter used by Protect (0-100, default 30).", ge=0, le=100),
    ] = 30,
    include_interest: Annotated[
        bool,
        Field(
            description=(
                "Backward-compatible filter used when group_types is omitted. "
                "When true, include known and interest groups. When false, only known groups."
            )
        ),
    ] = True,
    group_types: Annotated[
        Optional[List[str]],
        Field(
            description=(
                "Optional explicit recognition group types to list. Supported values: known, interest, unknown. "
                "When set, this overrides include_interest."
            )
        ),
    ] = None,
    order_by: Annotated[
        str,
        Field(description="Sort field: name, createdAt, firstDetectedAt, lastDetectedAt, or detectionsCount."),
    ] = "name",
    order_direction: Annotated[
        str,
        Field(description="Sort direction: asc or desc."),
    ] = "asc",
) -> Dict[str, Any]:
    """List assigned Known Faces from the Protect recognition API."""
    logger.info(
        "protect_list_known_faces called (page=%s, page_size=%s, min_confidence=%s)",
        page,
        page_size,
        min_confidence,
    )
    try:
        raw = await recognition_manager.list_known_faces(
            page=page,
            page_size=page_size,
            min_confidence=min_confidence,
            include_interest=include_interest,
            group_types=group_types,
            order_by=order_by,
            order_direction=order_direction,  # type: ignore[arg-type]
        )
        faces = [from_controller(face).model_dump(exclude_none=True) for face in raw.get("faces", [])]
        return {
            "success": True,
            "data": {
                "faces": faces,
                "count": len(faces),
                "links": raw.get("links", {}),
            },
        }
    except Exception as e:
        logger.error("Error listing known faces: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list known faces: {e}"}


@server.tool(
    name="protect_list_known_license_plates",
    description=(
        "List UniFi Protect license-plate identities (vehicle recognition groups), "
        "including named/known license plates by default and unlabeled plate groups when "
        "group_types includes unknown. Each entry's `id` is the value to use in a "
        "`license_plate_known` alarm-rule condition. Returns metadata (incl. color/vehicleType "
        "when Protect provides them) and controller image references only; image bytes are not fetched."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    permission_category="recognition",
)
async def protect_list_known_license_plates(
    page: Annotated[
        Optional[int],
        Field(description="Optional 1-based Protect recognition page number."),
    ] = None,
    page_size: Annotated[
        int,
        Field(
            description="Maximum number of license-plate groups to return (default 100).",
            ge=1,
            le=1000,
        ),
    ] = 100,
    min_confidence: Annotated[
        int,
        Field(
            description="Minimum recognition confidence filter used by Protect (0-100, default 30).",
            ge=0,
            le=100,
        ),
    ] = 30,
    include_interest: Annotated[
        bool,
        Field(
            description=(
                "Backward-compatible filter used when group_types is omitted. "
                "When true, include known and interest groups. When false, only known groups."
            )
        ),
    ] = True,
    group_types: Annotated[
        Optional[List[str]],
        Field(
            description=(
                "Optional explicit recognition group types to list. Supported values: known, "
                "interest, unknown. When set, this overrides include_interest."
            )
        ),
    ] = None,
    order_by: Annotated[
        str,
        Field(description="Sort field: name, createdAt, firstDetectedAt, lastDetectedAt, or detectionsCount."),
    ] = "name",
    order_direction: Annotated[
        str,
        Field(description="Sort direction: asc or desc."),
    ] = "asc",
) -> Dict[str, Any]:
    """List Protect License Plate Identities (vehicle recognition groups)."""
    logger.info(
        "protect_list_known_license_plates called (page=%s, page_size=%s, min_confidence=%s)",
        page,
        page_size,
        min_confidence,
    )
    try:
        raw = await recognition_manager.list_known_license_plates(
            page=page,
            page_size=page_size,
            min_confidence=min_confidence,
            include_interest=include_interest,
            group_types=group_types,
            order_by=order_by,
            order_direction=order_direction,  # type: ignore[arg-type]
        )
        # Manager already serializes via license_plate_from_controller + model_dump,
        # so pass through directly (no redundant re-serialization).
        plates = raw.get("license_plates", [])
        return {
            "success": True,
            "data": {
                "license_plates": plates,
                "count": len(plates),
                "links": raw.get("links", {}),
            },
        }
    except Exception as e:
        logger.error("Error listing known license plates: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list known license plates: {e}"}


@server.tool(
    name="protect_update_known_face",
    description=(
        "Update UniFi Protect Known Face metadata. Pass only the fields you want to change; "
        "current values are automatically preserved. Supported fields: name, description, "
        "is_notification_enabled. Requires confirm=True to apply; otherwise returns a preview."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "face_id": {
                "type": "string",
                "description": "Face group UUID from protect_list_known_faces.",
            },
            "fields": {
                "type": "object",
                "description": (
                    "Partial update fields. Supported keys: name, description, is_notification_enabled. "
                    "Read-only fields such as id, image paths, detection counts, timestamps, type, tags, "
                    "and metadata are rejected."
                ),
                "properties": {
                    "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "is_notification_enabled": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
                },
                "additionalProperties": False,
            },
            "confirm": {
                "type": "boolean",
                "description": "When true, applies the update. When false (default), returns a preview.",
            },
        },
        "required": ["face_id", "fields"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="recognition",
    permission_action="update",
)
async def protect_update_known_face(
    face_id: Annotated[str, Field(description="Face group UUID from protect_list_known_faces.")],
    fields: Annotated[
        Dict[str, Any],
        Field(
            description=(
                "Partial update fields. Supported keys: name, description, is_notification_enabled. "
                "Read-only fields such as id, image paths, detection counts, timestamps, type, tags, "
                "and metadata are rejected."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Update Known Face metadata with preview/confirm."""
    logger.info("protect_update_known_face called for %s (confirm=%s)", face_id, confirm)
    try:
        field_data = fields.model_dump(exclude_unset=True) if hasattr(fields, "model_dump") else dict(fields)
        if not field_data:
            return {"success": False, "error": "No fields provided. Specify at least one field to update."}

        preview_data = await recognition_manager.update_known_face(face_id, field_data)
        if not confirm:
            return update_preview(
                resource_type="known_face",
                resource_id=face_id,
                resource_name=preview_data.get("face_name"),
                current_state=preview_data["current_state"],
                updates=preview_data["proposed_changes"],
            )

        result = await recognition_manager.apply_update_known_face(face_id, field_data)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating known face %s: %s", face_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update known face: {e}"}


@server.tool(
    name="protect_merge_known_faces",
    description=(
        "Merge one UniFi Protect face group into another. The target group survives and the source "
        "group is folded into it. Requires confirm=True to apply; otherwise returns a preview."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="recognition",
    permission_action="update",
)
async def protect_merge_known_faces(
    source_face_id: Annotated[str, Field(description="Face group UUID to fold into the target group.")],
    target_face_id: Annotated[str, Field(description="Face group UUID that survives the merge.")],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the merge. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Merge one Known Face group into another with preview/confirm."""
    logger.info(
        "protect_merge_known_faces called (source=%s, target=%s, confirm=%s)",
        source_face_id,
        target_face_id,
        confirm,
    )
    try:
        try:
            MergeKnownFacesInput(source_face_id=source_face_id, target_face_id=target_face_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

        preview_data = await recognition_manager.merge_known_faces(source_face_id, target_face_id)
        if not confirm:
            return preview_response(
                action="merge",
                resource_type="known_face",
                resource_id=source_face_id,
                current_state={
                    "source": preview_data["source"],
                    "target": preview_data["target"],
                },
                proposed_changes={
                    "source_face_id": source_face_id,
                    "target_face_id": target_face_id,
                    "target_survives": True,
                },
                resource_name=preview_data["source"].get("name") or preview_data["source"].get("matched_name"),
                warnings=preview_data["warnings"],
            )

        result = await recognition_manager.apply_merge_known_faces(source_face_id, target_face_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error merging known faces %s -> %s: %s", source_face_id, target_face_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to merge known faces: {e}"}


@server.tool(
    name="protect_delete_known_face",
    description=(
        "Delete or remove a UniFi Protect face recognition group. This is destructive. "
        "Requires confirm=True to apply; otherwise returns a preview of the exact group."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="recognition",
    permission_action="delete",
)
async def protect_delete_known_face(
    face_id: Annotated[str, Field(description="Face group UUID from protect_list_known_faces.")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the group. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Delete a Known Face group with preview/confirm."""
    logger.info("protect_delete_known_face called for %s (confirm=%s)", face_id, confirm)
    try:
        try:
            DeleteKnownFaceInput(face_id=face_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

        preview_data = await recognition_manager.delete_known_face(face_id)
        if not confirm:
            return preview_response(
                action="delete",
                resource_type="known_face",
                resource_id=face_id,
                current_state=preview_data["face"],
                proposed_changes={"deleted": True},
                resource_name=preview_data["face"].get("name") or preview_data["face"].get("matched_name"),
                warnings=preview_data["warnings"],
            )

        result = await recognition_manager.apply_delete_known_face(face_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting known face %s: %s", face_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete known face: {e}"}


@server.tool(
    name="protect_update_known_license_plate",
    description=(
        "Update UniFi Protect Known License Plate (license-plate identity) metadata. Pass only the "
        "fields you want to change; current values are automatically preserved. Supported fields: "
        "name, description, is_notification_enabled. Requires confirm=True to apply; otherwise returns a preview."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "plate_id": {
                "type": "string",
                "description": "License-plate group id from protect_list_known_license_plates.",
            },
            "fields": {
                "type": "object",
                "description": (
                    "Partial update fields. Supported keys: name, description, is_notification_enabled. "
                    "Read-only fields such as id, plate text (matched_name), image paths, detection counts, "
                    "timestamps, type, tags, and metadata are rejected."
                ),
                "properties": {
                    "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "is_notification_enabled": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
                },
                "additionalProperties": False,
            },
            "confirm": {
                "type": "boolean",
                "description": "When true, applies the update. When false (default), returns a preview.",
            },
        },
        "required": ["plate_id", "fields"],
        "additionalProperties": False,
    },
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False),
    permission_category="recognition",
    permission_action="update",
)
async def protect_update_known_license_plate(
    plate_id: Annotated[str, Field(description="License-plate group id from protect_list_known_license_plates.")],
    fields: Annotated[
        Dict[str, Any],
        Field(
            description=(
                "Partial update fields. Supported keys: name, description, is_notification_enabled. "
                "Read-only fields such as id, plate text (matched_name), image paths, detection counts, "
                "timestamps, type, tags, and metadata are rejected."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, applies the update. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Update Known License Plate metadata with preview/confirm."""
    logger.info("protect_update_known_license_plate called for %s (confirm=%s)", plate_id, confirm)
    try:
        field_data = fields.model_dump(exclude_unset=True) if hasattr(fields, "model_dump") else dict(fields)
        if not field_data:
            return {"success": False, "error": "No fields provided. Specify at least one field to update."}

        preview_data = await recognition_manager.update_known_license_plate(plate_id, field_data)
        if not confirm:
            return update_preview(
                resource_type="known_license_plate",
                resource_id=plate_id,
                resource_name=preview_data.get("plate_name"),
                current_state=preview_data["current_state"],
                updates=preview_data["proposed_changes"],
            )

        result = await recognition_manager.apply_update_known_license_plate(plate_id, field_data)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating known license plate %s: %s", plate_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update known license plate: {e}"}


@server.tool(
    name="protect_delete_known_license_plate",
    description=(
        "Delete or remove a UniFi Protect license-plate recognition group. This is destructive. "
        "Requires confirm=True to apply; otherwise returns a preview of the exact group."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="recognition",
    permission_action="delete",
)
async def protect_delete_known_license_plate(
    plate_id: Annotated[str, Field(description="License-plate group id from protect_list_known_license_plates.")],
    confirm: Annotated[
        bool,
        Field(description="When true, deletes the group. When false (default), returns a preview."),
    ] = False,
) -> Dict[str, Any]:
    """Delete a Known License Plate group with preview/confirm."""
    logger.info("protect_delete_known_license_plate called for %s (confirm=%s)", plate_id, confirm)
    try:
        try:
            DeleteKnownLicensePlateInput(plate_id=plate_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}

        preview_data = await recognition_manager.delete_known_license_plate(plate_id)
        if not confirm:
            return preview_response(
                action="delete",
                resource_type="known_license_plate",
                resource_id=plate_id,
                current_state=preview_data["license_plate"],
                proposed_changes={"deleted": True},
                resource_name=preview_data["license_plate"].get("name")
                or preview_data["license_plate"].get("matched_name"),
                warnings=preview_data["warnings"],
            )

        result = await recognition_manager.apply_delete_known_license_plate(plate_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error deleting known license plate %s: %s", plate_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to delete known license plate: {e}"}
