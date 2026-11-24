"""Argument types shared by the tools.

Kept outside ``tools/`` so that importing them registers no tool: a tool
module imported for its types would register its own tools past the category
filter. The schema advertises the accepted values and range, but the
framework does not enforce them (``json_schema_extra``): the managers validate
strictly and answer a bad value with fixed text that never repeats it.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, WithJsonSchema, create_model

PlanId = Annotated[
    str,
    Field(
        description=(
            "InnerSpace floor plan id, from innerspace_list_floor_plans. These IDs are scoped to the InnerSpace "
            "tool family — do not pass them to other products' tools."
        )
    ),
]
SiteId = Annotated[
    str | None,
    Field(
        description=(
            "InnerSpace site id to filter by. Omit for every site. These IDs are scoped to the InnerSpace tool "
            "family — do not pass them to other products' tools."
        )
    ),
]
Unit = Annotated[
    Literal["metric", "imperial"] | None,
    Field(
        description=(
            "Length unit of the result: 'metric' (metres) or 'imperial' (feet). Omit to use the project's own unit."
        ),
    ),
]
Limit = Annotated[
    int,
    Field(
        description="Maximum entries to return, 1 to 2000. The result reports the total and whether it was cut.",
        json_schema_extra={"minimum": 1, "maximum": 2000},
    ),
]
IncludeShapes = Annotated[
    bool,
    Field(description="When true, also returns every shape of the project with converted geometry (large)."),
]
# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------

FAMILY = "These IDs are scoped to the InnerSpace tool family — do not pass them to other products' tools."
CONFIRM_FLOW = "Previews unless confirm=true."
PARTIAL_UPDATE = "Pass only the fields you want to change — current values are automatically preserved."


def _inline(schema: dict[str, Any]) -> dict[str, Any]:
    """``schema`` with every ``$ref`` replaced by its definition, so it can sit under one property."""
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(definitions[node["$ref"].rsplit("/", 1)[1]])
            # A "title" annotation is a string; a property named title is a schema.
            return {key: resolve(value) for key, value in node.items() if key != "title" or not isinstance(value, str)}
        if isinstance(node, list):
            return [resolve(value) for value in node]
        return node

    return resolve(schema)


def input_schema(**params: Any) -> dict[str, Any]:
    """A write tool's complete input schema, for the tool index and the manifest.

    Each parameter is its type (required) or ``(type, default)``, in the order of the tool's signature.
    """
    fields = {name: spec if isinstance(spec, tuple) else (spec, ...) for name, spec in params.items()}
    schema = _inline(create_model("Arguments", **fields).model_json_schema())
    return {**schema, "additionalProperties": False}


def item_list(model: type[BaseModel], description: str, max_items: int) -> Any:
    """A list of objects advertised with ``model``'s fields; the manager validates each item strictly."""
    return Annotated[
        list[dict[str, Any]],
        WithJsonSchema(
            {
                "type": "array",
                "items": _inline(model.model_json_schema()),
                "minItems": 1,
                "maxItems": max_items,
                "description": description,
            }
        ),
    ]


def id_list(noun: str, max_items: int) -> Any:
    """Ids of objects to remove, advertised with the cap; the manager enforces it."""
    description = f"Ids of the {noun} to remove, at most {max_items} per call. {FAMILY}"
    schema = {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": max_items}
    return Annotated[list[str], WithJsonSchema({**schema, "description": description})]


_CONFIRM = (
    "When true, re-reads, sends one request and reads the change back; if the outcome is unknown, read before "
    "retrying. When false (default), returns a preview from a fresh read."
)
Confirm = Annotated[bool, Field(description=_CONFIRM)]
ConfirmCreate = Annotated[
    bool,
    Field(
        description=(
            _CONFIRM + " New ids follow from the arguments, so repeating a confirm that already landed sends nothing "
            "and reports already applied; use different arguments for an intentional copy."
        )
    ),
]
WriteUnit = Annotated[
    str,
    Field(
        description=(
            "Unit of every length and coordinate in this call: 'metric' (metres) or 'imperial' (feet). Required, "
            "so a change of the project's unit cannot rescale a call."
        ),
        json_schema_extra={"enum": ["metric", "imperial"]},
    ),
]
Coordinates = Annotated[
    str,
    Field(
        description=(
            "'frame' (default): the frame the reads return, from the plan's top-left, y down, in unit; refused on "
            "a plan whose image is shifted or scaled. 'plan_units': the console's own stored values."
        ),
        json_schema_extra={"enum": ["frame", "plan_units"]},
    ),
]
AttenuationDb = Annotated[float, Field(description="Signal loss in dB, 0 to 99.")]
Color = Annotated[str, Field(description="Display color as #RRGGBB.")]
TypeName = Annotated[str, Field(description="Name, 1 to 32 characters.")]
NewAttenuationDb = Annotated[float | None, Field(description="New signal loss in dB, 0 to 99. Omit to keep.")]
NewColor = Annotated[str | None, Field(description="New display color as #RRGGBB. Omit to keep.")]
NewTypeName = Annotated[str | None, Field(description="New name, 1 to 32 characters. Omit to keep.")]
