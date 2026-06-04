"""GET /v1/sites/{site_id}/known-faces — Protect recognition resources."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.protect.events import SmartDetection
from unifi_api.graphql.types.protect.recognition import (
    DetectionSearchLabels,
    KnownFace,
    KnownLicensePlate,
)
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate
from unifi_api.services.pydantic_models import Page

router = APIRouter()


def _known_face_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or "")


def _known_license_plate_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or "")


def _decode_cursor(cursor: str | None) -> Cursor | None:
    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise HTTPException(status_code=400, detail="invalid cursor")


@router.get(
    "/sites/{site_id}/known-faces",
    response_model=Page[to_pydantic_model(KnownFace)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/recognition"],
)
async def list_known_faces(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    min_confidence: int = Query(30, ge=0, le=100),
    include_interest: bool = Query(True),
    group_types: list[str] | None = Query(
        None,
        description=(
            "Explicit recognition group types to list. Supported values: known, interest, unknown. "
            "When set, this overrides include_interest."
        ),
    ),
    order_by: str = Query("name"),
    order_direction: str = Query("asc"),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "recognition_manager",
        )
        await factory.get_connection_manager(session, controller.id, "protect")
        result = await mgr.list_known_faces(
            page_size=1000,
            min_confidence=min_confidence,
            include_interest=include_interest,
            group_types=group_types,
            order_by=order_by,
            order_direction=order_direction,
        )

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(result.get("faces", [])),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_known_face_key,
    )

    type_class = request.app.state.type_registry.lookup("protect", "known_faces")
    items = [type_class.from_manager_output(face).to_dict() for face in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/known-license-plates",
    response_model=Page[to_pydantic_model(KnownLicensePlate)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/recognition"],
)
async def list_known_license_plates(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None),
    min_confidence: int = Query(30, ge=0, le=100),
    include_interest: bool = Query(True),
    group_types: list[str] | None = Query(
        None,
        description=(
            "Explicit recognition group types to list. Supported values: known, interest, unknown. "
            "When set, this overrides include_interest."
        ),
    ),
    order_by: str = Query("name"),
    order_direction: str = Query("asc"),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "recognition_manager",
        )
        await factory.get_connection_manager(session, controller.id, "protect")
        result = await mgr.list_known_license_plates(
            page_size=1000,
            min_confidence=min_confidence,
            include_interest=include_interest,
            group_types=group_types,
            order_by=order_by,
            order_direction=order_direction,
        )

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(result.get("license_plates", [])),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_known_license_plate_key,
    )

    type_class = request.app.state.type_registry.lookup("protect", "known_license_plates")
    items = [type_class.from_manager_output(plate).to_dict() for plate in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


def _detection_key(obj) -> tuple:
    raw = obj if isinstance(obj, dict) else getattr(obj, "raw", {}) or {}
    return (0, raw.get("id") or "")


@router.get(
    "/sites/{site_id}/detection-search",
    response_model=Page[to_pydantic_model(SmartDetection)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/recognition"],
)
async def search_detections(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
    labels: list[str] = Query(
        ...,
        description=(
            "Filter labels of the form 'prefix:value' (e.g. ['vehicleType:truck', 'color:black']). "
            "At least one is required; all are applied together. Use the detection-search-labels "
            "endpoint to discover legal values."
        ),
    ),
    search_limit: int = Query(100, ge=1, le=1000),
    order: str = Query("desc"),
    exclude_motion: bool = Query(True),
    min_confidence: int | None = Query(None, ge=0, le=100),
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
            "event_manager",
        )
        await factory.get_connection_manager(session, controller.id, "protect")
        try:
            result = await mgr.search_detections(
                labels=labels,
                limit=search_limit,
                order=order,
                exclude_motion=exclude_motion,
                min_confidence=min_confidence,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    cursor_obj = _decode_cursor(cursor)
    page, next_cursor = paginate(
        list(result.get("detections", [])),
        limit=limit,
        cursor=cursor_obj,
        key_fn=_detection_key,
    )

    type_class = request.app.state.type_registry.lookup_tool("protect_search_detections")[0]
    items = [type_class.from_manager_output(d).to_dict() for d in page]
    hint = type_class.render_hint("list")

    return {
        "items": items,
        "next_cursor": next_cursor.encode() if next_cursor else None,
        "render_hint": hint,
    }


@router.get(
    "/sites/{site_id}/detection-search-labels",
    response_model=to_pydantic_model(DetectionSearchLabels),
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["protect/recognition"],
)
async def detection_search_labels(
    request: Request,
    site_id: str,
    controller=Depends(resolve_controller),
) -> dict:
    require_capability(controller, "protect")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "protect",
            "event_manager",
        )
        await factory.get_connection_manager(session, controller.id, "protect")
        raw = await mgr.get_detection_search_labels()

    type_class = request.app.state.type_registry.lookup_tool("protect_detection_search_labels")[0]
    return type_class.from_manager_output(raw).to_dict()
