"""Custom Strawberry → Pydantic walker for OpenAPI response_model."""

from __future__ import annotations

import pytest
from pydantic import BaseModel
from unifi_api.graphql.pydantic_export import to_pydantic_model


def test_simple_strawberry_type_to_pydantic() -> None:
    """A flat Strawberry type maps to a Pydantic model with the same fields."""
    from unifi_api.graphql.types.network.client import Client

    Model = to_pydantic_model(Client)
    assert issubclass(Model, BaseModel)
    fields = set(Model.model_fields.keys())
    assert "mac" in fields
    assert "hostname" in fields
    assert "is_wired" in fields


def test_strawberry_id_becomes_str() -> None:
    """strawberry.ID fields project as Optional[str] in Pydantic."""
    from unifi_api.graphql.types.network.client import Client

    Model = to_pydantic_model(Client)
    field = Model.model_fields["mac"]
    annotation = field.annotation
    assert "str" in str(annotation)


def test_pydantic_model_validates_to_dict_output() -> None:
    """The Pydantic model accepts the dict shape that Type.to_dict() produces."""
    from unifi_api.graphql.types.network.client import Client

    Model = to_pydantic_model(Client)
    sample_raw = {
        "mac": "aa:bb:cc:dd:ee:01",
        "hostname": "alpha",
        "is_wired": True,
        "is_guest": False,
        "is_online": True,
        "last_seen": 1700000000,
        "first_seen": 1690000000,
        "ip": "10.0.0.5",
    }
    inst = Client.from_manager_output(sample_raw)
    out = inst.to_dict()
    Model(**out)


def test_pydantic_model_rejects_unknown_fields_loosely() -> None:
    """Pydantic models built from Strawberry types accept extras (Strawberry semantics).

    REST routes return dicts that may include manager-extra keys; Pydantic must
    not reject them, matching Strawberry's permissive shape.
    """
    from unifi_api.graphql.types.network.client import Client

    Model = to_pydantic_model(Client)
    sample = {
        "mac": "aa:01",
        "hostname": "x",
        "is_wired": True,
        "is_guest": False,
        "ip": None,
        "status": "online",
        "last_seen": "2025-01-01T00:00:00",
        "first_seen": None,
        "note": None,
        "usergroup_id": None,
        "extra_field_we_dont_care_about": "extra",
    }
    Model(**sample)  # must not raise


def test_to_pydantic_model_caches_by_type() -> None:
    """Repeated calls return the same Pydantic class (identity-stable for response_model=)."""
    from unifi_api.graphql.types.network.client import Client

    assert to_pydantic_model(Client) is to_pydantic_model(Client)


def test_to_pydantic_model_raises_on_non_strawberry_type() -> None:
    """Non-Strawberry inputs raise TypeError so callers don't get a silently-broken model."""

    class NotStrawberry:
        pass

    with pytest.raises(TypeError, match="not a Strawberry type"):
        to_pydantic_model(NotStrawberry)
