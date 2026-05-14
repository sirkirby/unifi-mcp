"""GET /v1/streams/access/doors/{door_id}/events — narrow per-door SSE."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.stream_generator import sse_event_stream

router = APIRouter()
PRODUCT = "access"


@router.get(
    f"/streams/{PRODUCT}/doors/{{door_id}}/events",
    dependencies=[Depends(require_scope(Scope.READ))],
)
async def stream_access_door_events(
    request: Request,
    door_id: str,
    controller=Depends(resolve_controller),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    require_capability(controller, PRODUCT)
    factory = request.app.state.manager_factory
    pool = request.app.state.subscriber_pool
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            PRODUCT,
            "event_manager",
        )
    serializer = request.app.state.serializer_registry.serializer_for_tool(
        "access_recent_events",
    )

    return StreamingResponse(
        sse_event_stream(
            manager=mgr,
            pool=pool,
            controller_id=controller.id,
            product=PRODUCT,
            serializer=serializer,
            last_event_id=last_event_id,
            filter_fn=lambda evt: evt.get("door_id") == door_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
