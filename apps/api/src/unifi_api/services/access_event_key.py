"""Canonical ordering key for UniFi Access event rows.

Both API surfaces — the GraphQL resolver and the REST resource route — must
agree on this, because cursor pagination windows with a strict
``(ts, id) < (last_ts, last_id)``: two rows sharing a key make the next page
drop both, and a key that differs between requests silently skips or repeats
rows.

The identity half is not computed here. ``unifi_core`` already assigns every
Access row a stable public identity — the controller's own ID when it has
one, otherwise a digest over the row's complete canonical payload — and this
module defers to it. An earlier version digested a hand-picked subset of
fields instead, which collided for two admin rows differing only at
``metadata.user.id`` and lost one row from a 68-row cursor traversal. A subset
cannot be shown to be exhaustive; the whole row can.

The time half does belong here: ordering is an API-surface concern, and the
raw rows carry time in three different shapes that have to sort against each
other.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from unifi_core.access.models.events import event_identity

__all__ = ["event_sort_key"]

# Not controller data: a process-local arrival stamp that changes every time a
# websocket row is buffered, so including it would give one event a different
# identity on each read. ``unifi_core`` excludes it for the same reason.
_LOCAL_ONLY_FIELDS = frozenset({"_buffered_at"})


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


def _whole_row_digest(raw: dict[str, Any]) -> str:
    """Digest a complete row, for the shapes ``event_identity`` declines.

    It returns ``None`` for a row that is neither identified nor recognisably a
    system-log record. Such a row still has to sort deterministically against
    its neighbours, and only its full content can distinguish it.
    """
    canonical = {key: value for key, value in raw.items() if key not in _LOCAL_ONLY_FIELDS and key != "id"}
    try:
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        # Controller rows are JSON, so this is defensive. ``default=str`` keeps
        # a value that is merely unserialisable (a datetime, a Decimal) from
        # collapsing the whole row onto a shared key.
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_sort_key(raw: Any) -> tuple[int, str]:
    """Return a stable ``(time, identity)`` ordering key for an event row.

    System-log rows are why the identity is not simply ``id``: the controller
    leaves it empty on those, so without a content identity every row of a page
    collapses onto the same key and the next page comes back short.
    """
    published = _get(raw, "published")
    ts = _sortable_millis(published) if published is not None else 0
    if not ts:
        ts = _sortable_millis(_get(raw, "timestamp") or _get(raw, "time"))

    identity = event_identity(raw)
    if not identity:
        # Both call sites unwrap ``.raw`` to a dict before calling, so the
        # non-dict branch is defensive; there is nothing to digest there.
        identity = _whole_row_digest(raw) if isinstance(raw, dict) else str(_get(raw, "id") or "")
    return (ts, str(identity))
