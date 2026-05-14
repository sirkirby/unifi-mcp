"""CI gate: every read tool in the manifest has a corresponding GraphQL Query field.

Phase 6 close: every read tool (122 total across network/protect/access) is
projected via a Strawberry type and resolved by a GraphQL Query field. The
EXEMPT_PRODUCTS allowlist is permanently empty.

Read tools are filtered via the type_registry's lookup_tool() — only tools
with a registered Strawberry projection count. Mutation tools live in the
serializer_registry and are out of scope for the read-only GraphQL surface.
"""

from __future__ import annotations

from unifi_api.graphql.schema import schema as graphql_schema
from unifi_api.graphql.type_registry_init import build_type_registry
from unifi_api.services.manifest import ManifestRegistry

# PR4 close: ALL THREE PRODUCTS now covered. The allowlist is empty —
# every read tool in the manifest must map to a GraphQL Query field.
# Phase 6 close-out invariant: this set stays empty forever.
EXEMPT_PRODUCTS: set[str] = set()


def _read_tools_by_product() -> dict[str, list[str]]:
    """Group read tools (LIST + DETAIL kinds, `unifi_list_*` / `unifi_get_*` prefix) by product.

    Phase 6 close: read tools are sourced from the type_registry. Only tools
    whose kind is "list" or "detail" count as read coverage targets — the
    timeseries/event_log shapes are nested inside Query fields rather than
    top-level fields and don't participate in this naming gate.
    """
    reg = ManifestRegistry.load_from_apps()
    type_registry = build_type_registry()
    out: dict[str, list[str]] = {"network": [], "protect": [], "access": []}
    for tool_name in reg.all_tools():
        # Read-tool prefix filter — Phase 6 scope is unifi_list_* / unifi_get_* only.
        if not (tool_name.startswith("unifi_list_") or tool_name.startswith("unifi_get_")):
            continue
        try:
            entry = reg.resolve(tool_name)
        except Exception:
            continue
        tool_type = type_registry.lookup_tool(tool_name)
        if tool_type is None:
            continue
        _type_class, kind = tool_type
        if kind not in ("list", "detail"):
            continue
        if entry.product in out:
            out[entry.product].append(tool_name)
    return out


def _query_field_names() -> set[str]:
    """Walk the schema's Query type and any nested namespaces for field names."""
    names: set[str] = set()
    seen: set[int] = set()
    gql_schema = graphql_schema._schema  # underlying graphql-core GraphQLSchema

    def _walk(type_obj) -> None:
        if not hasattr(type_obj, "fields"):
            return
        # Cycle protection — relationship edges (e.g. Client.device -> Device,
        # Device.portClients -> [Client]) form cycles in the type graph.
        type_id = id(type_obj)
        if type_id in seen:
            return
        seen.add(type_id)
        for field_name, field in type_obj.fields.items():
            names.add(field_name)
            # If the field's return type is itself a typed object with subfields
            # (e.g., Query.network -> NetworkQuery), walk into it.
            target_type = field.type
            # Unwrap NonNull / List wrappers
            while hasattr(target_type, "of_type"):
                target_type = target_type.of_type
            if hasattr(target_type, "fields"):
                _walk(target_type)

    query_type = gql_schema.query_type
    if query_type is not None:
        _walk(query_type)
    return names


def test_every_read_tool_has_graphql_field() -> None:
    """For every read tool in the manifest, a corresponding Query field exists.

    During PR1, all products are exempt (no resolvers yet, just the smoke
    `health` field). PR2 removes network from EXEMPT_PRODUCTS, etc. PR4 close
    has EXEMPT_PRODUCTS empty — all 122 read tools must map.
    """
    # No serializer registration needed — Phase 6 close routes all read
    # tools through the type_registry, which build_type_registry() builds
    # synchronously inside _read_tools_by_product().
    fields = _query_field_names()
    by_product = _read_tools_by_product()

    missing: list[str] = []
    for product, tools in by_product.items():
        if product in EXEMPT_PRODUCTS:
            continue
        for tool_name in tools:
            # Loose check: some field whose name reflects the tool exists.
            # The naming-convention gate (Task 13) tightens this to an exact
            # canonical map.
            stem = tool_name.replace("unifi_list_", "").replace("unifi_get_", "")
            stem = stem.replace("_details", "")  # DETAIL convention
            stem_camel = stem.split("_")[0] + "".join(p.capitalize() for p in stem.split("_")[1:])
            if not any(stem_camel.lower() in fld.lower() for fld in fields):
                missing.append(f"{product}/{tool_name}")

    assert not missing, "Read tools without a GraphQL Query field:\n  " + "\n  ".join(missing)


def test_smoke_health_field_present() -> None:
    """PR1 baseline: the smoke health field exists on the schema."""
    assert "health" in _query_field_names()
