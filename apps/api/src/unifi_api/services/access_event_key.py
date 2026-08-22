"""Canonical ordering key for UniFi Access event rows.

Both API surfaces — the GraphQL resolver and the REST resource route — must
agree on this, because cursor pagination windows with a strict
``(ts, id) < (last_ts, last_id)``: two rows sharing a key make the next page
drop both, and a key that differs between requests silently skips or repeats
rows.

Lives here rather than in ``unifi-core`` deliberately. ``apps/api`` pins a
released ``unifi-core`` floor, so importing a brand-new symbol from it would
raise ImportError on a fresh PyPI install until a release carries it — the
same class of break the pin-alignment gate catches for whole modules. The API
layer is the only consumer of this ordering, so it is also its natural home.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

__all__ = ["event_sort_key"]


def _get(raw: Any, key: str) -> Any:
    if isinstance(raw, dict):
        return raw.get(key)
    return getattr(raw, key, None)


# Epoch seconds and epoch milliseconds both appear: system-log rows use millis
# (``published``) while legacy/websocket rows carry seconds. Left unconverted, a
# seconds row keys ~1000x lower than a millis row for the same instant, so in a
# mixed list every legacy row sinks to the bottom and can be stranded past the
# cursor window. Anything below this bound cannot plausibly be millis (it would
# be 1973), so it is seconds.
_MILLIS_LOWER_BOUND = 100_000_000_000


def _to_millis(value: int) -> int:
    if 0 < value < _MILLIS_LOWER_BOUND:
        return value * 1000
    return value


def _sortable_millis(value: Any) -> int:
    """Coerce an event time to sortable epoch milliseconds.

    Access event times arrive in three shapes: ``published`` as epoch millis on
    system-log rows, an ISO 8601 string once normalised, and a bare number on
    legacy/websocket rows. A plain ``int()`` raises ``ValueError`` on the ISO
    form, which is enough to take a whole events query down.
    """
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return _to_millis(int(value))
    text = str(value).strip()
    if not text:
        return 0
    try:
        return _to_millis(int(text))
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if parsed.tzinfo is None:
        # A naive string would otherwise be read in the host's local zone,
        # which misorders it against the "+00:00" rows by the UTC offset and
        # makes the key differ between workers in different timezones - so a
        # cursor minted by one would window wrongly on another.
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def event_sort_key(raw: Any) -> tuple[int, str]:
    """Return a stable ``(time, identity)`` ordering key for an event row.

    System-log rows are why the identity is not simply ``id`` — they carry
    ``id: ""``, so without a fallback every row of a page collapses onto the
    same key and page 2 comes back empty. The fallback digests the fields that
    actually distinguish a row, so it stays stable across requests.
    """
    published = _get(raw, "published")
    ts = _sortable_millis(published) if published is not None else 0
    if not ts:
        ts = _sortable_millis(_get(raw, "timestamp") or _get(raw, "time"))

    identity = _get(raw, "id") or ""
    if not identity:
        # ``metadata`` carries the door and actor. Without them two same-
        # millisecond rows for different doors with the same rendered message
        # digest identically - reproducing in miniature the shared-key failure
        # this function exists to prevent.
        metadata = _get(raw, "metadata")
        parts = [str(_get(raw, key) or "") for key in ("published", "log_key", "event_type", "message", "result")]
        if isinstance(metadata, dict):
            for entry_key in ("door", "actor", "device", "credential"):
                entry = metadata.get(entry_key)
                parts.append(str(entry.get("id") or "") if isinstance(entry, dict) else "")
        basis = "|".join(parts)
        identity = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]
    return (ts, str(identity))
