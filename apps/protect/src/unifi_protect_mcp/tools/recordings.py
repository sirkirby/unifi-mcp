"""Recording tools for UniFi Protect MCP server.

Provides tools for querying recording status, listing recording availability,
and exporting video clips from cameras.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import DeleteRecordingInput, ExportClipInput
from unifi_core.protect.models.recordings import (
    from_controller as recording_from_controller,
    status_list_from_controller,
)
from pydantic import Field, ValidationError

from unifi_protect_mcp.runtime import recording_manager, server

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: parse ISO datetime string
# ---------------------------------------------------------------------------


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-format datetime string, returning None on failure."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_get_recording_status",
    description=(
        "Returns the current recording state for one or all cameras. Shows "
        "recording mode (always, never, detections), whether actively recording, "
        "and available recording time range from NVR stats. Pass a camera_id to "
        "check a single camera, or omit for all cameras."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_recording_status(
    camera_id: Annotated[
        Optional[str],
        Field(
            description="Camera UUID (from protect_list_cameras) to check. Omit to get recording status for all cameras."
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get recording status for one or all cameras."""
    logger.info("protect_get_recording_status called (camera_id=%s)", camera_id)
    try:
        result = await recording_manager.get_recording_status(camera_id=camera_id)
        shaped = status_list_from_controller(result).model_dump(exclude_none=True)
        return {"success": True, "data": shaped}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting recording status: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to get recording status: {e}"}


@server.tool(
    name="protect_list_recordings",
    description=(
        "Returns recording availability information for a camera within a time "
        "range. Shows the recording window and whether footage exists. UniFi "
        "Protect stores recordings as continuous streams, not discrete segments. "
        "Defaults to the last 24 hours if no time range is specified. "
        "Times should be ISO-8601 format (e.g., '2026-03-16T00:00:00Z')."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_recordings(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras) to query recordings for.")],
    start: Annotated[
        Optional[str],
        Field(
            description="Start of the time range as ISO 8601 timestamp (e.g., 2026-03-16T00:00:00Z). Defaults to 24 hours ago."
        ),
    ] = None,
    end: Annotated[
        Optional[str],
        Field(description="End of the time range as ISO 8601 timestamp (e.g., 2026-03-17T00:00:00Z). Defaults to now."),
    ] = None,
) -> Dict[str, Any]:
    """List recording availability for a camera."""
    logger.info("protect_list_recordings called (camera=%s, start=%s, end=%s)", camera_id, start, end)
    try:
        result = await recording_manager.list_recordings(
            camera_id=camera_id,
            start=_parse_datetime(start),
            end=_parse_datetime(end),
        )
        shaped = recording_from_controller(result).model_dump(exclude_none=True)
        return {"success": True, "data": shaped}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error listing recordings for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to list recordings: {e}"}


@server.tool(
    name="protect_export_clip",
    description=(
        "Exports a video clip from a camera for a specified time range. Returns "
        "metadata about the export (size, duration) but not the video data itself "
        "(too large for MCP responses). Maximum duration is 2 hours. "
        "For timelapse exports, pass fps (4=60x, 8=120x, 20=300x, 40=600x). "
        "Times must be ISO-8601 format (e.g., '2026-03-16T12:00:00Z')."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_export_clip(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras) to export footage from.")],
    start: Annotated[str, Field(description="Clip start time as ISO 8601 timestamp (e.g., 2026-03-16T12:00:00Z).")],
    end: Annotated[
        str,
        Field(
            description="Clip end time as ISO 8601 timestamp (e.g., 2026-03-16T12:30:00Z). Maximum 2 hours after start."
        ),
    ],
    channel_index: Annotated[
        int,
        Field(description="Video channel index: 0 = high quality (default), 1 = medium, 2 = low."),
    ] = 0,
    fps: Annotated[
        Optional[int],
        Field(
            description="Frames per second for timelapse export. Common values: 4 (60x speed), 8 (120x), 20 (300x), 40 (600x). Omit for normal speed."
        ),
    ] = None,
) -> Dict[str, Any]:
    """Export a video clip from a camera."""
    logger.info("protect_export_clip called (camera=%s, start=%s, end=%s, fps=%s)", camera_id, start, end, fps)
    try:
        try:
            params = ExportClipInput(
                camera_id=camera_id, start=start, end=end, channel_index=channel_index, fps=fps
            )
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        start_dt = _parse_datetime(start)
        end_dt = _parse_datetime(end)
        if start_dt is None:
            return {
                "success": False,
                "error": "Invalid start time. Use ISO-8601 format (e.g., '2026-03-16T12:00:00Z').",
            }
        if end_dt is None:
            return {"success": False, "error": "Invalid end time. Use ISO-8601 format (e.g., '2026-03-16T12:30:00Z')."}

        result = await recording_manager.export_clip(
            camera_id=camera_id,
            start=start_dt,
            end=end_dt,
            channel_index=channel_index,
            fps=fps,
        )
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error exporting clip for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to export clip: {e}"}


@server.tool(
    name="protect_delete_recording",
    description=(
        "Attempts to delete recordings for a camera in a time range. "
        "Note: Individual recording deletion is NOT supported by the uiprotect API. "
        "Recording retention is managed automatically by the NVR. This tool returns "
        "information about the limitation and alternative approaches."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="recording",
    permission_action="delete",
)
async def protect_delete_recording(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras) to delete recordings for.")],
    start: Annotated[
        str, Field(description="Start of the deletion range as ISO 8601 timestamp (e.g., 2026-03-16T00:00:00Z).")
    ],
    end: Annotated[
        str, Field(description="End of the deletion range as ISO 8601 timestamp (e.g., 2026-03-16T12:00:00Z).")
    ],
    confirm: Annotated[
        bool,
        Field(
            description="When true, attempts the deletion. When false (default), returns a preview. Note: deletion is not supported by the API regardless."
        ),
    ] = False,
) -> Dict[str, Any]:
    """Delete recording for a camera (not supported by API)."""
    logger.info(
        "protect_delete_recording called (camera=%s, start=%s, end=%s, confirm=%s)",
        camera_id,
        start,
        end,
        confirm,
    )
    try:
        try:
            params = DeleteRecordingInput(camera_id=camera_id, start=start, end=end)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        start_dt = _parse_datetime(start)
        end_dt = _parse_datetime(end)
        if start_dt is None:
            return {"success": False, "error": "Invalid start time. Use ISO-8601 format."}
        if end_dt is None:
            return {"success": False, "error": "Invalid end time. Use ISO-8601 format."}

        result = await recording_manager.delete_recording(
            camera_id=camera_id,
            start=start_dt,
            end=end_dt,
        )
        # Since deletion is not supported, always return the info response
        return {"success": False, "error": result["message"]}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error with delete recording for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to process recording deletion: {e}"}


logger.info(
    "Recording tools registered: protect_get_recording_status, protect_list_recordings, "
    "protect_export_clip, protect_delete_recording"
)
