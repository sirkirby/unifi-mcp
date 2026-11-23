"""The real Access registration runs every tool call inside the controller's operation gate.

Access has no connection-wait wrapper: its managers connect on demand from
inside the tool, which is inside the gate. Probe tools registered through the
app's own ``server.tool`` and called through MCP dispatch see the write turn
held for a confirmed write and one read slot taken for a read.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

import unifi_access_mcp.main as main_mod
from unifi_access_mcp import runtime
from unifi_core.operation_gate import (
    GateKey,
    GateSettings,
    OperationGate,
    gate_registry,
    observing_operations,
    reset_gate_registry_for_tests,
)
from unifi_mcp_shared.tool_index import TOOL_REGISTRY

PROBES = ("access_gate_wiring_probe_write", "access_gate_wiring_probe_read")


@pytest.fixture
def wiring(monkeypatch):
    monkeypatch.setattr(runtime.connection_manager, "host", "access.test")
    monkeypatch.setattr(runtime.connection_manager, "port", 443)
    reset_gate_registry_for_tests()
    yield
    for name in PROBES:
        if main_mod.server._tool_manager.get_tool(name) is not None:
            main_mod.server.remove_tool(name)
        TOOL_REGISTRY.pop(name, None)
    reset_gate_registry_for_tests()


async def test_confirmed_writes_hold_the_write_turn_and_reads_take_a_slot(wiring):
    seen: list[tuple] = []

    @main_mod.server.tool(name=PROBES[0], permission_category="doors", permission_action="update")
    async def probe_write(confirm: bool = False) -> dict:
        seen.append(("write", confirm, runtime.get_operation_gate().holds_write()))
        return {"success": True, "data": {}}

    @main_mod.server.tool(name=PROBES[1], annotations={"readOnlyHint": True})
    async def probe_read() -> dict:
        seen.append(("read", runtime.get_operation_gate().snapshot()["reads_in_use"]))
        return {"success": True, "data": {}}

    await main_mod.server.call_tool(PROBES[0], {"confirm": True})
    await main_mod.server.call_tool(PROBES[0], {"confirm": False})
    await main_mod.server.call_tool(PROBES[1], {})
    assert seen == [("write", True, True), ("write", False, False), ("read", 1)]
    assert runtime.get_operation_gate().name == "access"


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

    @main_mod.server.tool(name=PROBES[0], permission_category="doors", permission_action="update")
    async def probe_write(confirm: bool = False) -> dict:
        return {"success": True, "data": {}}

    async with observing_operations(Observer()):
        await main_mod.server.call_tool(PROBES[0], {"confirm": True})
    assert admitted == ["admitted"]


async def test_the_support_bundle_summarises_the_gate_without_naming_the_controller(wiring):
    import json as _json

    gate = runtime.get_operation_gate()
    async with gate.write(label="access_update_secret_wlan_name"):
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
    assert "access.test" not in text
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


class _HangingProxySession:
    """A proxy session whose controller never answers."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def request(self, method, url, **kwargs):
        session = self

        class _Response:
            async def __aenter__(self):
                session.sent.append(method)
                await asyncio.sleep(10)

            async def __aexit__(self, *exc_info):
                return False

        return _Response()


@pytest.mark.parametrize(
    ("clock", "expected", "guidance"),
    [
        (_FrozenClock, None, "may or may not have been applied"),
        (_LeapingClock, False, "was not sent"),
    ],
)
async def test_a_lock_cut_off_at_its_hold_budget_reports_its_outcome(wiring, monkeypatch, clock, expected, guidance):
    """The real lock tool body, manager and proxy request, called through MCP dispatch."""
    from unifi_access_mcp.tools import doors

    gate = OperationGate(GateSettings(hold_budget_seconds=0.05), name="access", clock=clock())
    gate_registry()._gates[GateKey.for_host("access.test", 443, "access")] = gate
    session = _HangingProxySession()
    # The manager the tool module holds: other tests may have rebuilt the runtime's since.
    connection_manager = doors.door_manager._cm
    monkeypatch.setattr(connection_manager, "_api_client_available", False)
    monkeypatch.setattr(connection_manager, "_proxy_available", True)
    monkeypatch.setattr(connection_manager, "_proxy_session", session)
    monkeypatch.setattr(connection_manager, "_csrf_token", "csrf")

    main_mod.server.tool(name=PROBES[0], permission_category="door", permission_action="update")(
        inspect.unwrap(doors.access_lock_door)
    )
    result = await main_mod.server.call_tool(PROBES[0], {"door_id": "door-1", "confirm": True})

    payload = json.loads(result.content[0].text)
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to lock door: The ")
    assert guidance in payload["error"]
    assert payload["mutation_applied"] is expected
    assert result.structured_content["mutation_applied"] is expected
    assert session.sent == ([] if expected is False else ["PUT"])
    assert not gate.write_held
