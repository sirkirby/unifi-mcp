"""CI gate: every Query field name follows the canonical map from manifest tool name."""

from unifi_api.graphql._naming import tool_to_field_path
from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_api.services.manifest import ManifestRegistry


def test_canonical_naming_examples() -> None:
    """The canonical naming rule produces the expected field paths for known tools."""
    assert tool_to_field_path("unifi_list_clients", product="network") == "query.network.clients"
    assert tool_to_field_path("unifi_list_cameras", product="protect") == "query.protect.cameras"
    assert tool_to_field_path("unifi_list_doors", product="access") == "query.access.doors"
    assert tool_to_field_path("unifi_get_client_details", product="network") == "query.network.client"
    # DETAIL without _details suffix and no LIST collision: stays as-is
    assert tool_to_field_path("unifi_get_door_status", product="access") == "query.access.doorStatus"
    # Out-of-scope tool: empty string
    assert tool_to_field_path("unifi_block_client", product="network") == ""


def test_naming_convention_no_collisions_in_manifest() -> None:
    """No two read tools should map to the same field path (would mask a duplicate).

    Phase 6 close: read-tool kinds come from the type_registry now that all
    read serializers have been migrated to Strawberry types.
    """
    manifest = ManifestRegistry.load_from_apps()
    type_registry = build_type_registry()

    # Build per-product LIST stem set first (collision-aware DETAIL mapping needs this).
    list_stems_by_product: dict[str, set[str]] = {"network": set(), "protect": set(), "access": set()}
    for name in manifest.all_tools():
        try:
            entry = manifest.resolve(name)
        except Exception:
            continue
        tool_type = type_registry.lookup_tool(name)
        if tool_type is None:
            continue
        _type_class, kind = tool_type
        if kind != "list" or not name.startswith("unifi_list_"):
            continue
        stem = name[len("unifi_list_") :]
        from unifi_api.graphql._naming import _to_camel

        list_stems_by_product[entry.product].add(_to_camel(stem))

    seen: dict[str, str] = {}
    for name in manifest.all_tools():
        try:
            entry = manifest.resolve(name)
        except Exception:
            continue
        tool_type = type_registry.lookup_tool(name)
        if tool_type is None:
            continue
        _type_class, kind = tool_type
        if kind not in ("list", "detail"):
            continue
        path = tool_to_field_path(
            name,
            product=entry.product,
            sibling_list_stems=list_stems_by_product.get(entry.product, set()),
        )
        if not path:
            continue
        if path in seen:
            raise AssertionError(f"naming collision: {name} and {seen[path]} both map to {path}")
        seen[path] = name
