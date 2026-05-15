"""Camera snapshot MCP resources for UniFi Protect.

Registers a **resource template** at ``protect://cameras/{camera_id}/snapshot``
that returns a live JPEG snapshot from the requested camera.

Because FastMCP supports URI-template resources with ``{parameters}`` and can
return ``bytes`` (the SDK automatically base64-encodes and wraps in
``BlobResourceContents``), each camera does **not** need its own static
registration -- clients simply read the template URI with the desired camera ID.

A companion **list resource** at ``protect://cameras/snapshots`` provides a
JSON index of all available cameras and their snapshot URIs so clients can
discover cameras before requesting snapshots.

Usage by MCP clients
--------------------
1. Read ``protect://cameras/snapshots`` to discover camera IDs.
2. Read ``protect://cameras/<camera_id>/snapshot`` to fetch the JPEG image.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from mcp.types import Annotations

from unifi_protect_mcp.runtime import camera_manager, server

logger = logging.getLogger(__name__)

SNAPSHOT_RESOURCE_META = {
    "io.unifi.resourceKind": "camera-snapshot",
    "io.unifi.updateMode": "on-demand",
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["protect_get_snapshot", "protect_list_cameras"],
}

SNAPSHOT_INDEX_RESOURCE_META = {
    "io.unifi.resourceKind": "snapshot-index",
    "io.unifi.updateMode": "poll",
    "io.unifi.pollIntervalMs": 10000,
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["protect_get_snapshot", "protect_list_cameras"],
}


# ---------------------------------------------------------------------------
# Resource template: individual camera snapshot (returns JPEG bytes)
# ---------------------------------------------------------------------------


@server.resource(
    "protect://cameras/{camera_id}/snapshot",
    name="Camera Snapshot",
    title="Live Camera Snapshot",
    description=(
        "Live JPEG snapshot from a UniFi Protect camera. "
        "Replace {camera_id} with the camera's ID (discover IDs via "
        "the protect://cameras/snapshots index resource or the "
        "protect_list_cameras tool)."
    ),
    mime_type="image/jpeg",
    annotations=Annotations(audience=["user", "assistant"], priority=0.7),
    meta=SNAPSHOT_RESOURCE_META,
)
async def camera_snapshot(camera_id: str) -> bytes:
    """Fetch a JPEG snapshot for the given camera.

    Returns raw JPEG bytes.  The MCP SDK automatically base64-encodes them
    for transport as a ``BlobResourceContents`` message.
    """
    logger.info("[snapshot-resource] Fetching snapshot for camera %s", camera_id)
    try:
        snapshot_bytes = await camera_manager.get_snapshot(camera_id)
        logger.info(
            "[snapshot-resource] Snapshot for camera %s: %d bytes",
            camera_id,
            len(snapshot_bytes),
        )
        return snapshot_bytes
    except Exception as exc:
        logger.error(
            "[snapshot-resource] Error fetching snapshot for camera %s: %s",
            camera_id,
            exc,
            exc_info=True,
        )
        raise


# ---------------------------------------------------------------------------
# Discovery resource: list all cameras with snapshot URIs
# ---------------------------------------------------------------------------


@server.resource(
    "protect://cameras/snapshots",
    name="Camera Snapshot Index",
    title="Camera Snapshot Index",
    description=(
        "JSON index of all cameras available for snapshot capture. "
        "Each entry includes the camera ID, name, connection state, "
        "and the resource URI to fetch its snapshot."
    ),
    mime_type="application/json",
    annotations=Annotations(audience=["assistant"], priority=0.6),
    meta=SNAPSHOT_INDEX_RESOURCE_META,
)
async def camera_snapshot_index() -> str:
    """Return a JSON array of cameras with their snapshot resource URIs."""
    try:
        cameras: List[Dict[str, Any]] = await camera_manager.list_cameras()
        index = []
        for cam in cameras:
            index.append(
                {
                    "camera_id": cam["id"],
                    "name": cam["name"],
                    "model": cam.get("model"),
                    "is_connected": cam.get("is_connected"),
                    "snapshot_uri": f"protect://cameras/{cam['id']}/snapshot",
                }
            )
        return json.dumps(index, default=str)
    except Exception as exc:
        logger.error("[snapshot-resource] Error listing cameras for index: %s", exc, exc_info=True)
        return json.dumps({"error": str(exc)})


logger.info(
    "Snapshot resources registered: "
    "protect://cameras/{camera_id}/snapshot (template), "
    "protect://cameras/snapshots (index)"
)
