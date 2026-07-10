"""Auth and policy resolution core. Reusable across MCP servers and the rich HTTP API."""

from __future__ import annotations

import inspect
import types
from typing import Annotated, Any, Callable, Union, get_args, get_origin

from pydantic import TypeAdapter

_VALIDATION_SCHEMA_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "uniqueItems",
        "minProperties",
        "maxProperties",
    }
)


def _validation_schema_keywords(annotation: Any) -> dict[str, Any]:
    """Extract only validation keywords supported by the compact manifest dialect."""
    annotation_schema = TypeAdapter(annotation).json_schema()
    validation = {key: annotation_schema[key] for key in _VALIDATION_SCHEMA_KEYWORDS if key in annotation_schema}

    any_of = annotation_schema.get("anyOf")
    if isinstance(any_of, list):
        non_null_branches = [branch for branch in any_of if isinstance(branch, dict) and branch.get("type") != "null"]
        if len(non_null_branches) == 1:
            branch = non_null_branches[0]
            validation.update({key: branch[key] for key in _VALIDATION_SCHEMA_KEYWORDS if key in branch})

    return validation


def _infer_input_schema(func: Callable, tool_name: str, logger: Any) -> dict[str, Any]:
    """Infer JSON Schema input_schema from function type annotations.

    Walks ``inspect.signature(func)`` and produces an ``{"type": "object", ...}``
    JSON Schema describing each parameter. Handles ``Annotated[T, Field(...)]``
    metadata, ``Optional`` / ``X | None`` unions, and the common scalar/container
    types (``int``, ``bool``, ``float``, ``dict``, ``list``).

    Used by the MCP ``@permissioned_tool`` decorator to derive ``input_schema``
    when callers don't pass one explicitly. Also reusable by non-MCP HTTP handlers
    that need to publish a JSON Schema for their request body from the handler's
    own type annotations.
    """
    try:
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls") or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue

            param_type = "string"
            param_description = None

            if param.annotation != inspect.Parameter.empty:
                ann = param.annotation
                schema_annotation = ann

                # Unwrap Annotated[T, Field(...)]
                if get_origin(ann) is Annotated:
                    annotated_args = get_args(ann)
                    ann = annotated_args[0] if annotated_args else ann
                    for metadata in annotated_args[1:]:
                        if hasattr(metadata, "description") and metadata.description:
                            param_description = metadata.description
                            break

                # Unwrap Optional / X | None unions
                if isinstance(ann, types.UnionType) or get_origin(ann) is Union:
                    args = get_args(ann)
                    non_none = [a for a in args if a is not types.NoneType]
                    if non_none:
                        ann = non_none[0]

                origin = get_origin(ann)
                if origin is dict or ann in (dict, "dict"):
                    param_type = "object"
                elif origin is list or ann in (list, "list"):
                    param_type = "array"
                elif ann in (int, "int"):
                    param_type = "integer"
                elif ann in (bool, "bool"):
                    param_type = "boolean"
                elif ann in (float, "float"):
                    param_type = "number"

            prop: dict[str, Any] = {"type": param_type}
            if param_description:
                prop["description"] = param_description
            if param.annotation != inspect.Parameter.empty:
                try:
                    prop.update(_validation_schema_keywords(schema_annotation))
                except Exception as exc:
                    logger.debug(
                        "Could not infer validation constraints for %s.%s: %s",
                        tool_name,
                        param_name,
                        exc,
                    )
            properties[param_name] = prop

            if param.default == inspect.Parameter.empty:
                required.append(param_name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    except Exception as exc:
        logger.debug("Could not infer input schema for %s: %s", tool_name, exc)
        return {"type": "object", "properties": {}}
