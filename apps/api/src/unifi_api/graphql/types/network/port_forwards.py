"""Re-export shim for cross-layer symmetry test compatibility.

The Strawberry ``PortForward`` type lives in ``port_forward.py`` (singular).
The pydantic domain model is ``port_forwards.py`` (plural). This shim makes
the Strawberry side importable as
``unifi_api.graphql.types.network.port_forwards``.
"""

from unifi_api.graphql.types.network.port_forward import PortForward  # noqa: F401
