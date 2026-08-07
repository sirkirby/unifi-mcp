"""Catalog-driven REST action dispatch to per-controller Core managers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from sqlalchemy.ext.asyncio import AsyncSession
from unifi_core.confirmation import create_preview, delete_preview, preview_response
from unifi_core.redaction import redaction_marker_paths

from unifi_api.services.dispatch_overrides import (
    DISPATCH_ARG_TRANSLATORS,
    DISPATCH_DIRECT_RESULT_ADAPTERS,
    DISPATCH_RESULT_ADAPTERS,
    UNSUPPORTED_ACTION_PARAMETERS,
)
from unifi_api.services.managers import ManagerFactory
from unifi_api.services.manifest import ManifestRegistry, ToolEntry

_MUTATING_PERMISSION_ACTIONS = frozenset({"create", "update", "delete"})
_READ_PERMISSION_ACTIONS = frozenset({"", "read"})
INCLUDE_SENSITIVE_UNSUPPORTED_ERROR = (
    "include_sensitive is not supported; set UNIFI_API_REDACT_SENSITIVE_FIELDS=false or "
    "policy.response.redact_sensitive_fields=false to allow raw sensitive fields for this API surface."
)


class CapabilityMismatch(Exception):
    """Raised when an action's product is not supported by the controller."""


class DispatchEntryMissing(Exception):
    """Raised when a catalog entry has no callable Core manager binding."""


