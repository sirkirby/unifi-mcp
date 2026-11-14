"""Read-only account actions with fixed, credential-free audit records."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from unifi_api.graphql.types.sitemanager._base import DESCRIPTION
from unifi_api.routes.resources.sitemanager._common import AccountReadRoute
from unifi_api.services.audit import write_audit
from unifi_api.services.sitemanager_errors import map_error
from unifi_api.services.sitemanager_reads import account_entry, read_sitemanager

router = APIRouter(route_class=AccountReadRoute)


class SiteManagerActionIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    args: dict = Field(default_factory=dict)


@router.post("/sitemanager/actions/{tool_name}", description=DESCRIPTION)
async def post_sitemanager_action(request: Request, tool_name: str, body: SiteManagerActionIn):
    state = request.app.state
    target, connection_id, error = "sitemanager.action", None, None
    try:
        entry = account_entry(state.manifest_registry, tool_name)
        target = entry.name
        result = await read_sitemanager(
            registry=state.manifest_registry,
            type_registry=state.type_registry,
            factory=state.sitemanager_factory,
            tool_name=entry.name,
            args=body.args,
            redact_sensitive=state.config.policy.response.redact_sensitive_fields,
        )
        connection_id = result.connection_id
    except Exception as exc:
        error = map_error(exc, "execute Site Manager read action")
        connection_id = getattr(error, "connection_id", None)
    try:
        async with state.sessionmaker() as session:
            await write_audit(
                session,
                key_id_prefix=request.state.api_key_prefix,
                controller=None,
                sitemanager_connection=connection_id,
                target=target,
                outcome="error" if error else "success",
                error_kind=error.kind if error else None,
            )
            await session.commit()
    except Exception as exc:
        error = map_error(exc, "record Site Manager action audit")
    if error is not None:
        raise error from None
    return result.action()
