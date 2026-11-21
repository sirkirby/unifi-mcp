"""Argument types shared by the tools.

Kept outside ``tools/`` so that importing them registers no tool: a tool
module imported for its types would register its own tools past the category
filter. The schema advertises the accepted values and range, but the
framework does not enforce them (``json_schema_extra``): the managers validate
strictly and answer a bad value with fixed text that never repeats it.
"""

from typing import Annotated, Literal

from pydantic import Field

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
