"""Structural guards for request-scoped Network site selection."""

from __future__ import annotations

import ast
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1] / "src" / "unifi_api"
NETWORK_SURFACES = [
    *sorted((API_ROOT / "routes" / "resources" / "network").glob("*.py")),
    API_ROOT / "graphql" / "resolvers" / "network.py",
]


def _manager_factory_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(), filename=str(path))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"get_connection_manager", "get_domain_manager"}
    ]


def _targets_network(call: ast.Call) -> bool:
    values = [*call.args, *(keyword.value for keyword in call.keywords)]
    return any(isinstance(value, ast.Constant) and value.value == "network" for value in values)


def _has_site_scope(call: ast.Call) -> bool:
    return any(keyword.arg == "site" for keyword in call.keywords)


def test_every_network_rest_and_graphql_manager_resolution_is_site_scoped() -> None:
    unscoped: list[str] = []
    network_calls = 0
    for path in NETWORK_SURFACES:
        for call in _manager_factory_calls(path):
            if not _targets_network(call):
                continue
            network_calls += 1
            if not _has_site_scope(call):
                unscoped.append(f"{path.relative_to(API_ROOT)}:{call.lineno}")

    assert network_calls > 0
    assert unscoped == [], f"Network manager resolution must pass site=: {unscoped}"


def test_action_dispatch_forwards_site_to_manager_factory() -> None:
    path = API_ROOT / "services" / "actions.py"
    calls = [call for call in _manager_factory_calls(path) if call.func.attr == "get_domain_manager"]

    assert len(calls) == 1
    assert _has_site_scope(calls[0])
