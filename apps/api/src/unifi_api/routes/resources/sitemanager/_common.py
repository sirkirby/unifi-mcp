"""READ admission and common account projection, without console resolution."""

from fastapi import Request
from fastapi.routing import APIRoute

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.services.sitemanager_errors import SiteManagerAPIError
from unifi_api.services.sitemanager_reads import read_sitemanager

_require_read = require_scope(Scope.READ)


class AccountReadRoute(APIRoute):
    def __init__(self, *args, **kwargs):
        kwargs["openapi_extra"] = {**(kwargs.get("openapi_extra") or {}), "x-sitemanager-read": True}
        super().__init__(*args, **kwargs)

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def authorized_handler(request: Request):
            await _require_read(request)
            return await handler(request)

        return authorized_handler


async def read(request, tool, args, *, query_fields=None):
    if query_fields is not None and set(request.query_params) - set(query_fields):
        raise SiteManagerAPIError(400, "invalid_sitemanager_request", "Unsupported Site Manager query parameters.")
    state = request.app.state
    result = await read_sitemanager(
        registry=state.manifest_registry,
        type_registry=state.type_registry,
        factory=state.sitemanager_factory,
        tool_name=tool,
        args={key: value for key, value in args.items() if value is not None},
        redact_sensitive=state.config.policy.response.redact_sensitive_fields,
    )
    return result.rest()
