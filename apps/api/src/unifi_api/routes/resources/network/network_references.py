"""Network references read.

GET /sites/{site_id}/networks/{network_id}/references — what references a
network, read from the session objects that name it: WLANs, port profiles,
switch-port overrides, V2 firewall policies and clients.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.graphql.pydantic_export import to_pydantic_model
from unifi_api.graphql.types.network.network_references import NetworkReferences
from unifi_api.routes.resources._common import (
    require_capability,
    resolve_controller,
)
from unifi_api.routes.resources.network._network_reference_errors import reference_read
from unifi_api.services.pydantic_models import Detail

router = APIRouter()


def _redact_sensitive(request: Request) -> bool:
    return request.app.state.config.policy.response.redact_sensitive_fields


@router.get(
    "/sites/{site_id}/networks/{network_id}/references",
    response_model=Detail[to_pydantic_model(NetworkReferences)],
    dependencies=[Depends(require_scope(Scope.READ))],
    tags=["network/network_references"],
    description=(
        "What references a network: Wi-Fi networks, port profiles, switch-port overrides, "
        "V2 firewall policies and clients. network_id is the network's _id from "
        "unifi_list_networks. A family whose read failed is listed in unavailable instead of "
        "being reported as empty."
    ),
)
async def get_network_references(
    request: Request,
    site_id: str,
    network_id: str,
    controller=Depends(resolve_controller),
    include_clients: bool = Query(True),
) -> dict:
    require_capability(controller, "network")
    factory = request.app.state.manager_factory
    sm = request.app.state.sessionmaker
    async with sm() as session:
        mgr = await factory.get_domain_manager(
            session,
            controller.id,
            "network",
            "network_reference_manager",
            site=site_id,
        )
        references = await reference_read(mgr.get_network_references(network_id, include_clients=include_clients))
    type_registry = request.app.state.type_registry
    tool_type = type_registry.lookup_tool("unifi_get_network_references")
    if tool_type is not None:
        type_class, kind = tool_type
        data = type_class.from_manager_output(references, redact_sensitive=_redact_sensitive(request)).to_dict()
        hint = type_class.render_hint(kind)
    else:
        registry = request.app.state.serializer_registry
        serializer = registry.serializer_for_tool("unifi_get_network_references")
        data = serializer.serialize(references)
        hint = registry.render_hint_for_tool("unifi_get_network_references")
    return {"data": data, "render_hint": hint}
