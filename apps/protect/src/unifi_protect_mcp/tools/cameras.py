"""Camera tools for UniFi Protect MCP server.

Provides tools for listing, inspecting, and managing cameras including
snapshots, stream URLs, settings, recording, PTZ control, and reboots.
"""

import base64
import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import preview_response
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import (
    PtzMoveInput,
    PtzPresetInput,
    PtzZoomInput,
    RebootCameraInput,
    ToggleRecordingInput,
)
from unifi_core.protect.models.cameras import (
    Camera,
    from_controller as camera_from_controller,
    to_controller_update as camera_to_controller_update,
)
from unifi_protect_mcp.runtime import camera_manager, server

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Read-only tools
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_list_cameras",
    description=(
        "Lists all cameras adopted by the Protect NVR with their name, model, "
        "connection state, recording mode, and whether they are currently recording. "
        "Use to get an overview of all cameras in the system."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_cameras() -> Dict[str, Any]:
    """List all cameras."""
    logger.info("protect_list_cameras tool called")
    try:
        cameras = await camera_manager.list_cameras()
        shaped = [camera_from_controller(c).model_dump(exclude_none=True) for c in cameras]
        return {"success": True, "data": {"cameras": shaped, "count": len(shaped)}}
    except Exception as e:
        logger.error("Error listing cameras: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list cameras: {e}"}


@server.tool(
    name="protect_get_camera",
    description=(
        "Returns detailed information for a single camera including firmware, "
        "IP address, MAC, mic/speaker settings, IR/HDR mode, stream channels, "
        "smart detection types, and PTZ capability. Use to inspect one camera."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_camera(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
) -> Dict[str, Any]:
    """Get detailed camera information by ID."""
    logger.info("protect_get_camera tool called for %s", camera_id)
    try:
        detail = await camera_manager.get_camera(camera_id)
        return {"success": True, "data": camera_from_controller(detail).model_dump(exclude_none=True)}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get camera: {e}"}


@server.tool(
    name="protect_get_snapshot",
    description=(
        "Fetches a JPEG snapshot from a camera. When include_image is True, "
        "returns the image as a base64-encoded string. When False (default), "
        "returns a reference URL. Optionally specify width and height to resize."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_snapshot(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
    include_image: Annotated[
        bool,
        Field(
            description="When true, returns base64-encoded JPEG image data in the response. When false (default), returns a resource URI."
        ),
    ] = False,
    width: Annotated[
        Optional[int],
        Field(
            description="Resize the snapshot to this width in pixels. Aspect ratio is preserved if only width or height is set."
        ),
    ] = None,
    height: Annotated[
        Optional[int],
        Field(
            description="Resize the snapshot to this height in pixels. Aspect ratio is preserved if only width or height is set."
        ),
    ] = None,
) -> Dict[str, Any]:
    """Get a snapshot from a camera."""
    logger.info("protect_get_snapshot tool called for %s (include_image=%s)", camera_id, include_image)
    try:
        if include_image:
            snapshot_bytes = await camera_manager.get_snapshot(camera_id, width=width, height=height)
            return {
                "success": True,
                "data": {
                    "image_base64": base64.b64encode(snapshot_bytes).decode(),
                    "content_type": "image/jpeg",
                },
            }
        else:
            # Return a reference URL; snapshot resources handle actual delivery
            return {
                "success": True,
                "data": {
                    "snapshot_url": f"protect://cameras/{camera_id}/snapshot",
                },
            }
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting snapshot for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get snapshot: {e}"}


@server.tool(
    name="protect_get_camera_streams",
    description=(
        "Returns RTSP/RTSPS stream URLs for a camera organized by channel "
        "(High, Medium, Low). Includes resolution, FPS, and bitrate for each stream. "
        "Use to connect a video player or integration to camera feeds."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_camera_streams(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
) -> Dict[str, Any]:
    """Get stream URLs for a camera."""
    logger.info("protect_get_camera_streams tool called for %s", camera_id)
    try:
        streams = await camera_manager.get_camera_streams(camera_id)
        return {"success": True, "data": streams}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting streams for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get camera streams: {e}"}


@server.tool(
    name="protect_get_camera_analytics",
    description=(
        "Returns motion and smart detection analytics for a camera including "
        "current detection state, last-detected timestamps for each type "
        "(person, vehicle, animal, etc.), and zone counts. "
        "For historical events, use the events API tools."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_get_camera_analytics(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
) -> Dict[str, Any]:
    """Get motion/smart detection analytics for a camera."""
    logger.info("protect_get_camera_analytics tool called for %s", camera_id)
    try:
        analytics = await camera_manager.get_camera_analytics(camera_id)
        return {"success": True, "data": analytics}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error getting analytics for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to get camera analytics: {e}"}


# ---------------------------------------------------------------------------
# Mutation tools (preview/confirm pattern)
# ---------------------------------------------------------------------------


@server.tool(
    name="protect_update_camera_settings",
    description=(
        "Updates camera settings such as IR LED mode, HDR mode, mic/speaker volume, "
        "status light, and motion detection. Requires confirm=True to apply. "
        "Supported keys: ir_led_mode, hdr_mode, mic_enabled, mic_volume, "
        "status_light_on, speaker_volume, name, motion_detection."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="camera",
    permission_action="update",
)
async def protect_update_camera_settings(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
    settings: Annotated[
        dict,
        Field(
            description=(
                "Dictionary of settings to update. Supported keys: "
                "ir_led_mode (auto, on, autoFilterOnly), hdr_mode (true/false), "
                "mic_enabled (true/false), mic_volume (0-100), "
                "status_light_on (true/false), speaker_volume (0-100), "
                "name (string), motion_detection (true/false)."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the mutation. When false (default), returns a preview of the changes."),
    ] = False,
) -> Dict[str, Any]:
    """Update camera settings with preview/confirm."""
    logger.info("protect_update_camera_settings tool called for %s (confirm=%s)", camera_id, confirm)
    try:
        if not settings:
            return {"success": False, "error": "No settings provided. Specify at least one setting to update."}

        filtered = camera_to_controller_update(settings)
        if not filtered:
            return {"success": False, "error": "No supported settings provided."}

        preview_data = await camera_manager.update_camera_settings(camera_id, filtered)

        if not confirm:
            return preview_response(
                action="update",
                resource_type="camera_settings",
                resource_id=camera_id,
                current_state=preview_data["current_state"],
                proposed_changes=preview_data["proposed_changes"],
                resource_name=preview_data["camera_name"],
            )

        # Apply the changes
        result = await camera_manager.apply_camera_settings(camera_id, filtered)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating camera settings for %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update camera settings: {e}"}


@server.tool(
    name="protect_toggle_recording",
    description=(
        "Enables or disables recording on a camera. When enabled, sets recording "
        "mode to 'always'. When disabled, sets to 'never'. Requires confirm=True to apply."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="camera",
    permission_action="update",
)
async def protect_toggle_recording(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
    enabled: Annotated[
        bool,
        Field(
            description="When true, enables recording (mode set to 'always'). When false, disables recording (mode set to 'never')."
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the mutation. When false (default), returns a preview of the changes."),
    ] = False,
) -> Dict[str, Any]:
    """Toggle camera recording on/off with preview/confirm."""
    logger.info("protect_toggle_recording tool called for %s (enabled=%s, confirm=%s)", camera_id, enabled, confirm)
    try:
        try:
            params = ToggleRecordingInput(camera_id=camera_id, enabled=enabled)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        preview_data = await camera_manager.toggle_recording(camera_id, enabled)

        if not confirm:
            return preview_response(
                action="toggle",
                resource_type="camera_recording",
                resource_id=camera_id,
                current_state={
                    "recording_mode": preview_data["current_recording_mode"],
                    "is_recording": preview_data["is_recording"],
                },
                proposed_changes={
                    "recording_mode": preview_data["proposed_recording_mode"],
                },
                resource_name=preview_data["camera_name"],
            )

        # Apply the change
        result = await camera_manager.apply_toggle_recording(camera_id, enabled)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error toggling recording for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to toggle recording: {e}"}


@server.tool(
    name="protect_ptz_move",
    description=(
        "Moves a PTZ camera using normalized pan/tilt speeds. "
        "Requires confirm=True to execute. Use protect_ptz_zoom for zoom movement. "
        "Only works on PTZ-capable cameras."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="camera",
    permission_action="update",
)
async def protect_ptz_move(
    camera_id: Annotated[str, Field(description="Camera UUID of a PTZ-capable camera (from protect_list_cameras)")],
    pan: Annotated[
        Optional[float],
        Field(description="Pan speed from -1000 (left) to 1000 (right). Use 0 to stop pan."),
    ] = None,
    tilt: Annotated[
        Optional[float],
        Field(description="Tilt speed from -1000 (down) to 1000 (up). Use 0 to stop tilt."),
    ] = None,
    duration_ms: Annotated[
        int,
        Field(ge=0, le=5000, description="How long to move before automatically sending a stop command."),
    ] = 250,
    confirm: Annotated[
        bool,
        Field(description="Set to true to execute the physical PTZ movement. Defaults to false for preview."),
    ] = False,
) -> Dict[str, Any]:
    """Move a PTZ camera with preview/confirm."""
    logger.info(
        "protect_ptz_move tool called for %s (pan=%s, tilt=%s, duration_ms=%s, confirm=%s)",
        camera_id,
        pan,
        tilt,
        duration_ms,
        confirm,
    )
    try:
        try:
            params = PtzMoveInput(camera_id=camera_id, pan=pan, tilt=tilt, duration_ms=duration_ms)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        if not confirm:
            camera = await camera_manager.get_camera(camera_id)
            if not camera.get("is_ptz"):
                return {"success": False, "error": f"Camera {camera_id} does not support PTZ"}
            return preview_response(
                action="move",
                resource_type="ptz_camera",
                resource_id=camera_id,
                resource_name=camera.get("name"),
                current_state={"is_ptz": camera.get("is_ptz")},
                proposed_changes={"pan": pan or 0, "tilt": tilt or 0, "duration_ms": duration_ms},
            )

        result = await camera_manager.ptz_move(camera_id, pan=pan, tilt=tilt, duration_ms=duration_ms)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error with PTZ move for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to execute PTZ move: {e}"}


@server.tool(
    name="protect_ptz_zoom",
    description=(
        "Zooms a PTZ camera using normalized zoom speed. "
        "Requires confirm=True to execute. This is separate from optical zoom settings."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="camera",
    permission_action="update",
)
async def protect_ptz_zoom(
    camera_id: Annotated[str, Field(description="Camera UUID of a PTZ-capable camera (from protect_list_cameras)")],
    zoom_speed: Annotated[
        int,
        Field(ge=-1000, le=1000, description="Zoom speed from -1000 (out) to 1000 (in). Use 0 to stop zoom."),
    ] = 0,
    duration_ms: Annotated[
        int,
        Field(ge=0, le=5000, description="How long to zoom before automatically sending a stop command."),
    ] = 250,
    confirm: Annotated[
        bool,
        Field(description="Set to true to execute the physical PTZ zoom. Defaults to false for preview."),
    ] = False,
) -> Dict[str, Any]:
    """Zoom a PTZ camera with preview/confirm."""
    logger.info(
        "protect_ptz_zoom tool called for %s (zoom_speed=%s, duration_ms=%s, confirm=%s)",
        camera_id,
        zoom_speed,
        duration_ms,
        confirm,
    )
    try:
        try:
            params = PtzZoomInput(camera_id=camera_id, zoom_speed=zoom_speed, duration_ms=duration_ms)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        if not confirm:
            camera = await camera_manager.get_camera(camera_id)
            if not camera.get("is_ptz"):
                return {"success": False, "error": f"Camera {camera_id} does not support PTZ"}
            return preview_response(
                action="zoom",
                resource_type="ptz_camera",
                resource_id=camera_id,
                resource_name=camera.get("name"),
                current_state={"is_ptz": camera.get("is_ptz")},
                proposed_changes={"zoom_speed": zoom_speed, "duration_ms": duration_ms},
            )

        result = await camera_manager.ptz_zoom(camera_id, zoom_speed=zoom_speed, duration_ms=duration_ms)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error with PTZ zoom for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to execute PTZ zoom: {e}"}


@server.tool(
    name="protect_ptz_preset",
    description=(
        "Moves a PTZ camera to a saved preset position by slot number. "
        "Returns available presets for the camera. Requires confirm=True to execute. "
        "Only works on PTZ-capable cameras."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False),
    permission_category="camera",
    permission_action="update",
)
async def protect_ptz_preset(
    camera_id: Annotated[str, Field(description="Camera UUID of a PTZ-capable camera (from protect_list_cameras)")],
    preset_slot: Annotated[
        int,
        Field(
            description="Preset slot number to move the camera to. Available slots can be seen in the camera's PTZ preset list."
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="Set to true to move to the preset. Defaults to false for preview."),
    ] = False,
) -> Dict[str, Any]:
    """Move PTZ camera to a preset position with preview/confirm."""
    logger.info("protect_ptz_preset tool called for %s (slot=%s, confirm=%s)", camera_id, preset_slot, confirm)
    try:
        try:
            params = PtzPresetInput(camera_id=camera_id, preset_slot=preset_slot)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        if not confirm:
            camera = await camera_manager.get_camera(camera_id)
            if not camera.get("is_ptz"):
                return {"success": False, "error": f"Camera {camera_id} does not support PTZ"}
            return preview_response(
                action="move_to_preset",
                resource_type="ptz_camera",
                resource_id=camera_id,
                resource_name=camera.get("name"),
                current_state={"is_ptz": camera.get("is_ptz")},
                proposed_changes={"preset_slot": preset_slot},
            )

        result = await camera_manager.ptz_goto_preset(camera_id, preset_slot)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error with PTZ preset for camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to go to PTZ preset: {e}"}


@server.tool(
    name="protect_reboot_camera",
    description=(
        "Reboots a camera. The camera will be temporarily unavailable during reboot. "
        "Requires confirm=True to execute. Use with caution — active recordings will be interrupted."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False),
    permission_category="camera",
    permission_action="update",
)
async def protect_reboot_camera(
    camera_id: Annotated[str, Field(description="Camera UUID (from protect_list_cameras)")],
    confirm: Annotated[
        bool,
        Field(
            description="When true, executes the reboot. When false (default), returns a preview showing camera state and warnings."
        ),
    ] = False,
) -> Dict[str, Any]:
    """Reboot a camera with preview/confirm."""
    logger.info("protect_reboot_camera tool called for %s (confirm=%s)", camera_id, confirm)
    try:
        try:
            params = RebootCameraInput(camera_id=camera_id)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        preview_data = await camera_manager.reboot_camera(camera_id)

        if not confirm:
            return preview_response(
                action="reboot",
                resource_type="camera",
                resource_id=camera_id,
                current_state={
                    "state": preview_data["state"],
                    "is_connected": preview_data["is_connected"],
                },
                proposed_changes={
                    "action": "reboot",
                    "state": "rebooting",
                },
                resource_name=preview_data["camera_name"],
                warnings=[
                    "Camera will be temporarily unavailable during reboot. Active recordings will be interrupted."
                ],
            )

        # Execute reboot
        result = await camera_manager.apply_reboot_camera(camera_id)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error rebooting camera %s: %s", camera_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to reboot camera: {e}"}


logger.info(
    "Camera tools registered: protect_list_cameras, protect_get_camera, "
    "protect_get_snapshot, protect_get_camera_streams, protect_get_camera_analytics, "
    "protect_update_camera_settings, protect_toggle_recording, "
    "protect_ptz_move, protect_ptz_zoom, protect_ptz_preset, protect_reboot_camera"
)
