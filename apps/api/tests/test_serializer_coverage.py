"""CI gate: every manifest tool must have a registered projection — either
a serializer (mutation tool) or a Strawberry type (read tool, since Phase 6
close).

Adding a new MCP tool without registering a serializer (mutation) or a type
(read) will fail this test — the SerializerRegistryError lists the missing
tool names in its message, so the fix is to add the appropriate projection.

The same invariant is enforced at lifespan startup in server.py
(`discover_serializers(set(manifest.all_tools()), type_registry=...)`); this
test catches the regression in CI before the app fails to start.
"""

from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_api.serializers._registry import (
    _reset_registry_for_tests,
    discover_serializers,
)
from unifi_api.services.manifest import ManifestRegistry


def test_every_tool_has_a_serializer() -> None:
    _reset_registry_for_tests()
    manifest = ManifestRegistry.load()
    type_registry = build_type_registry()
    # Will raise SerializerRegistryError if any tool lacks both a serializer
    # and a type.
    discover_serializers(set(manifest.all_tools()), type_registry=type_registry)


def test_nine_cloud_tools_are_covered_only_by_read_types():
    import pytest
    from unifi_api.serializers._registry import SerializerRegistryError

    from tests.sitemanager_data import CASES

    names = {case[0] for case in CASES}
    assert len(names) == 9
    registry = build_type_registry()
    assert names <= set(registry.all_tools())
    _reset_registry_for_tests()
    serializers = discover_serializers(set(ManifestRegistry.load().all_tools()), type_registry=registry)
    assert names.isdisjoint(set(serializers.all_tools()))
    for missing in names:
        _reset_registry_for_tests()
        incomplete = build_type_registry()
        incomplete._tool_types.pop(missing)
        with pytest.raises(SerializerRegistryError, match=missing):
            discover_serializers(set(ManifestRegistry.load().all_tools()), type_registry=incomplete)
    _reset_registry_for_tests()


def test_innerspace_writes_have_serializers_and_reads_have_types():
    _reset_registry_for_tests()
    manifest = ManifestRegistry.load()
    type_registry = build_type_registry()
    serializers = discover_serializers(set(manifest.all_tools()), type_registry=type_registry)
    innerspace = {name for name in manifest.all_tools() if name.startswith("innerspace_")}
    writes = {name for name in innerspace if manifest.resolve(name).permission_action != "read"}

    assert len(writes) == 15
    assert writes <= set(serializers.all_tools())
    assert (innerspace - writes) <= set(type_registry.all_tools())
    assert (innerspace - writes).isdisjoint(set(serializers.all_tools()))
    _reset_registry_for_tests()
