"""CI gate: every console resource route and GraphQL reads under the operation gate.

Modelled on test_resource_route_coverage.py. A console resource route
(``GET /v1/sites/...``) or the GraphQL endpoint that reaches a controller
without ``hold_controller_read_slots`` would read while another client writes,
and outside the per-controller read cap. The dependency is attached where the
routers are included, so a new resource router added to those loops is covered
automatically; one included anywhere else fails here.

Routes that must not hold a read slot are named in ``NOT_READ_SLOT_ROUTES``
with the reason.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from unifi_api.config import ApiConfig, DbConfig, HttpConfig, LoggingConfig
from unifi_api.server import create_app
from unifi_api.services.operation_gate import hold_controller_read_slots

# Prefixes that reach controllers but must not hold a read slot for the request.
NOT_READ_SLOT_ROUTES = {
    # explanation: the action endpoint enters the gate itself, as a write for a
    # confirmed mutation and a read otherwise.
    "/v1/actions/",
    # explanation: event streams stay open for as long as the client listens;
    # they read the websocket buffer, not the controller, and must not pin a slot.
    "/v1/streams/",
}


def _walk(raw_routes: Iterable[Any], prefix: str = "", inherited: tuple = ()) -> list[tuple[str, set, tuple]]:
    found: list[tuple[str, set, tuple]] = []
    for route in raw_routes:
        include_context = getattr(route, "include_context", None)
        included_router = getattr(include_context, "included_router", None)
        if included_router is not None:
            found.extend(
                _walk(
                    included_router.routes,
                    f"{prefix}{include_context.prefix}",
                    inherited + tuple(dependency.dependency for dependency in include_context.dependencies),
                )
            )
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        own = tuple(dependency.dependency for dependency in getattr(route, "dependencies", []) or [])
        dependant = getattr(route, "dependant", None)
        nested = tuple(dependency.call for dependency in getattr(dependant, "dependencies", []) or [])
        found.append((f"{prefix}{path}", set(getattr(route, "methods", None) or ()), inherited + own + nested))
    return found


def _routes(tmp_path) -> list[tuple[str, set, tuple]]:
    os.environ["UNIFI_API_DB_KEY"] = "ci-gate-test"
    app = create_app(
        ApiConfig(
            http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
            logging=LoggingConfig(level="WARNING"),
            db=DbConfig(path=str(tmp_path / "state.db")),
        )
    )
    return _walk(app.routes)


def test_every_console_resource_and_graphql_route_takes_a_read_slot(tmp_path) -> None:
    routes = _routes(tmp_path)
    reads = [
        (path, dependencies)
        for path, methods, dependencies in routes
        if (path.startswith("/v1/sites/") and "GET" in methods) or path.startswith("/v1/graphql")
    ]
    assert len(reads) > 100, "the walk found too few read routes; did the router layout change?"
    missing = sorted(path for path, dependencies in reads if hold_controller_read_slots not in dependencies)
    assert missing == [], f"read routes without hold_controller_read_slots: {missing}"


def test_actions_and_streams_do_not_hold_a_read_slot(tmp_path) -> None:
    routes = _routes(tmp_path)
    holding = sorted(
        path
        for path, _methods, dependencies in routes
        if path.startswith(tuple(NOT_READ_SLOT_ROUTES)) and hold_controller_read_slots in dependencies
    )
    assert holding == []
    assert any(path.startswith("/v1/streams/") for path, _m, _d in routes)
