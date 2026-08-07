"""Marker result types shared by action dispatch and response routing."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ShapedReadResult:
    """A Core-shaped read result with its primary public data field."""

    payload: dict[str, Any]
    data_key: str
    render_hint: dict[str, Any] = field(default_factory=dict)
