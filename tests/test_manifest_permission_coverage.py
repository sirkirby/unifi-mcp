"""Every tool that can change state is policy-checked.

A tool registered without ``permission_action`` is never checked against the
policy gates, so the committed manifests must show it as read-only. The
shared meta-tools are the exception: they register outside
``permissioned_tool`` and dispatch through ``server.call_tool``, which reaches
the gated domain tool.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from unifi_mcp_shared.meta_tools import is_meta_tool

ROOT = Path(__file__).resolve().parent.parent
MANIFESTS = {
    "network": ROOT / "apps/network/src/unifi_network_mcp/tools_manifest.json",
    "protect": ROOT / "apps/protect/src/unifi_protect_mcp/tools_manifest.json",
    "access": ROOT / "apps/access/src/unifi_access_mcp/tools_manifest.json",
}


def _tools(server: str) -> list[dict]:
    return json.loads(MANIFESTS[server].read_text())["tools"]


@pytest.mark.parametrize("server", sorted(MANIFESTS))
def test_ungated_tools_are_read_only(server):
    ungated_mutating = [
        tool["name"]
        for tool in _tools(server)
        if not tool.get("permission_action")
        and not is_meta_tool(tool["name"])
        and (tool.get("annotations") or {}).get("readOnlyHint") is not True
    ]

    assert ungated_mutating == [], (
        f"{server} tools with no permission_action that are not annotated readOnlyHint=True: {ungated_mutating}"
    )
