"""Catalog-driven REST action dispatch to per-controller Core managers."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy.ext.asyncio import AsyncSession
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
    if not confirm and action_kind == "mutation":
        raise ValueError(f"tool '{tool_name}' requires confirm=true")

    if dispatch_table is None:
        binding = DispatchEntry(entry.manager_attr, entry.manager_method)
    else:
        binding = dispatch_table.get(tool_name)
    if binding is None or not binding.manager_attr or not binding.method:
        raise DispatchEntryMissing(f"no Core manager binding for tool '{tool_name}'")

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
    )

    if entry.product == "network":
        connection_manager = await factory.get_connection_manager(session, controller_id, "network")
        current_site = getattr(connection_manager, "site", None)
        if site and current_site != site:
            set_site = getattr(connection_manager, "set_site", None)
            if callable(set_site):
                await _resolve_result(set_site(site))

    method = getattr(manager, binding.method, None)
    if method is None or not callable(method):
        raise DispatchEntryMissing(
            f"manager '{binding.manager_attr}' has no callable method '{binding.method}' for tool '{tool_name}'"
        )

    manager_args = dict(args)
    translator = DISPATCH_ARG_TRANSLATORS.get(tool_name)
    if translator is not None:
        positional, keyword = translator(manager_args)
        result = await _resolve_result(method(*positional, **keyword))
    else:
        result = await _resolve_result(method(**manager_args))
    result_adapter = DISPATCH_RESULT_ADAPTERS.get(tool_name)
    if result_adapter is not None:
        result = result_adapter(result, dict(args), manager)
        result = await _resolve_result(result)
    return result
