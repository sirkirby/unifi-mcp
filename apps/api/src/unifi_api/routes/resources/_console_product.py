"""REST read plumbing shared by the console products: capability check, the shared read, response shaping."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from unifi_api.db.models import Controller
from unifi_api.routes.resources._common import require_capability
from unifi_api.services.console_product import ConsoleProduct, map_error, read


class ConsoleResources:
    """The ``read``, ``detail`` and ``items`` helpers of one console product's resource routes."""

    def __init__(self, product: ConsoleProduct) -> None:
        self.product = product

    async def read(
        self,
        request: Request,
        controller: Controller,
        *,
        manager_attr: str,
        method: str,
        operation: str,
        args: tuple[Any, ...] = (),
        **kwargs: Any,
    ) -> Any:
        require_capability(controller, self.product.key)
        state = request.app.state
        return await read(
            self.product,
            sessionmaker=state.sessionmaker,
            factory=state.manager_factory,
            controller_id=controller.id,
            manager_attr=manager_attr,
            method=method,
            operation=operation,
            args=args,
            kwargs=kwargs,
        )

    def detail(self, request: Request, tool: str, result: Any, *, operation: str) -> dict:
        """One result, projected; a result it cannot project maps like any other read failure."""
        type_class, kind, redact = _projection(request, tool)
        try:
            data = type_class.from_manager_output(result, redact_sensitive=redact).to_dict()
        except Exception as exc:
            raise map_error(self.product, exc, operation) from None
        return {"data": data, "render_hint": type_class.render_hint(kind)}

    def items(self, request: Request, tool: str, result: list[Any], *, operation: str) -> dict:
        """The whole list: console product lists are not paged, so there is no cursor."""
        type_class, kind, redact = _projection(request, tool)
        try:
            data = [type_class.from_manager_output(item, redact_sensitive=redact).to_dict() for item in result]
        except Exception as exc:
            raise map_error(self.product, exc, operation) from None
        return {"items": data, "render_hint": type_class.render_hint(kind)}


def _projection(request: Request, tool: str) -> tuple[type, str, bool]:
    type_class, kind = request.app.state.type_registry.lookup_tool(tool)
    return type_class, kind, request.app.state.config.policy.response.redact_sensitive_fields
