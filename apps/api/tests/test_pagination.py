"""Cursor + paginate() tests."""

import base64
import json

import pytest
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate


def test_cursor_encode_decode_roundtrip() -> None:
    c = Cursor(last_id="aa:bb:cc", last_ts=1000)
    encoded = c.encode()
    assert isinstance(encoded, str)
    decoded = Cursor.decode(encoded)
    assert decoded.last_id == "aa:bb:cc"
    assert decoded.last_ts == 1000


@pytest.mark.parametrize("last_ts", ["2026-08-18T12:00:00Z", 1787054400.75])
def test_cursor_roundtrip_preserves_emitted_timestamp_scalars(last_ts) -> None:
    cursor = Cursor(last_id="event-id", last_ts=last_ts)
    assert Cursor.decode(cursor.encode()) == cursor


def test_cursor_decode_invalid_raises() -> None:
    with pytest.raises(InvalidCursor):
        Cursor.decode("not-base64-or-json")


@pytest.mark.parametrize(
    "payload",
    [
        {"last_id": "evt", "last_ts": 1000, "resource": "access_events", "version": 1},
        {"last_id": "evt"},
    ],
)
def test_cursor_decode_rejects_non_legacy_payload_shapes(payload) -> None:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(InvalidCursor, match="exact legacy cursor payload"):
        Cursor.decode(encoded)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"last_id": True, "last_ts": 1000}, "last_id must be a string or integer"),
        ({"last_id": ["evt"], "last_ts": 1000}, "last_id must be a string or integer"),
        ({"last_id": "evt", "last_ts": False}, "last_ts must be a string, integer, float, or null"),
        (
            {"last_id": "evt", "last_ts": {"millis": 1000}},
            "last_ts must be a string, integer, float, or null",
        ),
    ],
)
def test_cursor_decode_rejects_invalid_value_types(payload, error) -> None:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(InvalidCursor, match=error):
        Cursor.decode(encoded)


def test_paginate_first_page_no_cursor() -> None:
    items = [{"id": str(i), "ts": i} for i in range(10)]
    page, next_cursor = paginate(items, limit=3, cursor=None, key_fn=lambda x: (x["ts"], x["id"]))
    assert len(page) == 3
    assert next_cursor is not None
    assert next_cursor.last_id == page[-1]["id"]


def test_paginate_returns_no_cursor_when_done() -> None:
    items = [{"id": "1", "ts": 1}]
    page, next_cursor = paginate(items, limit=10, cursor=None, key_fn=lambda x: (x["ts"], x["id"]))
    assert page == items
    assert next_cursor is None


def test_paginate_continuation_with_cursor() -> None:
    items = [{"id": str(i), "ts": i} for i in range(10)]
    page1, next_c = paginate(items, limit=4, cursor=None, key_fn=lambda x: (x["ts"], x["id"]))
    assert len(page1) == 4
    page2, next_c2 = paginate(items, limit=4, cursor=next_c, key_fn=lambda x: (x["ts"], x["id"]))
    # No overlap between pages
    p1_ids = {x["id"] for x in page1}
    p2_ids = {x["id"] for x in page2}
    assert p1_ids.isdisjoint(p2_ids)
