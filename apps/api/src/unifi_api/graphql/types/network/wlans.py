"""Re-export shim: exposes Wlan at the canonical module path.

The symmetry test imports ``unifi_api.graphql.types.network.wlans``
(matching the pydantic model module name).  The Strawberry type lives in
``unifi_api.graphql.types.network.wlan`` (singular).
This shim keeps the dot-path consistent without duplicating any code.
"""

from unifi_api.graphql.types.network.wlan import Wlan  # noqa: F401

__all__ = ["Wlan"]
