"""Auto-generate apps/api/docs/graphql-reference.md and openapi-reference.md.

Run: `uv run --package unifi-api-server python -m unifi_api.graphql.docgen`
to regenerate. CI gates catch staleness.
"""

from __future__ import annotations

import json
from pathlib import Path

from unifi_api.graphql.schema import schema


def render_reference() -> str:
    """Render apps/api/docs/graphql-reference.md grouped by top-level Query field.

    Walks the schema's introspection metadata and emits markdown sections
    per Query namespace (network / protect / access) plus type definitions.
    """
    sdl = str(schema).strip()
    out: list[str] = []
    out.append("# unifi-api-server GraphQL Reference\n")
    out.append("> Auto-generated from the Strawberry schema by `unifi_api.graphql.docgen`.")
    out.append("> Regenerate with `python -m unifi_api.graphql.docgen`.\n")
    out.append("\n## Schema (full SDL)\n")
    out.append("\n```graphql\n")
    out.append(sdl)
    out.append("\n```\n")

    gql_schema = schema._schema
    query_type = gql_schema.query_type
    if query_type is not None:
        out.append("\n## Query namespaces\n")
        for field_name, field in sorted(query_type.fields.items()):
            description = field.description or ""
            out.append(f"\n### `query.{field_name}`\n")
            if description:
                out.append(f"\n{description}\n")
            target = field.type
            while hasattr(target, "of_type"):
                target = target.of_type
            if hasattr(target, "fields"):
                out.append("\n**Fields:**\n")
                for sub_name, sub_field in sorted(target.fields.items()):
                    sub_desc = sub_field.description or ""
                    sub_type_str = str(sub_field.type)
                    line = f"- `{sub_name}: {sub_type_str}`"
                    if sub_desc:
                        line += f"  — {sub_desc}"
                    out.append(line)
                out.append("")

    return "\n".join(out)


def render_openapi_reference() -> str:
    """Render apps/api/docs/openapi-reference.md from openapi.json."""
    spec_path = Path(__file__).resolve().parents[3] / "openapi.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    out: list[str] = []
    out.append("# unifi-api-server REST Reference\n")
    out.append("> Auto-generated from `openapi.json` by `unifi_api.graphql.docgen`.")
    out.append("> Regenerate with `python -m unifi_api.graphql.docgen`.\n")

    # Group endpoints by tag
    by_tag: dict[str, list[tuple[str, str, dict]]] = {}
    for path, ops in sorted(spec.get("paths", {}).items()):
        for method, op in ops.items():
            if not isinstance(op, dict):
                continue
            for tag in op.get("tags", ["untagged"]):
                by_tag.setdefault(tag, []).append((method.upper(), path, op))

    for tag in sorted(by_tag):
        out.append(f"\n## {tag}\n")
        for method, path, op in by_tag[tag]:
            summary = op.get("summary") or op.get("operationId") or ""
            out.append(f"### `{method} {path}` — {summary}\n")
            if op.get("description"):
                out.append(f"\n{op['description']}\n")
            params = op.get("parameters") or []
            if params:
                out.append("\n**Parameters:**\n")
                for p in params:
                    name = p.get("name", "")
                    where = p.get("in", "")
                    required = " (required)" if p.get("required") else ""
                    out.append(f"- `{name}` ({where}){required}")
                out.append("")
            response_200 = op.get("responses", {}).get("200", {})
            response_schema = response_200.get("content", {}).get("application/json", {}).get("schema")
            if response_schema:
                schema_name = response_schema.get("$ref", "").split("/")[-1] or response_schema.get("type", "object")
                out.append(f"\n**Returns:** `{schema_name}`\n")

    return "\n".join(out)


def main() -> None:
    docs_dir = Path(__file__).resolve().parents[3] / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "graphql-reference.md").write_text(render_reference(), encoding="utf-8")
    (docs_dir / "openapi-reference.md").write_text(render_openapi_reference(), encoding="utf-8")
    print(f"wrote {docs_dir / 'graphql-reference.md'}")
    print(f"wrote {docs_dir / 'openapi-reference.md'}")


if __name__ == "__main__":
    main()
