"""Re-export shim: exposes TrafficRoute at the canonical module path.

The symmetry test imports ``unifi_api.graphql.types.network.traffic_routes``
(matching the pydantic model module name).  The Strawberry type lives in
``unifi_api.graphql.types.network.route`` alongside Route and ActiveRoute.
This shim keeps the dot-path consistent without duplicating any code.
"""

from unifi_api.graphql.types.network.route import TrafficRoute  # noqa: F401

__all__ = ["TrafficRoute"]
