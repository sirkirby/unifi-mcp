"""Floor plan image resource for UniFi InnerSpace.

A resource template at ``innerspace://plans/{plan_id}/image`` that returns the
plan's image. It is fetched on demand through the same manager call as
``innerspace_get_plan_asset``: only the plan's own image address is ever
requested, and the size cap and the type and content checks apply here too.

The template declares ``image/png``. The plan's metadata is read first, and a
plan whose image is another type is refused with fixed text before anything
is downloaded; its image is available from ``innerspace_get_plan_asset`` with
``include_image``.

The server registers the template with :func:`register_plan_image_resource`
only when ``innerspace_get_plan_asset`` is enabled, since both read the same
image.
"""

from __future__ import annotations

import base64
import logging
from contextlib import nullcontext

from mcp.server.mcpserver.exceptions import ResourceError
from mcp.types import Annotations

from unifi_core.operation_gate import ControllerBusyError
from unifi_innerspace_mcp.resources.uris import PLAN_IMAGE_URI_TEMPLATE
from unifi_innerspace_mcp.runtime import floor_plan_manager, get_operation_gate, server, tool_failure

PLAN_IMAGE_RESOURCE_META = {
    "io.unifi.resourceKind": "plan-image",
    "io.unifi.updateMode": "on-demand",
    "io.unifi.protocolSubscribe": False,
    "io.unifi.relatedTools": ["innerspace_get_plan_asset", "innerspace_list_floor_plans"],
}

_PNG = "image/png"
_OPERATION = "read InnerSpace plan image"
# The MCP SDK logs a read with the requested URI, which carries the caller's plan id: a failed read in the
# server (in its message arguments, and inside the error text) and every read in the resource manager (as an
# ``extra`` attribute).
_SDK_LOGGERS = ("mcp.server.mcpserver.server", "mcp.server.mcpserver.resources.resource_manager")
_URI_SCHEME = "innerspace://"


class _PlanImageUriFilter(logging.Filter):
    """Logs the URI template in place of a requested InnerSpace URI, so a rejected plan id never reaches a log."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                PLAN_IMAGE_URI_TEMPLATE if isinstance(arg, str) and _URI_SCHEME in arg else arg for arg in record.args
            )
        uri = getattr(record, "uri", None)
        if isinstance(uri, str) and _URI_SCHEME in uri:
            record.uri = PLAN_IMAGE_URI_TEMPLATE
        return True


async def _fetch(plan_id: str) -> tuple[str, str | None]:
    """The plan's content type, and its base64 image when that type is PNG."""
    try:
        content_type = (await floor_plan_manager.get_plan_asset(plan_id))["content_type"]
        if content_type != _PNG:
            return content_type, None
        asset = await floor_plan_manager.get_plan_asset(plan_id, include_image=True)
        return asset["content_type"], asset["image_base64"]
    except Exception as e:
        # Fixed text, built and logged the way the tools do it: class only.
        raise ResourceError(tool_failure(_OPERATION, e)["error"]) from None


async def plan_image(plan_id: str) -> bytes:
    """Fetch a plan's image bytes, after checking from its metadata that it is a PNG.

    A resource read is not a tool call, so it takes its own read slot at the
    console's operation gate, with a direct call's wait budget.
    """
    gate = get_operation_gate()
    slot = (
        gate.read(wait_budget=gate.settings.direct_call_wait_seconds, label=_OPERATION)
        if gate is not None
        else nullcontext()
    )
    try:
        async with slot:
            content_type, image = await _fetch(plan_id)
    except ControllerBusyError as e:
        # The gate's text is fixed; nothing was sent to the console.
        raise ResourceError(f"Failed to {_OPERATION}: {e}") from None
    if content_type != _PNG:
        raise ResourceError(
            f"Failed to {_OPERATION}: the image is not a PNG; read it with innerspace_get_plan_asset and include_image"
        )
    return base64.b64decode(image)


def register_plan_image_resource() -> None:
    """Register the plan image template on the server. Registering again replaces it."""
    for name in _SDK_LOGGERS:
        sdk_logger = logging.getLogger(name)
        if not any(isinstance(f, _PlanImageUriFilter) for f in sdk_logger.filters):
            sdk_logger.addFilter(_PlanImageUriFilter())
    server.resource(
        PLAN_IMAGE_URI_TEMPLATE,
        name="InnerSpace Plan Image",
        title="InnerSpace Floor Plan Image",
        description=(
            "The image of an InnerSpace floor plan, fetched on demand and capped in size. Replace {plan_id} with "
            "the plan's id (from innerspace_list_floor_plans). These IDs are scoped to the InnerSpace tool family "
            "— do not pass them to other products' tools."
        ),
        mime_type=_PNG,
        annotations=Annotations(audience=["user", "assistant"], priority=0.7),
        meta=PLAN_IMAGE_RESOURCE_META,
    )(plan_image)
