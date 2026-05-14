"""Shared dependencies for REST resource endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request

from unifi_api.db.models import Controller
from unifi_api.services.controllers import (
    ControllerNotFound,
    get_controller,
    list_controllers,
)


async def resolve_controller(
    request: Request,
    controller: str | None = Query(None, description="Controller UUID; omit to use default"),
) -> Controller:
    sm = request.app.state.sessionmaker
    async with sm() as session:
        if controller:
            try:
                return await get_controller(session, controller)
            except ControllerNotFound:
                raise HTTPException(status_code=404, detail="controller not found")
        rows = await list_controllers(session)
        defaults = [r for r in rows if r.is_default]
        if not defaults:
            raise HTTPException(
                status_code=400,
                detail="no default controller configured; specify ?controller=<id>",
            )
        return defaults[0]


def require_capability(controller: Controller, product: str) -> None:
    products = [p for p in controller.product_kinds.split(",") if p]
    if product not in products:
        raise HTTPException(
            status_code=409,
            detail={
                "kind": "capability_mismatch",
                "missing_product": product,
                "available_products": products,
            },
        )


def _pagination_dep(
    limit: int = Query(50, ge=1, le=200, description="Items per page"),
    cursor: str | None = Query(None, description="Opaque pagination cursor"),
) -> tuple[int, str | None]:
    return (limit, cursor)


PaginationParams = Annotated[tuple[int, str | None], Depends(_pagination_dep)]
