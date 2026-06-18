"""Fail-closed guard for the typed-projection redaction contract.

The action endpoint (``routes/actions.py``) only threads ``redact_sensitive``
into a Strawberry type's ``from_manager_output`` when that signature *declares*
the parameter (``_type_accepts_redact_sensitive``). That reflection gate is
fail-open: a secret-bearing projection that forgets the ``redact_sensitive``
keyword would serialize raw secrets with no error and no policy enforcement.

This test closes that seam at CI time: any registered projection whose own
fields name secret material (per the shared ``is_sensitive_key`` vocabulary)
MUST accept ``redact_sensitive`` so the policy can blank them. A new type that
projects a sensitive field without the flag fails here instead of leaking.
"""

from __future__ import annotations

import dataclasses
import inspect

from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_core.redaction import is_sensitive_key


def _registered_type_classes() -> list[type]:
    """Every distinct type class registered for a tool or resource projection."""
    registry = build_type_registry()
    seen: dict[str, type] = {}
    for tool_name in registry.all_tools():
        type_class, _kind = registry.lookup_tool(tool_name)
        seen[type_class.__name__] = type_class
    for product, resource in registry.all_resources():
        type_class = registry.lookup(product, resource)
        seen[type_class.__name__] = type_class
    return list(seen.values())


def _accepts_redaction_flag(type_class: type) -> bool:
    from_manager = getattr(type_class, "from_manager_output", None)
    if from_manager is None:
        return True  # not a projection entry point; nothing to gate
    return "redact_sensitive" in inspect.signature(from_manager).parameters


def _sensitive_field_names(type_class: type) -> list[str]:
    if not dataclasses.is_dataclass(type_class):
        return []
    return [f.name for f in dataclasses.fields(type_class) if is_sensitive_key(f.name)]


def test_registered_projections_exist():
    # Sanity: the registry actually populated, so an empty iteration can't make
    # the guard below pass vacuously.
    assert _registered_type_classes(), "type registry produced no projections"


def test_sensitive_typed_fields_require_redaction_flag():
    offenders: list[tuple[str, list[str]]] = []
    for type_class in _registered_type_classes():
        if _accepts_redaction_flag(type_class):
            continue
        sensitive = _sensitive_field_names(type_class)
        if sensitive:
            offenders.append((type_class.__name__, sensitive))

    assert not offenders, (
        "Typed projections expose sensitive-named fields without accepting "
        "`redact_sensitive` — the reflection gate in routes/actions.py would "
        f"serialize these raw regardless of policy (fail-open): {offenders}"
    )
