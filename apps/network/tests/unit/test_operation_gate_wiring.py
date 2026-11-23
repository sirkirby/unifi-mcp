"""The real Network registration takes the controller's operation gate before the connection wait.

A probe write and a probe read are registered through the app's own
``server.tool`` and called through MCP dispatch. The connection wait sees the
gate already held, so the wiring is gate, then connection, then the tool. The
same check against a server that passes a gate provider but pre-wraps the
connection wait around the raw decorator fails.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import unifi_network_mcp.main as main_mod
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
from unifi_network_mcp import runtime
from unifi_network_mcp.reconnect import reconnecting_tool_decorator

PREFIX = "unifi"
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
    @tool_decorator(name=PROBES[0], permission_category="firewall", permission_action="update")
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
        policy_gate_checker=PolicyGateChecker(server_prefix="network"),
        server_prefix="network",
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

    @main_mod.server.tool(name=PROBES[0], permission_category="firewall", permission_action="update")
    async def probe_write(confirm: bool = False) -> dict:
        return {"success": True, "data": {}}

    async with observing_operations(Observer()):
        await main_mod.server.call_tool(PROBES[0], {"confirm": True})
    assert admitted == ["admitted"]


def test_the_gate_is_keyed_by_host_port_and_product(wiring):
    gate = runtime.get_operation_gate()
    assert gate is runtime.get_operation_gate()
    assert gate.name == "network"
    assert gate.settings == runtime.get_gate_settings()


async def test_the_support_bundle_summarises_the_gate_without_naming_the_controller(wiring):
    import json as _json

    gate = runtime.get_operation_gate()
    async with gate.write(label="unifi_update_secret_wlan_name"):
        pass
    async with gate.read():
        bundle = await runtime.support_bundle_service.generate(probe="summary")
    assert bundle["success"] is True, bundle
    summary = bundle["data"]["connection"]["operation_gate"]
    assert summary["read_cap"] == runtime.get_gate_settings().read_cap
    assert summary["reads_in_use"] == 1
    assert summary["writes_completed"] == "1"
    text = _json.dumps(bundle)
    # The whole bundle, not just the summary: no host, no tool label.
    assert "controller.test" not in text
    assert "secret_wlan" not in text


class _FrozenClock:
    """The whole hold budget is left whenever a request starts."""

    def now(self) -> float:
        return 0.0

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _LeapingClock:
    """Each reading is far past the last: the budget is spent before the first request."""

    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        self.value += 1_000.0
        return self.value

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(0)


@pytest.mark.parametrize(
    ("clock", "expected", "guidance"),
    [
        (_FrozenClock, None, "may or may not have been applied"),
        (_LeapingClock, False, "was not sent"),
    ],
)
async def test_a_reboot_cut_off_at_its_hold_budget_reports_its_outcome(wiring, monkeypatch, clock, expected, guidance):
    """The real reboot tool body, manager and connection request, called through MCP dispatch."""
    from unifi_network_mcp.tools import devices

    gate = OperationGate(GateSettings(hold_budget_seconds=0.05), name="network", clock=clock())
    gate_registry()._gates[GateKey.for_host("controller.test", 443, "network")] = gate
    sent: list[str] = []

    async def hang(api_request):
        sent.append(api_request.method)
        await asyncio.sleep(10)  # a controller that does not answer

    # The managers the tool module holds: other tests may have rebuilt the runtime's since.
    monkeypatch.setattr(
        devices.device_manager._connection,
        "controller",
        SimpleNamespace(request=hang, connectivity=SimpleNamespace(is_unifi_os=True)),
    )
    monkeypatch.setattr(devices.device_manager, "get_device_details", AsyncMock(return_value=object()))

    main_mod.server.tool(name=PROBES[0], permission_category="devices", permission_action="update")(
        inspect.unwrap(devices.reboot_device)
    )
    result = await main_mod.server.call_tool(PROBES[0], {"mac_address": "00:00:5e:00:53:01", "confirm": True})

    payload = json.loads(result.content[0].text)
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to reboot device 00:00:5e:00:53:01: The ")
    assert guidance in payload["error"]
    assert payload["mutation_applied"] is expected
    assert result.structured_content["mutation_applied"] is expected
    assert sent == ([] if expected is False else ["post"])
    assert not gate.write_held
