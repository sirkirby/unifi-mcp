"""Helpers for cross-layer (MCP pydantic ↔ API Strawberry) symmetry tests.

The symmetry test asserts that every field a pydantic domain model marks
as mutable also exists in the matching Strawberry read type with a
compatible type annotation. This catches a class of round-trip bug
where a caller reads a field via the API, then passes it back into an
MCP create/update, only to have the MCP layer reject or silently drop
it because the API exposed it under a different name or shape.
"""

from __future__ import annotations

import dataclasses
import types
import typing
from typing import Any, get_args, get_origin


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Strip a single layer of Optional[T] / T | None.

    Returns (inner, was_optional). For non-optional types, returns
    (annotation, False).
    """
    origin = get_origin(annotation)
    # typing.Optional and typing.Union
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    # PEP 604 X | None
    if origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _normalize_for_compare(annotation: Any) -> Any:
    """Return a comparable representation of a type annotation."""
    inner, _ = _unwrap_optional(annotation)
    origin = get_origin(inner)
    # list[T] / List[T] → ("list", T)
    if origin in (list,):
        args = get_args(inner)
        return ("list", _normalize_for_compare(args[0]) if args else None)
    # dict / dict[K, V] → "dict"
    if origin in (dict,):
        return "dict"
    return inner


def types_compatible(pydantic_annotation: Any, strawberry_annotation: Any) -> bool:
    """Decide whether a pydantic field annotation and a Strawberry field
    annotation describe compatible shapes.

    Compatibility rules:
    - Optional wrappers are stripped on both sides before comparison.
    - Literal[...] on the pydantic side compares as ``str`` against the
      Strawberry side (Strawberry frequently uses bare ``str``).
    - ``list[T]`` matches ``list[T]`` with recursive inner comparison.
    - ``dict`` (or ``dict[K, V]``) on the pydantic side matches
      ``strawberry.scalars.JSON`` on the Strawberry side.
    - Otherwise the two normalized types must be equal.
    """
    py_inner, _ = _unwrap_optional(pydantic_annotation)
    sb_inner, _ = _unwrap_optional(strawberry_annotation)

    # Literal[A, B, ...] on pydantic side → str-shaped
    if get_origin(py_inner) is typing.Literal:
        py_inner = str

    py_norm = _normalize_for_compare(py_inner)
    sb_norm = _normalize_for_compare(sb_inner)

    # pydantic dict / list[Any] / Any ↔ strawberry JSON scalar
    # All three pydantic shapes map to opaque structured data; Strawberry
    # represents them as the JSON scalar (arbitrary serialisable value).
    _is_any = py_inner is Any
    _is_list_any = isinstance(py_norm, tuple) and py_norm[0] == "list" and (py_norm[1] is Any or py_norm[1] == Any)
    if py_norm == "dict" or _is_any or _is_list_any:
        sb_repr = repr(sb_inner)
        if "JSON" in sb_repr or sb_norm == "dict":
            return True

    # strawberry.ID ↔ pydantic str / Optional[str]
    if py_inner is str:
        sb_repr = repr(sb_inner)
        if "ID" in sb_repr or sb_norm is str:
            return True

    return py_norm == sb_norm


def strawberry_fields(strawberry_cls: Any) -> dict[str, Any]:
    """Return {name: annotation} for every public field on a Strawberry type.

    Skips underscore-prefixed names and ``strawberry.Private[T]`` fields.
    Private detection inspects the raw ``field.type`` because
    ``typing.get_type_hints(..., include_extras=False)`` would strip the
    Private wrapper before we could see it.
    """
    out: dict[str, Any] = {}
    hints = typing.get_type_hints(strawberry_cls, include_extras=False)
    for field in dataclasses.fields(strawberry_cls):
        if field.name.startswith("_"):
            continue
        if "Private" in repr(field.type):
            continue
        annotation = hints.get(field.name, field.type)
        out[field.name] = annotation
    return out


def compare_pair(
    pydantic_cls: Any,
    mutable_fields: frozenset[str],
    strawberry_cls: Any,
) -> list[str]:
    """Compare one (pydantic, Strawberry) pair. Returns a list of error
    strings; empty list means compatible."""
    errors: list[str] = []
    sb_fields = strawberry_fields(strawberry_cls)

    for name in sorted(mutable_fields):
        if name not in sb_fields:
            errors.append(f"field '{name}' missing on Strawberry type {strawberry_cls.__name__}")
            continue
        py_annotation = pydantic_cls.model_fields[name].annotation
        sb_annotation = sb_fields[name]
        if not types_compatible(py_annotation, sb_annotation):
            errors.append(f"field '{name}': pydantic={py_annotation!r} incompatible with Strawberry={sb_annotation!r}")

    return errors
