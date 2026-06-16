"""Helpers for the resource-route surface — used by /v1/catalog/resources
and the test_resource_route_coverage CI gate (Task 22)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from fastapi import FastAPI


@dataclass
class ResourceRoute:
    method: str
    path: str
    name: str  # function name


def collect_resource_routes(app: FastAPI) -> list[ResourceRoute]:
    """Walk the FastAPI app and return all GET routes under /v1/sites/."""
    return _collect_routes(app.routes)


def _collect_routes(raw_routes: Iterable[Any], prefix: str = "") -> list[ResourceRoute]:
    routes: list[ResourceRoute] = []
    for route in raw_routes:
        include_context = getattr(route, "include_context", None)
        included_router = getattr(include_context, "included_router", None)
        if included_router is not None:
            # FastAPI 0.137 keeps included routers nested instead of flattening
            # them into app.routes, so preserve the include prefix while walking.
            include_prefix = getattr(include_context, "prefix", "")
            routes.extend(_collect_routes(included_router.routes, f"{prefix}{include_prefix}"))
            continue

        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or "GET" not in methods or path is None:
            continue
        full_path = f"{prefix}{path}"
        if not full_path.startswith("/v1/sites/"):
            continue
        routes.append(ResourceRoute(method="GET", path=full_path, name=route.name))
    return routes


def is_read_tool(name: str) -> bool:
    """True if the tool name follows the read-tool convention (list_/get_/recent_)."""
    parts = name.split("_", 1)
    if len(parts) != 2:
        return False
    rest = parts[1]
    return rest.startswith(("list_", "get_", "recent_"))


def read_tools_in_manifest(all_tools: Iterable[str]) -> set[str]:
    return {t for t in all_tools if is_read_tool(t)}
