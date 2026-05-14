"""Cursor + paginate() tests."""

import pytest
from unifi_api.services.pagination import Cursor, InvalidCursor, paginate


def test_cursor_encode_decode_roundtrip() -> None:
    c = Cursor(last_id="aa:bb:cc", last_ts=1000)
    encoded = c.encode()
    assert isinstance(encoded, str)
    decoded = Cursor.decode(encoded)
    assert decoded.last_id == "aa:bb:cc"
    assert decoded.last_ts == 1000


def test_cursor_decode_invalid_raises() -> None:
    with pytest.raises(InvalidCursor):
        Cursor.decode("not-base64-or-json")


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
