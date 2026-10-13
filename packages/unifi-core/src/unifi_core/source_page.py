"""One bounded read from a product source, with the transport facts evidence needs.

Managers return a :class:`SourcePage` from their ``*_page`` methods so that
remote totals, continuation state, the cap and offset actually transmitted,
the bounds actually submitted, and rows the manager could not read survive
the manager boundary. List-returning manager methods stay unchanged for
tools; incident evidence is built from pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourcePage:
    # Every row the source returned for this read, in order, including rows
    # that are not objects; evidence counts those as malformed.
    rows: list[Any] = field(default_factory=list)
    # True when more matching rows exist beyond this read, False only when the
    # source showed the read reached the end, None when nothing establishes either.
    has_more: bool | None = None
    # The source's own count of matching rows, when it reports one.
    total_reported: int | None = None
    # Rows skipped before this read, and the most rows this read could return.
    offset: int | None = None
    cap: int | None = None
    # Which API path answered (``"v2"`` or ``"legacy"`` for Network).
    api_path: str | None = None
    # Epoch-millisecond ``(from, to)`` bounds sent to the source, when absolute.
    submitted_window_ms: tuple[int, int] | None = None
    # Rows were dropped by a filter applied after the source's cap.
    post_filtered: bool = False

    @property
    def records(self) -> list[dict[str, Any]]:
        """The rows that are objects."""
        return [row for row in self.rows if isinstance(row, dict)]

    @property
    def malformed(self) -> int:
        return len(self.rows) - len(self.records)
