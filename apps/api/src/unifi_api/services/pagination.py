"""Cursor-based pagination over in-memory snapshots.

UniFi managers return full snapshots (e.g., client_manager.get_clients
returns the entire list). Pagination is applied in-memory after the
manager call — no per-page round-trip to the controller. Future
managers with native cursoring can override per-resource.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass
from typing import Any, Callable


class InvalidCursor(Exception):
    pass


@dataclass(frozen=True)
class Cursor:
    last_id: str | int
    last_ts: str | int | float | None = None

    def encode(self) -> str:
        payload = json.dumps({"last_id": self.last_id, "last_ts": self.last_ts}).encode()
        return base64.urlsafe_b64encode(payload).decode()

    @classmethod
    def decode(cls, s: str) -> "Cursor":
        try:
            payload = json.loads(base64.urlsafe_b64decode(s.encode()).decode())
            if not isinstance(payload, dict) or set(payload) != {"last_id", "last_ts"}:
                raise ValueError("expected exact legacy cursor payload")
            last_id = payload["last_id"]
            last_ts = payload["last_ts"]
            if isinstance(last_id, bool) or not isinstance(last_id, (str, int)):
                raise ValueError("last_id must be a string or integer")
            if isinstance(last_ts, bool) or (last_ts is not None and not isinstance(last_ts, (str, int, float))):
                raise ValueError("last_ts must be a string, integer, float, or null")
            if isinstance(last_ts, float) and not math.isfinite(last_ts):
                raise ValueError("last_ts must be finite")
            return cls(last_id=last_id, last_ts=last_ts)
        except Exception as e:
            raise InvalidCursor(f"failed to decode cursor: {e}")


def paginate(
    items: list[Any],
    *,
    limit: int,
    cursor: Cursor | None,
    key_fn: Callable[[Any], tuple],
) -> tuple[list[Any], Cursor | None]:
    """Sort items by key_fn (descending), apply cursor windowing, return (page, next_cursor).

    key_fn returns (ts, id) — lexicographic descending sort. Cursor's last_ts/last_id
    cuts off items at-or-before that point.
    """
    sorted_items = sorted(items, key=key_fn, reverse=True)

    if cursor is not None:
        filtered = []
        for item in sorted_items:
            ts, id_ = key_fn(item)
            if cursor.last_ts is not None:
                if (ts, id_) < (cursor.last_ts, cursor.last_id):
                    filtered.append(item)
            else:
                # No-ts mode: just exclude items at or before last_id (less robust;
                # works when ids are sortable).
                if id_ < cursor.last_id:
                    filtered.append(item)
        sorted_items = filtered

    page = sorted_items[:limit]
    if len(sorted_items) > limit:
        last = page[-1]
        ts, id_ = key_fn(last)
        next_cursor: Cursor | None = Cursor(last_id=id_, last_ts=ts)
    else:
        next_cursor = None
    return page, next_cursor
