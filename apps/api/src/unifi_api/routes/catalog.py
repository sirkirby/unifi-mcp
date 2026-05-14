"""Catalog endpoints — discoverability for tools, categories, render hints."""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Request

from unifi_api.auth.middleware import require_scope
from unifi_api.auth.scopes import Scope

router = APIRouter()


@router.get("/catalog/tools", dependencies=[Depends(require_scope(Scope.READ))])
async def get_tools(request: Request) -> dict:
    manifest = request.app.state.manifest_registry
    serializer_registry = request.app.state.serializer_registry
    items = []
    for tool_name in manifest.all_tools():
        entry = manifest.resolve(tool_name)
        try:
            render_hint = serializer_registry.render_hint_for_tool(tool_name)
        except Exception:
            render_hint = {"kind": "empty"}
        items.append(
            {
                "name": tool_name,
                "product": entry.product,
                "category": entry.category,
                "manager": entry.manager,
                "method": entry.method,
                "render_hint": render_hint,
            }
        )
    return {"items": items}


@router.get("/catalog/categories", dependencies=[Depends(require_scope(Scope.READ))])
async def get_categories(request: Request) -> dict:
    manifest = request.app.state.manifest_registry
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for tool_name in manifest.all_tools():
        entry = manifest.resolve(tool_name)
        counts[(entry.product, entry.category or "")] += 1
    items = [{"product": p, "category": c, "tool_count": n} for (p, c), n in sorted(counts.items())]
    return {"items": items}


@router.get("/catalog/render-hints", dependencies=[Depends(require_scope(Scope.READ))])
async def get_render_hints(request: Request) -> dict:
    manifest = request.app.state.manifest_registry
    serializer_registry = request.app.state.serializer_registry
    type_registry = request.app.state.type_registry
    by_kind: dict[str, dict] = {}
    for tool_name in manifest.all_tools():
        kind: str | None = None
        try:
            kind = serializer_registry.kind_for_tool(tool_name).value
        except Exception:
            # Phase 6 — read tools whose projection lives in the type_registry
            # have no serializer; fall back to the type_registry's tool lookup.
            tool_type = type_registry.lookup_tool(tool_name)
            if tool_type is not None:
                _type_class, kind = tool_type
        if kind is None:
            continue
        by_kind.setdefault(kind, {"kind": kind, "tools": [], "resources": []})
        by_kind[kind]["tools"].append(tool_name)
    for product, resource in serializer_registry.all_resources():
        try:
            kind = serializer_registry.kind_for_resource(product, resource).value
        except Exception:
            continue
        by_kind.setdefault(kind, {"kind": kind, "tools": [], "resources": []})
        by_kind[kind]["resources"].append({"product": product, "path": resource})
    return {"items": list(by_kind.values())}


@router.get("/catalog/resources", dependencies=[Depends(require_scope(Scope.READ))])
async def get_resources(request: Request) -> dict:
    """Discoverability endpoint: every registered resource path with render_hint.

    Lists every (product, resource_path) pair from the serializer registry.
    For paths with placeholders (e.g., 'clients/{mac}'), renders as a path
    template under /v1/sites/{site_id}/.
    """
    serializer_registry = request.app.state.serializer_registry
    type_registry = request.app.state.type_registry
    items = []
    seen: set[tuple[str, str]] = set()

    def _render_hint(product: str, resource: str) -> dict:
        try:
            type_class = type_registry.lookup(product, resource)
        except Exception:
            type_class = None
        if type_class is not None:
            # Phase 6 close — typed projections expose render_hint(kind). The
            # kind matches the original serializer's kind; use the serializer
            # registry as the kind oracle when available, falling back to a
            # heuristic on the resource shape.
            try:
                kind = serializer_registry.kind_for_resource(product, resource).value
            except Exception:
                kind = "detail" if "{" in resource else "list"
            try:
                return type_class.render_hint(kind)
            except Exception:
                return {"kind": kind}
        try:
            return serializer_registry.render_hint_for_resource(product, resource)
        except Exception:
            return {"kind": "empty"}

    def _path_for(resource: str) -> str:
        if "{" in resource:
            base, tmpl = resource.split("/", 1)
            return f"/v1/sites/{{site_id}}/{base}/{tmpl}"
        return f"/v1/sites/{{site_id}}/{resource}"

    for product, resource in serializer_registry.all_resources():
        seen.add((product, resource))
        items.append(
            {
                "product": product,
                "resource_path": _path_for(resource),
                "render_hint": _render_hint(product, resource),
            }
        )
    # Phase 6 PR2 — include type-only resources (read serializer classes have
    # been deleted for migrated products; their projection lives in type_registry).
    for product, resource in type_registry.all_resources():
        if (product, resource) in seen:
            continue
        # Skip synthetic resource keys that don't map to a REST path
        # (e.g., ("network", "client_lookup") which is exposed at /lookup-by-ip).
        if resource.endswith("_lookup") or resource == "blocked_clients":
            # blocked_clients/lookup are already exposed at REST under
            # /blocked-clients and /lookup-by-ip, but their type_registry key
            # is the logical resource id. Surface them with the actual REST path.
            if resource == "blocked_clients":
                rest_path = "/v1/sites/{site_id}/blocked-clients"
            elif resource == "client_lookup":
                rest_path = "/v1/sites/{site_id}/lookup-by-ip"
            else:
                rest_path = _path_for(resource)
            items.append(
                {
                    "product": product,
                    "resource_path": rest_path,
                    "render_hint": _render_hint(product, resource),
                }
            )
            continue
        items.append(
            {
                "product": product,
                "resource_path": _path_for(resource),
                "render_hint": _render_hint(product, resource),
            }
        )
    return {"items": items}
