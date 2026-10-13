"""In the default lazy mode a read-only client looks up a camera's uplink directly.

Lazy mode lists only meta-tools and the read-only tools in ``LAZY_DIRECT_TOOLS``.
The server runs as a real stdio process against a loopback fake controller
that knows one wired client: the client lists the tools, keeps those annotated
``readOnlyHint: true``, and calls ``unifi_get_client_details`` from that set,
without ``unifi_execute``.
"""

from __future__ import annotations

import asyncio

import pytest
from fake_controller import FakeController, closed_port, run_stdio_server, tool_payload

pytestmark = pytest.mark.real_reconnect

CAMERA_MAC = "02:00:00:00:0a:01"
SWITCH_MAC = "02:00:00:00:10:01"
CAMERA_CLIENT = {"mac": CAMERA_MAC, "is_wired": True, "sw_mac": SWITCH_MAC, "sw_port": 7, "hostname": "fixture-camera"}
META_TOOLS = {
    "unifi_tool_index",
    "unifi_execute",
    "unifi_batch",
    "unifi_batch_status",
    "unifi_load_tools",
    "unifi_get_support_bundle",
}
DIRECT_TOOLS = {"unifi_get_incident_evidence", "unifi_get_client_details"}


@pytest.mark.asyncio
async def test_lazy_mode_lists_the_client_lookup_and_a_read_only_client_calls_it(tmp_path):
    controller = FakeController("network", network_rows={"/stat/sta": [CAMERA_CLIENT]})
    port = closed_port()
    await controller.start(port, tmp_path)
    try:
        run = await asyncio.to_thread(
            run_stdio_server,
            tmp_path,
            module="unifi_network_mcp",
            env_prefix="NETWORK",
            port=port,
            tool="unifi_get_client_details",
            arguments={"mac_address": CAMERA_MAC},
            wait_seconds=15.0,
        )
    finally:
        await controller.close()

    assert set(run["tools"]) == META_TOOLS | DIRECT_TOOLS
    read_only = {entry["name"] for entry in run["listed"] if (entry.get("annotations") or {}).get("readOnlyHint")}
    assert DIRECT_TOOLS <= read_only
    assert "unifi_execute" not in read_only

    payload = tool_payload(run["call"])
    assert payload["success"] is True, payload
    # The uplink identifiers that tie the camera to its switch port.
    assert payload["client"]["mac"] == CAMERA_MAC
    assert (payload["client"]["sw_mac"], payload["client"]["sw_port"]) == (SWITCH_MAC, 7)
    assert controller.logins >= 1
