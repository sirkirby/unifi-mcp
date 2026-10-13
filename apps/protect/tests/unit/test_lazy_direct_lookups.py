"""In the default lazy mode a read-only client reads a camera directly.

Lazy mode lists only meta-tools and the read-only tools in ``LAZY_DIRECT_TOOLS``.
The server runs as a real stdio process against a loopback fake NVR that
connects with an empty bootstrap: the client lists the tools, keeps those
annotated ``readOnlyHint: true``, and calls ``protect_get_camera`` from that
set, without ``protect_execute``. The fake has no cameras, so the connected
lookup answers that the camera does not exist.
"""

from __future__ import annotations

import asyncio

import pytest
from fake_controller import FakeController, closed_port, run_stdio_server, tool_payload

pytestmark = pytest.mark.real_reconnect

META_TOOLS = {
    "protect_tool_index",
    "protect_execute",
    "protect_batch",
    "protect_batch_status",
    "protect_load_tools",
    "protect_get_support_bundle",
}
DIRECT_TOOLS = {"protect_get_incident_evidence", "protect_get_camera"}


@pytest.mark.asyncio
async def test_lazy_mode_lists_the_camera_lookup_and_a_read_only_client_calls_it(tmp_path):
    controller = FakeController("protect")
    port = closed_port()
    await controller.start(port, tmp_path)
    try:
        run = await asyncio.to_thread(
            run_stdio_server,
            tmp_path,
            module="unifi_protect_mcp",
            env_prefix="PROTECT",
            port=port,
            tool="protect_get_camera",
            arguments={"camera_id": "fixture-camera-0001"},
            wait_seconds=15.0,
        )
    finally:
        await controller.close()

    assert set(run["tools"]) == META_TOOLS | DIRECT_TOOLS
    read_only = {entry["name"] for entry in run["listed"] if (entry.get("annotations") or {}).get("readOnlyHint")}
    assert DIRECT_TOOLS <= read_only
    assert "protect_execute" not in read_only

    payload = tool_payload(run["call"])
    assert payload["success"] is False
    assert "fixture-camera-0001" in payload["error"] and "not found" in payload["error"].lower(), payload
    assert controller.logins >= 1
