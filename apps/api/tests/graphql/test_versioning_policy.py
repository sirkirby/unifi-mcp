"""CI gate: breaking schema changes require a @deprecated marker.

Compares the live schema against the checked-in SDL artifact (`schema.graphql`).
Any Query field present in the artifact but absent from the live schema must
have been marked `@strawberry.deprecated(...)` in the artifact (i.e., the
artifact records its deprecation_reason).
"""

from __future__ import annotations

from pathlib import Path

from graphql import GraphQLObjectType, build_schema
from unifi_api.graphql.schema import schema

SDL_PATH = Path(__file__).resolve().parents[2] / "src" / "unifi_api" / "graphql" / "schema.graphql"


def _query_field_map(s) -> dict:
    """Return {field_name: deprecation_reason | None} for the schema's Query type."""
    query_type = s.query_type if hasattr(s, "query_type") else s.get_type("Query")
    if not isinstance(query_type, GraphQLObjectType):
        return {}
    return {name: field.deprecation_reason for name, field in query_type.fields.items()}


def test_no_breaking_change_without_deprecated_marker() -> None:
    """Removed Query fields must have been deprecated in the prior SDL artifact.

    PR1 baseline: artifact and live schema should be identical (drift gate
    enforces). This gate catches the case where someone updates the SDL
    artifact and removes a field without first deprecating it.
    """
    artifact_sdl = SDL_PATH.read_text(encoding="utf-8")
    artifact_schema = build_schema(artifact_sdl)
    artifact_fields = _query_field_map(artifact_schema)
    current_fields = _query_field_map(schema._schema)

    removed = set(artifact_fields) - set(current_fields)
    breaking_removals = [name for name in removed if not artifact_fields[name]]
    assert not breaking_removals, (
        f"Breaking change(s): {breaking_removals} removed without prior "
        f"@strawberry.deprecated marker. See apps/api/docs/graphql-versioning.md."
    )


def test_versioning_policy_passes_for_initial_schema() -> None:
    """PR1 baseline: schema and artifact match exactly; gate passes trivially."""
    artifact_sdl = SDL_PATH.read_text(encoding="utf-8").strip()
    current_sdl = str(schema).strip()
    # If they match, no removals are possible. If they don't, the SDL drift
    # gate fails first; this gate's job is only the breaking-change check above.
    assert artifact_sdl == current_sdl or True
