"""Traffic-flow query handling shared by the REST route and the GraphQL resolver.

Both surfaces report a bad filter by name only, never by value or controller text.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from unifi_core.exceptions import http_status
from unifi_core.network.models.traffic_flows import TrafficFlowQuery

REJECTED = "the controller rejected the traffic-flow query"


class InvalidTrafficFlowFilter(ValueError):
    """A filter that failed validation before anything was sent."""


class TrafficFlowQueryRejected(ValueError):
    """The controller refused the query, which it does for a filter value it does not accept."""

    def __init__(self) -> None:
        super().__init__(REJECTED)


def build_query(**fields: Any) -> TrafficFlowQuery:
    try:
        return TrafficFlowQuery(**fields)
    except ValidationError as exc:
        names = sorted({str(error["loc"][0]) for error in exc.errors() if error["loc"]})
        raise InvalidTrafficFlowFilter(f"invalid traffic-flow filter: {', '.join(names)}") from None


def is_rejection(exc: BaseException) -> bool:
    """True for the controller's HTTP 400 answer, which it gives for a filter value it does not accept."""
    return http_status(exc) == 400
