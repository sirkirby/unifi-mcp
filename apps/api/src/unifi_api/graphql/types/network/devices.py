"""Re-export shim: exposes Device and DeviceRadio at the canonical module path.

The symmetry test imports ``unifi_api.graphql.types.network.devices``
(matching the pydantic model module name).  The Strawberry types live in
``unifi_api.graphql.types.network.device`` (singular).
This shim keeps the dot-path consistent without duplicating any code.
"""

from unifi_api.graphql.types.network.device import Device, DeviceRadio  # noqa: F401

__all__ = ["Device", "DeviceRadio"]
