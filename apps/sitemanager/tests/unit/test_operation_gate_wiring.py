"""Site Manager wires no operation gate, explicitly, and its calls still admit batch jobs."""

from __future__ import annotations

import pytest

import unifi_sitemanager_mcp.main as main_mod
from unifi_core.operation_gate import gate_registry, observing_operations, reset_gate_registry_for_tests
from unifi_mcp_shared.tool_index import TOOL_REGISTRY

PROBE = "sitemanager_gate_wiring_probe_read"


@pytest.fixture
def probe():
    reset_gate_registry_for_tests()
    yield
    if main_mod.server._tool_manager.get_tool(PROBE) is not None:
        main_mod.server.remove_tool(PROBE)
    TOOL_REGISTRY.pop(PROBE, None)


async def test_calls_take_no_gate_and_still_signal_admission(probe):
    admitted: list[str] = []

    class Observer:
        def admitted(self) -> None:
            admitted.append("admitted")

        def queued(self, ticket) -> None:
            raise AssertionError("Site Manager never queues at a gate")

        def granted(self, ticket) -> None:
            raise AssertionError("Site Manager never queues at a gate")

    @main_mod.server.tool(name=PROBE, annotations={"readOnlyHint": True})
    async def probe_read() -> dict:
        return {"success": True, "data": {}}

    async with observing_operations(Observer()):
        await main_mod.server.call_tool(PROBE, {})
    assert admitted == ["admitted"]
    assert gate_registry().gates() == {}
