"""The real Protect registration takes the controller's operation gate before the connection wait.

A probe write and a probe read are registered through the app's own
``server.tool`` and called through MCP dispatch. The connection wait sees the
gate already held, so the wiring is gate, then connection, then the tool. The
same check against a server that passes a gate provider but pre-wraps the
connection wait around the raw decorator fails.
"""

from __future__ import annotations

import asyncio
import json
import logging

import pytest

import unifi_protect_mcp.main as main_mod
from unifi_core.operation_gate import (
    GateKey,
    GateSettings,
    OperationGate,
    gate_registry,
    observing_operations,
    reset_gate_registry_for_tests,
)
from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_mcp_shared.tool_index import TOOL_REGISTRY
from unifi_protect_mcp import runtime
from unifi_protect_mcp.reconnect import reconnecting_tool_decorator

PREFIX = "protect"
PROBES = (f"{PREFIX}_gate_wiring_probe_write", f"{PREFIX}_gate_wiring_probe_read")


@pytest.fixture
def wiring(monkeypatch):
    connection_manager = runtime.connection_manager
    monkeypatch.setattr(connection_manager, "host", "controller.test")
    monkeypatch.setattr(connection_manager, "port", 443)
    seen: list[tuple] = []

    async def ensure_connected(self) -> bool:
        gate = runtime.get_operation_gate()
        if gate is not None:
            seen.append(("connect", gate.holds_write(), gate.snapshot()["reads_in_use"]))
        return True

    # On the class: undoing an instance patch would pin a bound method to the singleton.
    monkeypatch.setattr(type(connection_manager), "ensure_connected", ensure_connected)
    reset_gate_registry_for_tests()
    yield seen
    for name in PROBES:
        if main_mod.server._tool_manager.get_tool(name) is not None:
            main_mod.server.remove_tool(name)
        TOOL_REGISTRY.pop(name, None)
    reset_gate_registry_for_tests()


async def _observe_gate_order(tool_decorator, seen: list[tuple]) -> list[tuple]:
    @tool_decorator(name=PROBES[0], permission_category="cameras", permission_action="update")
    async def probe_write(confirm: bool = False) -> dict:
        seen.append(("write body", runtime.get_operation_gate().holds_write()))
        return {"success": True, "data": {}}

    @tool_decorator(name=PROBES[1], annotations={"readOnlyHint": True})
    async def probe_read() -> dict:
        seen.append(("read body", runtime.get_operation_gate().snapshot()["reads_in_use"]))
        return {"success": True, "data": {}}

    await main_mod.server.call_tool(PROBES[0], {"confirm": True})
    await main_mod.server.call_tool(PROBES[1], {})
    return seen


GATE_FIRST = [("connect", True, 0), ("write body", True), ("connect", False, 1), ("read body", 1)]


async def test_the_app_takes_the_gate_before_the_connection_wait(wiring):
    assert await _observe_gate_order(main_mod.server.tool, wiring) == GATE_FIRST


async def test_a_pre_wrapped_connection_wait_fails_the_wiring_check(wiring):
    misplaced = create_permissioned_tool(
        original_tool_decorator=reconnecting_tool_decorator(
            main_mod._original_tool_decorator, runtime.connection_manager
        ),
        policy_gate_checker=PolicyGateChecker(server_prefix="protect"),
        server_prefix="protect",
        register_tool_fn=lambda **kwargs: None,
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda func, name: func,
        logger=logging.getLogger("test"),
        gate_provider=runtime.get_operation_gate,
    )
    observed = await _observe_gate_order(misplaced, wiring)
    assert observed != GATE_FIRST
    assert observed[0] == ("connect", False, 0)


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

    @main_mod.server.tool(name=PROBES[0], permission_category="cameras", permission_action="update")
    async def probe_write(confirm: bool = False) -> dict:
        return {"success": True, "data": {}}

    async with observing_operations(Observer()):
        await main_mod.server.call_tool(PROBES[0], {"confirm": True})
    assert admitted == ["admitted"]


def test_the_gate_is_keyed_by_host_port_and_product(wiring):
    gate = runtime.get_operation_gate()
    assert gate is runtime.get_operation_gate()
    assert gate.name == "protect"
    assert gate.settings == runtime.get_gate_settings()


async def test_a_held_write_is_bounded_by_its_remaining_hold_budget_and_reads_are_not(wiring, monkeypatch):
    class Clock:
        value = 0.0

        def now(self) -> float:
            return self.value

        async def sleep(self, seconds: float) -> None:
            await asyncio.sleep(seconds)

    clock = Clock()
    gate = OperationGate(GateSettings(hold_budget_seconds=10), name="protect", clock=clock)
    gate_registry()._gates[GateKey.for_host("controller.test", 443, "protect")] = gate

    async def ensure_connected(self) -> bool:
        clock.value += 9.99  # the connection wait used up nearly all of the write's budget
        return True

    monkeypatch.setattr(type(runtime.connection_manager), "ensure_connected", ensure_connected)

    @main_mod.server.tool(name=PROBES[0], permission_category="cameras", permission_action="update")
    async def probe_write(confirm: bool = False) -> dict:
        try:
            await asyncio.sleep(1)  # a hung controller, retried by uiprotect
        except Exception:  # noqa: BLE001 - tools catch everything; the bound still wins
            return {"success": False, "error": "swallowed"}
        return {"success": True, "data": {}}

    @main_mod.server.tool(name=PROBES[1], annotations={"readOnlyHint": True})
    async def probe_read() -> dict:
        await asyncio.sleep(0.02)
        return {"success": True, "data": {}}

    result = json.loads((await main_mod.server.call_tool(PROBES[0], {"confirm": True})).content[0].text)
    assert result["success"] is False
    assert result["mutation_applied"] is None
    assert "may or may not have been applied" in result["error"]
    assert not gate.write_held

    read = json.loads((await main_mod.server.call_tool(PROBES[1], {})).content[0].text)
    assert read["success"] is True


async def test_the_support_bundle_summarises_the_gate_without_naming_the_controller(wiring):
    evidence = await runtime.support_bundle_adapter.collect("summary", None)
    summary = evidence.connection.operation_gate
    assert summary is not None
    assert summary.read_cap == runtime.get_gate_settings().read_cap
    assert "test" not in summary.model_dump_json()
