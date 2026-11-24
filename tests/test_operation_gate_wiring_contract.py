"""Every MCP app states its operation-gate wiring explicitly.

Shared defaults ``gate_provider`` to None so older apps keep working, which
means a new app that forgets it silently runs ungated. Each app's main module
must pass ``gate_provider`` by keyword, and an app with a connection-wait
wrapper must hand it over as ``connection_decorator`` rather than pre-wrap the
raw decorator, or the gate would sit inside the wait. The per-app wiring tests
check the behaviour through real registration; this checks the declaration.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APPS = {
    "network": ("unifi_network_mcp", True),
    "protect": ("unifi_protect_mcp", True),
    "access": ("unifi_access_mcp", False),
    "drive": ("unifi_drive_mcp", False),
    "innerspace": ("unifi_innerspace_mcp", False),
    "sitemanager": ("unifi_sitemanager_mcp", False),
}
FACTORIES = {"create_permissioned_tool", "setup_permissioned_tool"}


def _permissioned_tool_call(app: str, package: str) -> ast.Call:
    tree = ast.parse((ROOT / "apps" / app / "src" / package / "main.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FACTORIES
    ]
    assert len(calls) == 1, f"{app}: expected one permissioned_tool factory call, found {len(calls)}"
    return calls[0]


def test_every_mcp_app_is_listed():
    assert set(APPS) == {main.parents[2].name for main in ROOT.glob("apps/*/src/unifi_*_mcp/main.py")}


@pytest.mark.parametrize("app", sorted(APPS))
def test_every_app_passes_its_gate_provider_by_keyword(app):
    package, _ = APPS[app]
    keywords = {keyword.arg: keyword.value for keyword in _permissioned_tool_call(app, package).keywords}
    assert "gate_provider" in keywords, f"{app} must pass gate_provider explicitly (None when it has no gate)"
    if app == "sitemanager":
        assert isinstance(keywords["gate_provider"], ast.Constant) and keywords["gate_provider"].value is None
    else:
        assert not (isinstance(keywords["gate_provider"], ast.Constant) and keywords["gate_provider"].value is None)


@pytest.mark.parametrize("app", sorted(APPS))
def test_the_connection_wait_is_handed_over_not_pre_wrapped(app):
    package, waits_for_connection = APPS[app]
    keywords = {keyword.arg: keyword.value for keyword in _permissioned_tool_call(app, package).keywords}
    original = keywords.get("original_tool_decorator")
    if original is not None:
        assert isinstance(original, ast.Name), f"{app}: original_tool_decorator must be the raw decorator"
    assert ("connection_decorator" in keywords) is waits_for_connection
