"""Paging parameter types shared by the list tools.

Kept outside ``tools/`` so that importing them registers no tool: a tool
module imported for its types would register its own tools past the category
filter.
"""

from typing import Annotated

from pydantic import Field

PageSize = Annotated[
    int | None,
    Field(description="Maximum entries in this page (1-500). Omit for the API default."),
]
Cursor = Annotated[
    str | None,
    Field(
        description=(
            "The next_cursor from a previous page. Omit for the first page. A page can hold fewer entries than "
            "page_size, even none: keep paging until next_cursor is absent."
        )
    ),
]
