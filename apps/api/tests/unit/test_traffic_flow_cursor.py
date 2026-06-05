"""Unit tests for the opaque traffic-flow cursor helpers."""

from __future__ import annotations

import pytest
from unifi_api.graphql.resolvers.network import (
    _decode_flow_cursor,
    _encode_flow_cursor,
)


@pytest.mark.parametrize("page", [0, 1, 5, 42, 1000])
def test_cursor_round_trip(page):
    assert _decode_flow_cursor(_encode_flow_cursor(page)) == page


def test_decode_empty_cursor_is_page_zero():
    assert _decode_flow_cursor(None) == 0
    assert _decode_flow_cursor("") == 0


def test_decode_invalid_cursor_raises():
    with pytest.raises(ValueError):
        _decode_flow_cursor("!!!not-base64!!!")


def test_decode_negative_page_clamps_to_zero():
    assert _decode_flow_cursor(_encode_flow_cursor(-1)) == 0
