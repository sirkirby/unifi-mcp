"""Every Network tool that takes a MAC declares the other MAC spellings as aliases.

Scope, read from the generated manifest: a tool is in scope when it declares
exactly one property spelled ``mac_address``, ``device_mac``, ``client_mac``,
``mac``, ``ap_mac`` or ``gateway_mac``. ``unifi_get_traffic_flows`` takes
``source_mac``, a flow *filter* rather than the identity of the thing being
operated on, and ``unifi_create_acl_rule`` takes the list-valued
``source_macs``/``destination_macs``; neither is aliased.
"""

from __future__ import annotations

import json
import subprocess
import sys
from functools import cache

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from unifi_mcp_shared.argument_aliases import MAC_SPELLINGS, argument_alias_note, mac_aliases
from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP
from unifi_network_mcp.runtime import _TOOLS_MANIFEST_PATH as MANIFEST_PATH

#: The MAC spellings plus the two role-specific parameter names that take a device MAC.
MAC_PARAMETERS = frozenset(MAC_SPELLINGS) | {"ap_mac", "gateway_mac"}


@cache
def _tools() -> list[dict]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["tools"]


def _mac_properties(tool: dict) -> list[str]:
    return [p for p in tool["schema"]["input"].get("properties", {}) if p in MAC_PARAMETERS]


@pytest.mark.parametrize("tool", [t for t in _tools() if _mac_properties(t)], ids=lambda t: t["name"])
def test_mac_tool_declares_every_other_spelling(tool: dict) -> None:
    (canonical,) = _mac_properties(tool)
    assert tool.get("argument_aliases") == mac_aliases(canonical)


@pytest.mark.parametrize("tool", [t for t in _tools() if _mac_properties(t)], ids=lambda t: t["name"])
def test_mac_tool_description_names_the_aliases(tool: dict) -> None:
    (canonical,) = _mac_properties(tool)
    assert argument_alias_note(mac_aliases(canonical)) in tool["description"]


@pytest.mark.parametrize("tool", [t for t in _tools() if not _mac_properties(t)], ids=lambda t: t["name"])
def test_non_mac_tool_declares_no_aliases(tool: dict) -> None:
    assert "argument_aliases" not in tool


def test_no_alias_collides_with_a_declared_property() -> None:
    for tool in _tools():
        properties = tool["schema"]["input"].get("properties", {})
        for alias, canonical in tool.get("argument_aliases", {}).items():
            assert alias not in properties, (tool["name"], alias)
            assert canonical in properties, (tool["name"], canonical)


async def test_real_manifest_rewrites_alias_at_dispatch() -> None:
    """A registered tool receives the canonical name when the caller used an alias."""
    server = StrictKwargFastMCP("network-test", tools_manifest_path=MANIFEST_PATH)
    seen: dict[str, str] = {}

    @server.tool(name="unifi_get_client_details")
    async def stub(mac_address: str, summary: bool = False) -> dict:
        seen["mac_address"] = mac_address
        return {"success": True}

    await server.call_tool("unifi_get_client_details", {"device_mac": "aa:bb:cc:dd:ee:ff"})
    assert seen == {"mac_address": "aa:bb:cc:dd:ee:ff"}


async def test_real_manifest_rewrites_every_spelling_for_gateway_mac() -> None:
    server = StrictKwargFastMCP("network-test", tools_manifest_path=MANIFEST_PATH)
    seen: dict[str, str] = {}

    @server.tool(name="unifi_get_speedtest_status")
    async def stub(gateway_mac: str) -> dict:
        seen["gateway_mac"] = gateway_mac
        return {"success": True}

    for spelling in MAC_SPELLINGS:
        seen.clear()
        await server.call_tool("unifi_get_speedtest_status", {spelling: "aa:bb:cc:dd:ee:ff"})
        assert seen == {"gateway_mac": "aa:bb:cc:dd:ee:ff"}, spelling


async def test_real_manifest_keeps_source_mac_unaliased() -> None:
    server = StrictKwargFastMCP("network-test", tools_manifest_path=MANIFEST_PATH)
    with pytest.raises(ToolError, match="unknown arguments {device_mac}"):
        await server.call_tool("unifi_get_traffic_flows", {"device_mac": "aa:bb:cc:dd:ee:ff"})


_REGISTRY_DUMP = """
import importlib, json
import unifi_network_mcp.main  # installs the permissioned decorator on the server
for module in ("clients", "devices", "switch", "stats", "events"):
    importlib.import_module(f"unifi_network_mcp.tools.{module}")
from unifi_network_mcp.tool_index import TOOL_REGISTRY
print(json.dumps({n: [m.argument_aliases, m.description] for n, m in TOOL_REGISTRY.items()}))
"""


def test_committed_manifest_matches_the_decorators() -> None:
    """The rewrite reads the manifest; the decorators promise the aliases. Both must agree.

    Runs in a subprocess so the permissioned decorator, not the import-time
    wrapper, registers the tools, and so nothing in this process is reloaded.
    """
    proc = subprocess.run([sys.executable, "-c", _REGISTRY_DUMP], capture_output=True, text=True, check=True)
    registry = json.loads(proc.stdout.strip().splitlines()[-1])
    mac_tools = [t for t in _tools() if _mac_properties(t)]
    assert mac_tools
    for tool in mac_tools:
        aliases, description = registry[tool["name"]]
        assert tool["argument_aliases"] == aliases, tool["name"]
        assert tool["description"] == description, tool["name"]
