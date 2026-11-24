"""The real Drive registration runs every tool call inside the NAS's operation gate.

Drive has no connection-wait wrapper: the first tool call logs in from inside
the tool, which is inside the gate. A probe tool registered through the app's
own ``server.tool`` and called through MCP dispatch sees one read slot taken.
The server has no write tools yet, so only reads are probed here.
"""

from __future__ import annotations

import pytest

import unifi_drive_mcp.main as main_mod
from unifi_core.operation_gate import observing_operations, reset_gate_registry_for_tests
from unifi_drive_mcp import runtime
from unifi_mcp_shared.tool_index import TOOL_REGISTRY

PROBE = "drive_gate_wiring_probe_read"


@pytest.fixture
def wiring(monkeypatch):
    monkeypatch.setattr(runtime.connection_manager, "host", "drive.test")
    monkeypatch.setattr(runtime.connection_manager, "port", 443)
    reset_gate_registry_for_tests()
    yield
    if main_mod.server._tool_manager.get_tool(PROBE) is not None:
        main_mod.server.remove_tool(PROBE)
    TOOL_REGISTRY.pop(PROBE, None)
    reset_gate_registry_for_tests()


def _register_read_probe(seen: list) -> None:
    @main_mod.server.tool(name=PROBE, permission_category="system", annotations={"readOnlyHint": True})
    async def probe_read() -> dict:
        gate = runtime.get_operation_gate()
        seen.append(gate.snapshot()["reads_in_use"] if gate is not None else None)
        return {"success": True, "data": {}}


async def test_a_read_takes_a_slot_at_the_drive_gate(wiring):
    seen: list = []
    _register_read_probe(seen)

    await main_mod.server.call_tool(PROBE, {})

    assert seen == [1]
    assert runtime.get_operation_gate().name == "drive"
    assert runtime.get_operation_gate().snapshot()["reads_in_use"] == 0


async def test_the_gate_settings_come_from_the_drive_prefix(wiring, monkeypatch):
    monkeypatch.setenv("UNIFI_DRIVE_READ_CONCURRENCY", "3")
    runtime.get_gate_settings.cache_clear()
    try:
        assert runtime.get_gate_settings().read_cap == 3
        assert runtime.get_operation_gate().snapshot()["read_cap"] == 3
    finally:
        runtime.get_gate_settings.cache_clear()


async def test_no_host_means_no_gate_but_the_call_is_still_admitted(wiring, monkeypatch):
    monkeypatch.setattr(runtime.connection_manager, "host", "")
    assert runtime.get_operation_gate() is None
    admitted: list[str] = []

    class Observer:
        def admitted(self) -> None:
            admitted.append("admitted")

        def queued(self, ticket) -> None:
            pass

        def granted(self, ticket) -> None:
            pass

    seen: list = []
    _register_read_probe(seen)
    async with observing_operations(Observer()):
        await main_mod.server.call_tool(PROBE, {})
    assert admitted == ["admitted"]
    assert seen == [None]
