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
