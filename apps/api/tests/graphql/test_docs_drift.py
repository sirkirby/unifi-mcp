"""CI gate: apps/api/docs/graphql-reference.md matches the docgen render.

Re-generate with:
    uv run --package unifi-api-server python -m unifi_api.graphql.docgen
"""

from pathlib import Path

from unifi_api.graphql.docgen import render_reference

REF_PATH = Path(__file__).resolve().parents[2] / "docs" / "graphql-reference.md"


def test_reference_md_matches_render() -> None:
    expected = render_reference().strip()
    actual = REF_PATH.read_text(encoding="utf-8").strip()
    assert actual == expected, (
        "graphql-reference.md is stale. Re-generate with:\n"
        "  uv run --package unifi-api-server python -m unifi_api.graphql.docgen\n"
    )
