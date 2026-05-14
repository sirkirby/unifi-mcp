"""Serializer registry tests."""

import pytest
from unifi_api.serializers._base import RenderKind, Serializer, register_serializer
from unifi_api.serializers._registry import (
    SerializerRegistryError,
    _reset_registry_for_tests,
    serializer_registry_singleton,
)


@pytest.fixture(autouse=True)
def _reset():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


def test_lookup_by_tool_name() -> None:
    @register_serializer(tools=["t1"])
    class T1(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return obj

    reg = serializer_registry_singleton()
    found = reg.serializer_for_tool("t1")
    assert isinstance(found, T1)


def test_lookup_by_resource() -> None:
    @register_serializer(resources=[("network", "clients")])
    class C(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return obj

    reg = serializer_registry_singleton()
    found = reg.serializer_for_resource("network", "clients")
    assert isinstance(found, C)


def test_kind_for_tool_with_per_tool_override() -> None:
    @register_serializer(tools={"a": {"kind": RenderKind.LIST}, "b": {"kind": RenderKind.DETAIL}})
    class S(Serializer):
        @staticmethod
        def serialize(obj):
            return obj

    reg = serializer_registry_singleton()
    assert reg.kind_for_tool("a") == RenderKind.LIST
    assert reg.kind_for_tool("b") == RenderKind.DETAIL


def test_validate_against_manifest_fails_on_missing() -> None:
    @register_serializer(tools=["only_one"])
    class S(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return obj

    reg = serializer_registry_singleton()
    # Manifest has tools the registry doesn't know about
    with pytest.raises(SerializerRegistryError, match="missing projection"):
        reg.validate_manifest({"only_one", "other_tool", "another_tool"})


def test_validate_against_manifest_passes_when_all_present() -> None:
    @register_serializer(tools=["a", "b"])
    class S(Serializer):
        kind = RenderKind.LIST

        @staticmethod
        def serialize(obj):
            return obj

    reg = serializer_registry_singleton()
    reg.validate_manifest({"a", "b"})  # no exception
