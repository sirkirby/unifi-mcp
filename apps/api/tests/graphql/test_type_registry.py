"""TypeRegistry — Phase 6 close: types-only projection registry."""

import pytest
from unifi_api.graphql.type_registry import (
    TypeRegistry,
    UnknownProjection,
)


def test_registry_returns_type_class_when_type_registered() -> None:
    reg = TypeRegistry()
    reg.register_type("network", "clients", str)  # pretend `str` is a type class
    assert reg.lookup("network", "clients") is str


def test_registry_raises_unknown_for_missing_resource() -> None:
    reg = TypeRegistry()
    with pytest.raises(UnknownProjection):
        reg.lookup("network", "ghosts")


def test_registry_enumerates_all_resources() -> None:
    reg = TypeRegistry()
    reg.register_type("network", "clients", str)
    reg.register_type("protect", "cameras", int)
    items = sorted(reg.all_resources())
    assert items == [("network", "clients"), ("protect", "cameras")]


def test_registry_tool_lookup_returns_type_kind_tuple() -> None:
    reg = TypeRegistry()
    reg.register_tool_type("unifi_list_clients", str, "list")
    result = reg.lookup_tool("unifi_list_clients")
    assert result == (str, "list")


def test_registry_tool_lookup_returns_none_for_unknown() -> None:
    reg = TypeRegistry()
    assert reg.lookup_tool("nope") is None
