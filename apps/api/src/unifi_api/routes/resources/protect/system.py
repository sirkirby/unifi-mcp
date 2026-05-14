"""Protect system + alarm read endpoints.

Six endpoint families collected here:

- ``GET /firmware-status``           → ``protect_get_firmware_status``
- ``GET /alarm-status``              → ``protect_alarm_get_status``
- ``GET /alarm-profiles``            → ``protect_alarm_list_profiles``
- ``GET /protect/health``            → ``protect_get_health`` (product-prefixed
  to disambiguate from ``/network/health`` and ``/access/health``)
- ``GET /protect/system-info``       → ``protect_get_system_info`` (likewise)
- ``GET /viewers``                   → ``protect_list_viewers``

The ``/protect/...`` prefix is in the URL path — not a router prefix.
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
from unifi_api.routes.resources.protect.cameras import _maybe_set_site
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate

router = APIRouter()


def _id_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


# ---------------------------------------------------------------------------
# Firmware status
# ---------------------------------------------------------------------------


@router.get(
    "/sites/{site_id}/firmware-status",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/system"],
)
async def get_firmware_status(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "system_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_firmware_status()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_get_firmware_status")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_get_firmware_status")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("protect_get_firmware_status")
    return {
        "data": data,
        "render_hint": hint,
    }


# ---------------------------------------------------------------------------
# Alarm status + profiles (alarm_manager)
# ---------------------------------------------------------------------------


@router.get(
    "/sites/{site_id}/alarm-status",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/system"],
)
async def alarm_get_status(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "alarm_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_arm_state()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_alarm_get_status")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_alarm_get_status")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("protect_alarm_get_status")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/alarm-profiles",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/system"],
)
async def alarm_list_profiles(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
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
            "alarm_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_arm_profiles()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_alarm_list_profiles")
    if tool_type is not None:
        # The action endpoint wraps the whole list as {profiles, count};
        # the REST per-page surface emits one row per profile via the
        # sub-row type ``AlarmProfile``.
        from unifi_api.graphql.types.protect.alarms import AlarmProfile

        rows = [AlarmProfile.from_manager_output(p).to_dict() for p in page]
        # Reuse the wrapper type's render hint kind, but emit per-row
        # display columns from the sub-row class (mirrors the original
        # serializer's render_hint contract).
        hint = AlarmProfile.render_hint(tool_type[1])
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_alarm_list_profiles")
        rows = [serializer.serialize(p) for p in page]
        hint = registry.render_hint_for_tool("protect_alarm_list_profiles")
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


# ---------------------------------------------------------------------------
# Protect-prefixed health + system info (disambiguated paths)
# ---------------------------------------------------------------------------


@router.get(
    "/sites/{site_id}/protect/health",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/system"],
)
async def get_protect_health(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "system_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_health()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_get_health")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_get_health")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("protect_get_health")
    return {
        "data": data,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/protect/system-info",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/system"],
)
async def get_protect_system_info(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    try:
        async with sm() as session:
            mgr = await factory.get_domain_manager(
                session,
                controller.id,
                "protect",
                "system_manager",
            )
            cm = await factory.get_connection_manager(session, controller.id, "protect")
            await _maybe_set_site(cm, site_id)
            payload = await mgr.get_system_info()
    except UniFiNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_get_system_info")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(payload).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_get_system_info")
        data = serializer.serialize(payload)
        hint = registry.render_hint_for_tool("protect_get_system_info")
    return {
        "data": data,
        "render_hint": hint,
    }


# ---------------------------------------------------------------------------
# Viewers — LIST
# ---------------------------------------------------------------------------


@router.get(
    "/sites/{site_id}/viewers",
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/system"],
)
async def list_viewers(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
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
            "system_manager",
        )
        cm = await factory.get_connection_manager(session, controller.id, "protect")
        await _maybe_set_site(cm, site_id)
        items = await mgr.list_viewers()

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(items),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_id_key,
    )

    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("protect_list_viewers")
    if tool_type is not None:
        # The action endpoint wraps the whole list as {viewers, count};
        # the REST per-page surface emits one row per viewer via the
        # sub-row type ``Viewer`` (mirrors AlarmProfile / AlarmProfileList
        # in protect/alarms).
        from unifi_api.graphql.types.protect.system import Viewer

        rows = [Viewer.from_manager_output(v).to_dict() for v in page]
        list_hint = Viewer.render_hint("list")
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("protect_list_viewers")
        rows = [serializer.serialize(v) for v in page]
        # ViewerSerializer hint kind is "detail" but the surface is a LIST —
        # override to "list" so consumers render rows.
        list_hint = {
            **registry.render_hint_for_tool("protect_list_viewers"),
            "kind": "list",
        }
    return {
        "items": rows,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": list_hint,
    }
