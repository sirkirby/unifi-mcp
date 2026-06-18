"""Action endpoint: POST /v1/actions/{tool_name}."""

from __future__ import annotations

import inspect
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope
from unifi_api.serializers._base import SerializerContractError
from unifi_api.serializers._registry import SerializerRegistryError
from unifi_api.services import actions as actions_svc
from unifi_api.services.audit import write_audit
from unifi_api.services.controllers import ControllerNotFound, get_controller
from unifi_api.services.manifest import ToolNotFound

router = APIRouter()


@lru_cache(maxsize=None)
def _type_accepts_redact_sensitive(type_class: type) -> bool:
    """Whether a Strawberry type's ``from_manager_output`` takes the redaction flag.

    Only the few types with secret fields (WLAN, SNMP, credentials) accept
    ``redact_sensitive``; the rest keep a single-arg signature. Cached per
    class so the reflection runs once, not per request.
    """
    return "redact_sensitive" in inspect.signature(type_class.from_manager_output).parameters


def _coerce_list_result(result: object, tool_name: str, kind: str) -> list:
    """Normalize a list-kind tool's manager output to a bare list.

    Most list tools return a bare list. The Protect recognition list tools
    (``protect_list_known_faces``, ``protect_list_known_license_plates``) return
    a dict envelope — ``{<items_key>: [...], "count": int, "links": {...}}`` —
    because their MCP surface carries pagination links. The GraphQL and REST
    surfaces unwrap that envelope themselves; the action path normalizes it here
    so all three behave the same. The envelope always holds exactly one
    list-valued key alongside scalar/dict metadata, so that single list is the
    item payload. Anything else (wrong shape, ambiguous multi-list dict) trips
    the same contract error as before.
    """
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        list_values = [value for value in result.values() if isinstance(value, list)]
        if len(list_values) == 1:
            return list_values[0]
    raise SerializerContractError(
        f"tool '{tool_name}' declared kind={kind} but manager returned {type(result).__name__}"
    )


class ActionIn(BaseModel):
    site: str
    controller: str
    args: dict = {}
    confirm: bool = False


@router.post(
    "/actions/{tool_name}",
    dependencies=[Depends(require_scope(Scope.WRITE))],
)
async def post_action(request: Request, tool_name: str, body: ActionIn) -> dict:
    sm = request.app.state.sessionmaker
    factory = request.app.state.manager_factory
    registry = request.app.state.manifest_registry
    serializer_registry = request.app.state.serializer_registry
    type_registry = request.app.state.type_registry
    key_prefix = getattr(request.state, "api_key_prefix", "(unknown)")

    if "include_sensitive" in body.args:
        return {"success": False, "error": actions_svc.INCLUDE_SENSITIVE_UNSUPPORTED_ERROR}

    async with sm() as session:
        try:
            controller = await get_controller(session, body.controller)
        except ControllerNotFound:
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=None,
                target=tool_name,
                outcome="error",
                error_kind="controller_not_found",
            )
            await session.commit()
            raise HTTPException(status_code=404, detail="controller not found")

        controller_products = [p for p in controller.product_kinds.split(",") if p]
        try:
            result = await actions_svc.dispatch_action(
                registry=registry,
                factory=factory,
                session=session,
                tool_name=tool_name,
                controller_id=body.controller,
                controller_products=controller_products,
                site=body.site,
                args=body.args,
                confirm=body.confirm,
            )
            redact_sensitive = request.app.state.config.policy.response.redact_sensitive_fields
            tool_type = type_registry.lookup_tool(tool_name)
            if tool_type is not None:
                # Phase 6 PR2 — read tool migrated to a Strawberry type. Shape
                # the manager output through Type.from_manager_output().to_dict()
                # and wrap with the same {"success", "data", "render_hint"}
                # envelope the dict-serializer used to produce.
                type_class, kind = tool_type
                hint = type_class.render_hint(kind)
                shape_kwargs = (
                    {"redact_sensitive": redact_sensitive} if _type_accepts_redact_sensitive(type_class) else {}
                )
                if kind in ("list", "timeseries", "event_log"):
                    items = _coerce_list_result(result, tool_name, kind)
                    data = [type_class.from_manager_output(x, **shape_kwargs).to_dict() for x in items]
                else:
                    data = type_class.from_manager_output(result, **shape_kwargs).to_dict()
                shaped = {"success": True, "data": data, "render_hint": hint}
            else:
                serializer = serializer_registry.serializer_for_tool(tool_name)
                shaped = serializer.serialize_action(result, tool_name=tool_name, redact_sensitive=redact_sensitive)
            outcome = "success" if shaped.get("success", True) else "error"
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=body.controller,
                target=tool_name,
                outcome=outcome,
            )
            await session.commit()
            return shaped
        except ToolNotFound:
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=body.controller,
                target=tool_name,
                outcome="error",
                error_kind="unknown_tool",
            )
            await session.commit()
            return {"success": False, "error": f"unknown tool: {tool_name}"}
        except actions_svc.CapabilityMismatch as e:
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=body.controller,
                target=tool_name,
                outcome="error",
                error_kind="capability_mismatch",
            )
            await session.commit()
            return {"success": False, "error": str(e)}
        except SerializerContractError as e:
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=body.controller,
                target=tool_name,
                outcome="error",
                error_kind="serializer_contract",
                detail=str(e),
            )
            await session.commit()
            raise HTTPException(
                status_code=500,
                detail={
                    "kind": "serializer_contract_error",
                    "tool": tool_name,
                    "detail": str(e),
                },
            )
        except SerializerRegistryError as e:
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=body.controller,
                target=tool_name,
                outcome="error",
                error_kind="serializer_missing",
                detail=str(e),
            )
            await session.commit()
            raise HTTPException(
                status_code=500,
                detail={
                    "kind": "serializer_missing",
                    "tool": tool_name,
                    "detail": str(e),
                },
            )
        except Exception as e:
            await write_audit(
                session,
                key_id_prefix=key_prefix,
                controller=body.controller,
                target=tool_name,
                outcome="error",
                error_kind=type(e).__name__,
                detail=str(e),
            )
            await session.commit()
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
