"""Cross-layer symmetry: every mutable field on a pydantic domain model
in unifi_core.<server>.models.<domain> must exist on the matching
Strawberry type in unifi_api.graphql.types.<server>.<domain> with a
compatible annotation.

The registry below names every (server, domain) pair that participates
in the test. Phase 0 seeds it with one pair (network/acl). Phase 1
adds Protect pairs; Phase 2 adds Access pairs.
"""

from __future__ import annotations

import importlib

import pytest

from _cross_layer_helpers import compare_pair


REGISTERED_PAIRS: list[tuple[str, str, str]] = [
    # (server, domain, pydantic_class_name)
    ("network", "acl", "AclRule"),
]


@pytest.mark.parametrize("server,domain,pydantic_name", REGISTERED_PAIRS)
def test_cross_layer_symmetry(server: str, domain: str, pydantic_name: str) -> None:
    pydantic_mod = importlib.import_module(f"unifi_core.{server}.models.{domain}")
    strawberry_mod = importlib.import_module(f"unifi_api.graphql.types.{server}.{domain}")

    pydantic_cls = getattr(pydantic_mod, pydantic_name)
    strawberry_cls = getattr(strawberry_mod, pydantic_name)
    mutable_fields = getattr(pydantic_mod, "MUTABLE_FIELDS")

    errors = compare_pair(pydantic_cls, mutable_fields, strawberry_cls)
    assert not errors, (
        f"\nCross-layer drift in {server}/{domain}:\n  - "
        + "\n  - ".join(errors)
    )
