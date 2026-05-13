"""Re-export shim for cross-layer symmetry test compatibility.

The Strawberry ``Network`` type lives in ``network.py`` (the file predates
Phase 4). The pydantic domain model is ``networks.py`` to avoid a name
clash with the Python module ``network``. The symmetry test resolves both
sides by domain name, so this shim makes the Strawberry side importable as
``unifi_api.graphql.types.network.networks``.
"""

from unifi_api.graphql.types.network.network import Network  # noqa: F401