@dataclass(frozen=True)
class MutationPreview:
    """Validated, non-executed mutation intent for the API response layer."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class DispatchEntry:
    """Compatibility view used by focused tests; production binds from ToolEntry."""

    manager_attr: str
    method: str


def build_dispatch_table(products: Iterable[str] = ("network", "protect", "access")) -> dict[str, DispatchEntry]:
    """Return a catalog-derived binding view without inspecting sibling app source."""
    selected = set(products)
    registry = ManifestRegistry.load()
    return {
        name: DispatchEntry(entry.manager_attr, entry.manager_method)
        for name in registry.all_tools()
        if (entry := registry.resolve(name)).product in selected
    }


def _classify_action(entry: ToolEntry) -> str:
    """Return ``read`` or ``mutation`` only when both safety signals agree."""
    if entry.permission_action in _MUTATING_PERMISSION_ACTIONS and entry.read_only_hint is False:
        return "mutation"
    if entry.permission_action in _READ_PERMISSION_ACTIONS and entry.read_only_hint is True:
        return "read"
    raise ValueError(
        f"tool '{entry.name}' has invalid safety metadata "
        f"(permission_action={entry.permission_action!r}, readOnlyHint={entry.read_only_hint!r})"
    )


async def _resolve_result(result: Any) -> Any:
    return await result if inspect.isawaitable(result) else result


def _preview_resource_id(args: dict[str, Any]) -> str:
    """Return the first public resource identifier in stable argument order."""
    for name, value in args.items():
        if (name in {"id", "mac", "mac_address"} or name.endswith("_id")) and value not in (None, ""):
            return str(value)
    return "(not yet assigned)"


def _build_mutation_preview(entry: ToolEntry, site: str, args: dict[str, Any]) -> MutationPreview:
    """Build a Core-standard preview without resolving or invoking a manager."""
    resource_name = args.get("name")
    if not isinstance(resource_name, str):
        resource_name = None

    if entry.permission_action == "create":
        payload = create_preview(
            resource_type=entry.category,
            resource_data=dict(args),
            resource_name=resource_name,
        )
    elif entry.permission_action == "delete":
        payload = delete_preview(
            resource_type=entry.category,
            resource_id=_preview_resource_id(args),
            resource_name=resource_name,
            resource_data=dict(args),
        )
    else:
        payload = preview_response(
            action=entry.permission_action,
            resource_type=entry.category,
            resource_id=_preview_resource_id(args),
            resource_name=resource_name,
            current_state={},
            proposed_changes=dict(args),
        )

    payload.update(
        {
            "tool": entry.name,
            "product": entry.product,
            "site": site,
        }
    )
    return MutationPreview(payload)


def _validate_action_args(entry: ToolEntry, args: dict[str, Any]) -> None:
    """Validate raw REST args against the generated MCP input contract."""
    errors = sorted(
        Draft202012Validator(entry.input_schema).iter_errors(args),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if not errors:
        return
    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path)
    location = f" at args.{path}" if path else ""
    raise ValueError(f"Invalid action arguments for '{entry.name}'{location}: {error.message}")


async def dispatch_action(
    *,
    registry: ManifestRegistry,
    factory: ManagerFactory,
    session: AsyncSession,
    tool_name: str,
    controller_id: str,
    controller_products: list[str],
    site: str,
    args: dict,
    confirm: bool,
    dispatch_table: dict[str, DispatchEntry] | None = None,
) -> Any:
    """Resolve one validated catalog action and invoke its Core manager binding.

    ``dispatch_table`` remains only as an explicit unit-test seam for narrow
    translator tests. Production calls always use the binding packaged on the
    resolved catalog entry.
    """
    entry = registry.resolve(tool_name)
    if entry.product not in controller_products:
        raise CapabilityMismatch(
            f"tool '{tool_name}' requires product '{entry.product}', controller supports {controller_products!r}"
        )

    action_kind = _classify_action(entry)

    if dispatch_table is None:
        binding = DispatchEntry(entry.manager_attr, entry.manager_method)
    else:
        binding = dispatch_table.get(tool_name)
    if binding is None or not binding.manager_attr or not binding.method:
        raise DispatchEntryMissing(f"no Core manager binding for tool '{tool_name}'")

    _validate_action_args(entry, args)

    if "include_sensitive" in args:
        raise ValueError(INCLUDE_SENSITIVE_UNSUPPORTED_ERROR)
    marker_paths = redaction_marker_paths(args)
    if marker_paths:
        field = marker_paths[0]
        raise ValueError(
            f"Failed to dispatch {tool_name}: omit {field} to keep the current value; do not pass the redaction marker."
        )

    unsupported = sorted(set(args) & UNSUPPORTED_ACTION_PARAMETERS.get(tool_name, frozenset()))
    if unsupported:
        names = ", ".join(unsupported)
        raise ValueError(
            f"Action parameter(s) {names} are not supported by the typed API action endpoint; "
            "omit them or use the dedicated resource endpoint."
        )

    manager_args = dict(args)
    translator = DISPATCH_ARG_TRANSLATORS.get(tool_name)
    if translator is not None:
        positional, keyword = translator(manager_args)
    else:
        positional, keyword = (), manager_args

    if action_kind == "mutation" and not confirm:
        return _build_mutation_preview(entry, site, args)

    direct_adapter = DISPATCH_DIRECT_RESULT_ADAPTERS.get(tool_name)
    if direct_adapter is not None:
        handled, direct_result = direct_adapter(dict(args))
        if handled:
            return direct_result

    manager = await factory.get_domain_manager(
        session=session,
        controller_id=controller_id,
        product=entry.product,
        attr_name=binding.manager_attr,
        site=site,
    )

    method = getattr(manager, binding.method, None)
    if method is None or not callable(method):
        raise DispatchEntryMissing(
            f"manager '{binding.manager_attr}' has no callable method '{binding.method}' for tool '{tool_name}'"
        )

    result = await _resolve_result(method(*positional, **keyword))
    result_adapter = DISPATCH_RESULT_ADAPTERS.get(tool_name)
    if result_adapter is not None:
        result = result_adapter(result, dict(args), manager)
        result = await _resolve_result(result)
    if action_kind == "mutation" and (result is None or result is False):
        returned = "None" if result is None else "False"
        raise ValueError(f"tool '{tool_name}' reported failure (Core manager returned {returned})")
    return result
