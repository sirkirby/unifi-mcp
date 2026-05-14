"""GET /v1/sites/{site_id}/recordings[/{recording_id}] — protect recordings.

UniFi Protect does not expose discrete recording segments — recordings
are a continuous time window per camera. The underlying manager method
returns a single dict describing that window for a given ``camera_id``.

The endpoint accepts ``camera_id`` as a query parameter and wraps the
single-dict response in a list for serialization. The detail endpoint
follows Task 8's firewall_rules pattern: fetch the list and filter by
id, since the manager exposes no native ``get_recording``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from unifi_core.exceptions import UniFiNotFoundError

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _recording_key(obj) -> tuple:
    """Sort by (start, id) descending — most recent first."""
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {})
    return (raw.get("start") or 0, raw.get("id") or "")


async def _maybe_set_site(cm, site_id: str) -> None:
    set_site = getattr(cm, "set_site", None)
    if set_site is None:
        return
    if getattr(cm, "site", None) != site_id:
        await set_site(site_id)


def _normalize_recordings(result) -> list[dict]:
    """Coerce the manager response into a list of dicts.

    ``RecordingManager.list_recordings`` historically returned a single
    dict (the window for one camera); newer/test stubs may return a
    list. Accept either.
    """
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    return []


@router.get(
    "/sites/{site_id}/recordings",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def list_recordings(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    camera_id: str = Query(..., description="Camera ID to query recordings for"),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "recording_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        result = await mgr.list_recordings(camera_id=camera_id)

    all_recordings = _normalize_recordings(result)

    cursor_obj = None
    if cursor:
        try:
            cursor_obj = Cursor.decode(cursor)
        except InvalidCursor:
            raise HTTPException(status_code=400, detail="invalid cursor")

    page, next_cursor = paginate(
        list(all_recordings),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_recording_key,
    )

    type_class = request.app.state.type_registry.lookup("protect", "recordings")
    items = [type_class.from_manager_output(r).to_dict() for r in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/recordings/{recording_id}",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def get_recording(
    request: Request,
    site_id: str,
    recording_id: str,
    controller=Depends(resolve_controller),
    camera_id: str = Query(..., description="Camera ID the recording belongs to"),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "recording_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        result = await mgr.list_recordings(camera_id=camera_id)

    all_recordings = _normalize_recordings(result)
    match = None
    for rec in all_recordings:
        raw = rec if isinstance(rec, dict) else getattr(rec, "raw", {})
        rid = raw.get("id")
        if rid == recording_id:
            match = rec
            break
    if match is None:
        raise HTTPException(status_code=404, detail="recording not found")

    type_class = request.app.state.type_registry.lookup("protect", "recordings/{id}")
    data = type_class.from_manager_output(match).to_dict()
    hint = type_class.render_hint("detail")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/recording-status",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/events"],
)
async def get_recording_status(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    camera_id: str | None = Query(
        None,
        description="Optional — limit to a single camera",
    ),
) -> dict:
    """Return current recording state for one or all cameras.

    The ``camera_id`` query is optional: omitting it returns the
    aggregate (all cameras), supplying it scopes to one camera and
    raises 404 via UniFiNotFoundError if the camera is unknown.
    """
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "recording_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_recording_status(camera_id=camera_id)
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_get_recording_status")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_get_recording_status")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("protect_get_recording_status")
    return {
        "data": data,
        "render_hint": hint,
    }
