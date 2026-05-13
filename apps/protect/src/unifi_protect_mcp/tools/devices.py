"""Device tools for UniFi Protect MCP server.

Provides tools for managing lights, sensors, and chimes -- the non-camera
device types supported by the Protect ecosystem.
"""

import logging
from typing import Annotated, Any, Dict, Optional

from mcp.types import ToolAnnotations
from pydantic import Field, ValidationError

from unifi_core.confirmation import preview_response
from unifi_core.exceptions import UniFiNotFoundError
from unifi_core.protect.models._actions import TriggerChimeInput
from unifi_core.protect.models.chimes import (
    from_controller as chime_from_controller,
    to_controller_update as chime_to_controller_update,
)
from unifi_core.protect.models.lights import (
    from_controller as light_from_controller,
    to_controller_update as light_to_controller_update,
)
from unifi_core.protect.models.sensors import from_controller as sensor_from_controller
from unifi_protect_mcp.runtime import chime_manager, light_manager, sensor_manager, server

logger = logging.getLogger(__name__)


# ===========================================================================
# Light tools
# ===========================================================================


@server.tool(
    name="protect_list_lights",
    description=(
        "Lists all UniFi Protect floodlight devices with their name, connection "
        "state, brightness level, PIR motion sensitivity, and paired camera. "
        "Use to get an overview of all lights in the system."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_lights() -> Dict[str, Any]:
    """List all lights."""
    logger.info("protect_list_lights tool called")
    try:
        raw_lights = await light_manager.list_lights()
        lights = [light_from_controller(raw).model_dump(exclude_none=True) for raw in raw_lights]
        return {"success": True, "data": {"lights": lights, "count": len(lights)}}
    except Exception as e:
        logger.error("Error listing lights: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list lights: {e}"}


@server.tool(
    name="protect_update_light",
    description=(
        "Updates light settings such as on/off state, LED brightness level (1-6), "
        "PIR motion sensitivity (0-100), motion-triggered duration (15-900 seconds), "
        "status indicator light, and device name. Requires confirm=True to apply. "
        "Supported keys: light_on, led_level, sensitivity, duration_seconds, status_light, name."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="light",
    permission_action="update",
)
async def protect_update_light(
    light_id: Annotated[str, Field(description="Light device UUID (from protect_list_lights)")],
    settings: Annotated[
        dict,
        Field(
            description=(
                "Dictionary of settings to update. Supported keys: "
                "light_on (true/false - turn light on or off), "
                "led_level (1-6 - brightness level), "
                "sensitivity (0-100 - PIR motion sensitivity), "
                "duration_seconds (15-900 - how long light stays on after motion), "
                "status_light (true/false - status indicator LED), "
                "name (string - device display name)."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the mutation. When false (default), returns a preview of the changes."),
    ] = False,
) -> Dict[str, Any]:
    """Update light settings with preview/confirm."""
    logger.info("protect_update_light tool called for %s (confirm=%s)", light_id, confirm)
    try:
        if not settings:
            return {"success": False, "error": "No settings provided. Specify at least one setting to update."}

        filtered = light_to_controller_update(settings)
        if not filtered:
            return {"success": False, "error": "No supported settings provided."}

        preview_data = await light_manager.update_light(light_id, filtered)

        if not confirm:
            return preview_response(
                action="update",
                resource_type="light_settings",
                resource_id=light_id,
                current_state=preview_data["current_state"],
                proposed_changes=preview_data["proposed_changes"],
                resource_name=preview_data["light_name"],
            )

        # Apply the changes
        result = await light_manager.apply_light_settings(light_id, filtered)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating light settings for %s: %s", light_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update light settings: {e}"}


# ===========================================================================
# Sensor tools
# ===========================================================================


@server.tool(
    name="protect_list_sensors",
    description=(
        "Lists all UniFi Protect sensor devices (motion, door/window, temperature, "
        "humidity, light level, leak detection). Shows connection state, battery "
        "status, current readings, and recent detection timestamps. "
        "Use to monitor environmental conditions and sensor health."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_sensors() -> Dict[str, Any]:
    """List all sensors."""
    logger.info("protect_list_sensors tool called")
    try:
        raw_sensors = await sensor_manager.list_sensors()
        sensors = [sensor_from_controller(raw).model_dump(exclude_none=True) for raw in raw_sensors]
        return {"success": True, "data": {"sensors": sensors, "count": len(sensors)}}
    except Exception as e:
        logger.error("Error listing sensors: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list sensors: {e}"}


# ===========================================================================
# Chime tools
# ===========================================================================


@server.tool(
    name="protect_list_chimes",
    description=(
        "Lists all UniFi Protect chime devices with their name, connection state, "
        "volume, ring settings per camera, and available ringtones/tracks. "
        "Use to see chime configuration and which cameras trigger which chimes."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def protect_list_chimes() -> Dict[str, Any]:
    """List all chimes."""
    logger.info("protect_list_chimes tool called")
    try:
        raw_chimes = await chime_manager.list_chimes()
        chimes = [chime_from_controller(raw).model_dump(exclude_none=True) for raw in raw_chimes]
        return {"success": True, "data": {"chimes": chimes, "count": len(chimes)}}
    except Exception as e:
        logger.error("Error listing chimes: %s", e, exc_info=True)
        return {"success": False, "error": f"Failed to list chimes: {e}"}


@server.tool(
    name="protect_update_chime",
    description=(
        "Updates chime settings such as speaker volume (0-100), repeat times (1-6), "
        "and device name. Requires confirm=True to apply. "
        "Supported keys: volume, repeat_times, name."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="chime",
    permission_action="update",
)
async def protect_update_chime(
    chime_id: Annotated[str, Field(description="Chime device UUID (from protect_list_chimes)")],
    settings: Annotated[
        dict,
        Field(
            description=(
                "Dictionary of settings to update. Supported keys: "
                "volume (0-100 - speaker volume), "
                "repeat_times (1-6 - number of times to repeat the chime tone), "
                "name (string - device display name)."
            )
        ),
    ],
    confirm: Annotated[
        bool,
        Field(description="When true, executes the mutation. When false (default), returns a preview of the changes."),
    ] = False,
) -> Dict[str, Any]:
    """Update chime settings with preview/confirm."""
    logger.info("protect_update_chime tool called for %s (confirm=%s)", chime_id, confirm)
    try:
        if not settings:
            return {"success": False, "error": "No settings provided. Specify at least one setting to update."}

        filtered = chime_to_controller_update(settings)
        if not filtered:
            return {"success": False, "error": "No supported settings provided."}

        preview_data = await chime_manager.update_chime(chime_id, filtered)

        if not confirm:
            return preview_response(
                action="update",
                resource_type="chime_settings",
                resource_id=chime_id,
                current_state=preview_data["current_state"],
                proposed_changes=preview_data["proposed_changes"],
                resource_name=preview_data["chime_name"],
            )

        # Apply the changes
        result = await chime_manager.apply_chime_settings(chime_id, filtered)
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error updating chime settings for %s: %s", chime_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to update chime settings: {e}"}


@server.tool(
    name="protect_trigger_chime",
    description=(
        "Plays the chime tone on a specific chime device. Optionally override "
        "volume (0-100) and repeat times (1-6) for this playback only. "
        "The chime's default settings are used if not specified."
    ),
    annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False),
    permission_category="chime",
    permission_action="update",
)
async def protect_trigger_chime(
    chime_id: Annotated[str, Field(description="Chime device UUID (from protect_list_chimes)")],
    volume: Annotated[
        Optional[int],
        Field(
            description="Override speaker volume for this playback only (0-100). Omit to use the chime's configured volume."
        ),
    ] = None,
    repeat_times: Annotated[
        Optional[int],
        Field(
            description="Override repeat count for this playback only (1-6). Omit to use the chime's configured repeat setting."
        ),
    ] = None,
) -> Dict[str, Any]:
    """Trigger a chime to play its tone."""
    logger.info("protect_trigger_chime tool called for %s (volume=%s, repeat=%s)", chime_id, volume, repeat_times)
    try:
        try:
            params = TriggerChimeInput(chime_id=chime_id, volume=volume, repeat_times=repeat_times)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e.errors()[0]['msg']}"}
        result = await chime_manager.trigger_chime(
            chime_id=chime_id,
            volume=volume,
            repeat_times=repeat_times,
        )
        return {"success": True, "data": result}
    except (UniFiNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("Error triggering chime %s: %s", chime_id, e, exc_info=True)
        return {"success": False, "error": f"Failed to trigger chime: {e}"}


logger.info(
    "Device tools registered: protect_list_lights, protect_update_light, "
    "protect_list_sensors, protect_list_chimes, protect_update_chime, protect_trigger_chime"
)
