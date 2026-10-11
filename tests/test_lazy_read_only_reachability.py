"""A client that permits only readOnlyHint tools can collect incident evidence in the default mode.

Each server runs as a real stdio process in its default (lazy) registration
mode, pointed at a loopback address with no controller behind it. The test
acts as a read-only client: it lists tools, keeps only those annotated
``readOnlyHint: true``, and calls the incident evidence tool from that set.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters
from unifi_core.incident_evidence import OverallStatus, validate_incident_evidence

_script_path = Path(__file__).parent.parent / "scripts" / "smoke_mcp_metadata.py"
_spec = importlib.util.spec_from_file_location("smoke_mcp_metadata_for_reachability", _script_path)
_smoke = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _smoke
_spec.loader.exec_module(_smoke)

SERVERS = {
    "network": ("unifi-network-mcp", "unifi", "unifi_get_incident_evidence"),
    "protect": ("unifi-protect-mcp", "protect", "protect_get_incident_evidence"),
}
WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T13:00:00Z"}


def _default_mode_env() -> dict[str, str]:
    env = _smoke.smoke_env(registration_mode="lazy")
    env.pop("UNIFI_TOOL_REGISTRATION_MODE")  # exercise the default, not an explicit choice
    return env


def _payload(result: Any) -> dict[str, Any]:
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if isinstance(structured, dict) and "success" in structured:
        return structured
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    raise AssertionError("tool returned no JSON payload")


def _read_only(tool: Any) -> bool:
    annotations = tool.annotations
    return annotations is not None and annotations.read_only_hint is True


async def _read_only_client_collects(product: str) -> None:
    package, prefix, tool_name = SERVERS[product]
    params = StdioServerParameters(
        command="uv",
        args=["run", "--no-sync", "--package", package, package],
        cwd=_smoke.REPO_ROOT,
        env=_default_mode_env(),
    )
    async with Client(params) as client:
        listed = (await client.list_tools()).tools
        permitted = {tool.name for tool in listed if _read_only(tool)}
        # Without direct registration the only route to a domain tool is *_execute, which is not read-only.
        assert f"{prefix}_execute" in {tool.name for tool in listed}
        assert f"{prefix}_execute" not in permitted
        assert tool_name in permitted

        result = await client.call_tool(tool_name, {**WINDOW, "max_calls": 1, "max_elapsed_ms": 5_000})
        payload = _payload(result)
        assert payload["success"] is True
        evidence = validate_incident_evidence(payload["data"])
        # No controller answers on loopback: the failure is reported per source, never as an empty all-clear.
        assert evidence.overall is OverallStatus.FAILED
        assert evidence.coverage_complete is False


@pytest.mark.parametrize("product", sorted(SERVERS))
def test_read_only_client_reaches_incident_evidence_in_default_mode(product: str) -> None:
    async def run() -> None:
        with anyio.fail_after(90):
            await _read_only_client_collects(product)

    anyio.run(run)
