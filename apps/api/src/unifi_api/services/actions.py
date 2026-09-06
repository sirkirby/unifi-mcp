"""Catalog-driven REST action dispatch to per-controller Core managers."""

from __future__ import annotations

import inspect
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from pydantic import ValidationError
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


def _effective_preview_args(
    entry: ToolEntry,
    args: dict[str, Any],
    translated_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Overlay translated public fields so previews match confirmed execution."""
    effective = dict(args)
    public_fields = entry.input_schema.get("properties", {})
    directly_overlaid: set[str] = set()
    for key in public_fields:
        if key in translated_kwargs:
            effective[key] = translated_kwargs[key]
            directly_overlaid.add(key)

    # Some public tools wrap one free-form object under a friendly name while
    # the manager uses a different payload name (for example
    # port_forward_data -> rule_data). Preserve the public wrapper but preview
    # the validated, default-expanded controller payload that confirmation uses.
    public_dict_keys = [
        key for key in public_fields if key not in directly_overlaid and isinstance(args.get(key), dict)
    ]
    translated_dicts = [value for value in translated_kwargs.values() if isinstance(value, dict)]
    if len(public_dict_keys) == 1 and len(translated_dicts) == 1:
        effective[public_dict_keys[0]] = translated_dicts[0]
    return effective


# A constraint longer than this is a schema dump, not a diagnostic.
_CONSTRAINT_REPR_MAX = 120


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
    # ``error.message`` embeds the submitted instance, so an operator value —
    # a credential in the worst case — would enter every sink this message
    # reaches: the HTTP body, the log and the durable audit row. The
    # schema-side facts identify the same failure and carry nothing the caller
    # sent.
    if error.validator == "required" and isinstance(error.instance, Mapping):
        # ``required`` carries no path, so it sorts first and is often the only
        # diagnostic the caller sees. The names come from the schema.
        missing = [name for name in error.validator_value if name not in error.instance]
        raise ValueError(f"Invalid action arguments for '{entry.name}': missing argument(s) {', '.join(missing)}")
    if error.validator == "additionalProperties" and isinstance(error.instance, Mapping):
        # jsonschema puts the offending key only in ``message``. A key is not
        # a value: the MCP side names it the same way in its unknown-argument
        # error.
        declared = error.schema.get("properties", {}) if isinstance(error.schema, Mapping) else {}
        patterned = error.schema.get("patternProperties", {}) if isinstance(error.schema, Mapping) else {}
        unexpected = sorted(
            key
            for key in set(error.instance) - set(declared)
            # A schema can also admit keys by pattern; those are declared, just
            # not by name, and naming them as unknown would send the caller
            # after the wrong argument.
            if not any(re.search(pattern, key) for pattern in patterned)
        )
        if unexpected:
            raise ValueError(
                f"Invalid action arguments for '{entry.name}'{location}: unknown argument(s) {', '.join(unexpected)}"
            )
    # A composite validator's value is the whole subschema tree, which is noise
    # in a durable audit row; the validator name alone says what failed.
    constraint = repr(error.validator_value)
    if error.validator in {"anyOf", "oneOf", "allOf", "not"} or len(constraint) > _CONSTRAINT_REPR_MAX:
        constraint = ""
    named = f"{error.validator or 'schema'}"
    detail = f"does not satisfy {named!r}" + (f": {constraint}" if constraint else "")
    raise ValueError(f"Invalid action arguments for '{entry.name}'{location}: {detail}")


def _value_free_validation_error(tool_name: str, error: ValidationError) -> ValueError:
    """Restate a pydantic validation failure without the caller's data.

    ``str(ValidationError)`` embeds ``input_value=``, truncated at about fifty
    characters — so a long credential survives as fragments that no
    value-matching scrub can find, all the way into the durable audit row.
    ``errors()`` without input, url or context carries the same diagnostic: the
    field and the failure. One residue remains — a custom validator writes its
    own text into ``msg`` as ``Value error, ...`` — which is why the audit
    sink's scrub stays behind this as a barrier.
    """
    details = error.errors(include_url=False, include_input=False, include_context=False)
    fields = "; ".join(
        f"{'.'.join(str(part) for part in detail['loc']) or '<root>'}: {detail['msg']}" for detail in details
    )
    return ValueError(f"Invalid action arguments for '{tool_name}': {fields}")


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
        try:
            positional, keyword = translator(manager_args)
        except ValidationError as e:
            raise _value_free_validation_error(tool_name, e) from None
    else:
        positional, keyword = (), manager_args

    if action_kind == "mutation" and not confirm:
        preview_args = _effective_preview_args(entry, args, keyword)
        return _build_mutation_preview(entry, site, preview_args)

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
