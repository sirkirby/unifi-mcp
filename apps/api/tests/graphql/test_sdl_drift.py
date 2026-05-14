"""CI gate: checked-in schema.graphql matches the live `str(schema)` output.

If a maintainer changes Python decorators in a way that mutates the SDL but
doesn't re-export, this gate fails — preventing silent contract drift.

Re-export with:
    uv run --package unifi-api-server python -c \\
      "from unifi_api.graphql.schema import schema; print(str(schema))" \\
      > apps/api/src/unifi_api/graphql/schema.graphql
"""

from pathlib import Path

from unifi_api.graphql.schema import schema

SDL_PATH = Path(__file__).resolve().parents[2] / "src" / "unifi_api" / "graphql" / "schema.graphql"


def test_sdl_artifact_matches_schema() -> None:
    """The checked-in SDL artifact matches what Strawberry exports right now."""
    expected = str(schema).strip()
    actual = SDL_PATH.read_text(encoding="utf-8").strip()
    assert actual == expected, (
        "schema.graphql is stale. Re-export with:\n"
        "  uv run --package unifi-api-server python -c \\\n"
        '    "from unifi_api.graphql.schema import schema; print(str(schema))" \\\n'
        f"    > {SDL_PATH.relative_to(Path.cwd()) if str(SDL_PATH).startswith(str(Path.cwd())) else SDL_PATH}\n"
    )
