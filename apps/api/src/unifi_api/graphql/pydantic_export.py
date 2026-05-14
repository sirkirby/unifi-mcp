"""Walker that derives a Pydantic model from a Strawberry type.

Single source of truth: the Strawberry types from Phase 6 are the canonical
projection layer. This walker derives the Pydantic mirror REST routes use
as ``response_model=...`` so OpenAPI shows real type information instead of
opaque dict.
"""

from __future__ import annotations

import datetime
from typing import Any, get_args, get_origin

import strawberry
from pydantic import BaseModel, ConfigDict, create_model
from strawberry.types.base import StrawberryList, StrawberryOptional
from strawberry.types.private import StrawberryPrivate

_MODEL_CACHE: dict[type, type[BaseModel]] = {}


def _is_private_field(field: Any) -> bool:
    """Return True if the field is marked strawberry.Private.

    In 0.315.x, Private fields are Annotated[T, StrawberryPrivate()] at the
    raw ``field.type`` level.
    """
    t = field.type
    if get_origin(t) is not None:
        # Annotated[...] form used for strawberry.Private
        for meta in get_args(t):
            if isinstance(meta, StrawberryPrivate):
                return True
    return False


def _strawberry_type_to_pydantic(strawberry_type_obj: Any) -> Any:
    """Map a Strawberry type object (field.type) to a Pydantic-compatible annotation.

    Handles:
    - StrawberryOptional wrapping any inner type
    - StrawberryList wrapping any inner type
    - strawberry.ID → str
    - Nested @strawberry.type → recurse via to_pydantic_model
    - Scalar primitives (str, int, bool, float, dict, datetime.datetime)
    - strawberry.scalars.JSON → Any
    - Annotated[...] private fields (already filtered upstream, but handled safely)
    - Fallback → Any
    """
    if isinstance(strawberry_type_obj, StrawberryOptional):
        inner = _strawberry_type_to_pydantic(strawberry_type_obj.of_type)
        return inner | None

    if isinstance(strawberry_type_obj, StrawberryList):
        inner = _strawberry_type_to_pydantic(strawberry_type_obj.of_type)
        return list[inner]  # type: ignore[valid-type]

    if strawberry_type_obj is strawberry.ID:
        return str

    if hasattr(strawberry_type_obj, "__strawberry_definition__"):
        return to_pydantic_model(strawberry_type_obj)

    # Strawberry-decorated enums expose Python's enum class via __strawberry_enum_definition__.
    # Pydantic v2 handles Python enums natively, so pass them through.
    if hasattr(strawberry_type_obj, "_enum_definition") or hasattr(
        strawberry_type_obj, "__strawberry_enum_definition__"
    ):
        return strawberry_type_obj

    if strawberry_type_obj in (str, int, bool, float, dict, datetime.datetime, type(None)):
        return strawberry_type_obj

    try:
        from strawberry.scalars import JSON

        if strawberry_type_obj is JSON:
            return Any
    except ImportError:
        pass

    return Any


def to_pydantic_model(strawberry_type: type) -> type[BaseModel]:
    """Derive a Pydantic model from a Strawberry ``@strawberry.type`` class.

    Cached per type. Skips ``strawberry.Private`` fields and ``@strawberry.field``
    resolver methods (cross-resource edges — not in ``to_dict``).
    """
    if strawberry_type in _MODEL_CACHE:
        return _MODEL_CACHE[strawberry_type]

    definition = getattr(strawberry_type, "__strawberry_definition__", None)
    if definition is None:
        raise TypeError(f"{strawberry_type.__name__} is not a Strawberry type")

    fields: dict[str, tuple[Any, Any]] = {}
    for field in definition.fields:
        if field.base_resolver is not None:
            # @strawberry.field resolver — cross-resource edge, not in to_dict()
            continue
        if _is_private_field(field):
            # strawberry.Private — internal context, not in to_dict()
            continue
        annotation = _strawberry_type_to_pydantic(field.type)
        fields[field.python_name] = (annotation, None)

    model = create_model(
        f"{strawberry_type.__name__}Model",
        # extra="allow": REST routes return manager-extra keys; Pydantic must not reject them.
        __config__=ConfigDict(extra="allow"),
        **fields,
    )
    _MODEL_CACHE[strawberry_type] = model
    return model
