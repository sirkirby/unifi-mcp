"""Canonical map: manifest tool name <-> Query field path.

Examples:
    unifi_list_clients         -> query.network.clients     (LIST, plural)
    unifi_get_client_details   -> query.network.client      (DETAIL, _details dropped)
    unifi_list_cameras         -> query.protect.cameras
    unifi_get_camera_status    -> query.protect.cameraStatus  (DETAIL, no _details, no LIST collision)

Rule:
    - unifi_list_<stem>      -> camelCase(<stem>)
    - unifi_get_<stem>       -> camelCase(<stem with _details suffix dropped>)
    - If a DETAIL tool's stripped stem collides with a LIST stem,
      append "Detail" suffix to disambiguate.

The collision-handling logic is encoded here, not at the call site.
"""

from __future__ import annotations


def _to_camel(snake: str) -> str:
    parts = [p for p in snake.split("_") if p]
    if not parts:
        return ""
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def tool_to_field_path(tool_name: str, *, product: str, sibling_list_stems: set[str] | None = None) -> str:
    """Compute the canonical query.<product>.<field> path for a tool name.

    Args:
        tool_name: a manifest tool name like "unifi_list_clients".
        product: "network" / "protect" / "access".
        sibling_list_stems: optional set of LIST stems already mapped for the
            same product. Used to detect DETAIL collisions and append "Detail"
            suffix to disambiguate. Pass `None` (default) when not doing
            collision-aware mapping.

    Returns the field path, or an empty string for tools out of scope
    (e.g., write/action tools that don't map to GraphQL Query fields).
    """
    if tool_name.startswith("unifi_list_"):
        stem = tool_name[len("unifi_list_") :]
        return f"query.{product}.{_to_camel(stem)}"

    if tool_name.startswith("unifi_get_"):
        stem = tool_name[len("unifi_get_") :]
        if stem.endswith("_details"):
            stem = stem[: -len("_details")]
            return f"query.{product}.{_to_camel(stem)}"
        # DETAIL without _details suffix
        camel = _to_camel(stem)
        if sibling_list_stems is not None and camel in sibling_list_stems:
            # Collides with a LIST stem; append Detail
            return f"query.{product}.{camel}Detail"
        return f"query.{product}.{camel}"

    # Action / mutation tools — out of scope for read coverage.
    return ""
