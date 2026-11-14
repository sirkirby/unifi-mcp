"""Every tool in the committed manifests declares its MCP behavior hints.

Read-only tools declare ``idempotentHint`` as well, since repeating a read
changes nothing. Mutating tools declare all four hints so clients never fall
back to the spec defaults (destructive, non-idempotent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = {
    "network": ROOT / "apps/network/src/unifi_network_mcp/tools_manifest.json",
    "protect": ROOT / "apps/protect/src/unifi_protect_mcp/tools_manifest.json",
    "access": ROOT / "apps/access/src/unifi_access_mcp/tools_manifest.json",
}
READ_HINTS = ("readOnlyHint", "idempotentHint", "openWorldHint")
WRITE_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")


def _tools(server: str) -> list[dict]:
    return json.loads(MANIFESTS[server].read_text())["tools"]


@pytest.mark.parametrize("server", sorted(MANIFESTS))
def test_every_tool_declares_its_hints(server):
    missing = {}
    for tool in _tools(server):
        annotations = tool.get("annotations") or {}
        required = READ_HINTS if annotations.get("readOnlyHint") is True else WRITE_HINTS
        absent = [hint for hint in required if hint not in annotations]
        if absent:
            missing[tool["name"]] = absent

    assert missing == {}, f"{server} tools with undeclared hints: {missing}"


@pytest.mark.parametrize("server", sorted(MANIFESTS))
def test_read_only_tools_are_idempotent(server):
    not_idempotent = [
        tool["name"]
        for tool in _tools(server)
        if (tool.get("annotations") or {}).get("readOnlyHint") is True
        and tool["annotations"].get("idempotentHint") is not True
    ]

    assert not_idempotent == [], f"{server} read-only tools not marked idempotent: {not_idempotent}"
