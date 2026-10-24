"""The traffic-flows action builds the same Core query as the MCP tool."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from unifi_api.services.dispatch_overrides import DISPATCH_ARG_TRANSLATORS

TRANSLATOR = DISPATCH_ARG_TRANSLATORS["unifi_get_traffic_flows"]


def test_port_filters_become_integer_lists() -> None:
    positional, keyword = TRANSLATOR({"destination_port": 7680, "source_port": 0, "action": "blocked"})
    query = keyword["query"]
    assert positional == ()
    assert query.destination_port == [7680]
    assert query.source_port == [0]
    assert query.action == ["blocked"]


def test_port_filters_accept_lists_and_default_to_none() -> None:
    query = TRANSLATOR({"destination_port": [443, 7680]})[1]["query"]
    assert query.destination_port == [443, 7680]
    assert query.source_port is None


def test_out_of_range_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TRANSLATOR({"destination_port": 65536})
