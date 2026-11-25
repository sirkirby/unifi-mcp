"""The real Drive registration runs every tool call inside the NAS's operation gate.

Drive has no connection-wait wrapper: the first tool call logs in from inside
the tool, which is inside the gate. A probe tool registered through the app's
own ``server.tool`` and called through MCP dispatch sees one read slot taken;
a confirmed write tool holds the write turn and its preview takes a read slot.
"""

from __future__ import annotations

import asyncio
import inspect
import json

import pytest

import unifi_drive_mcp.main as main_mod
from unifi_core.drive.managers.file_service_manager import FileServiceManager
from unifi_core.operation_gate import (
    GateKey,
    GateSettings,
    OperationGate,
    gate_registry,
    observing_operations,
    reset_gate_registry_for_tests,
    write_request_bound,
)
from unifi_drive_mcp import runtime
from unifi_mcp_shared.tool_index import TOOL_REGISTRY

PROBE = "drive_gate_wiring_probe_read"
WRITE_PROBE = "drive_gate_wiring_probe_write"
CLIENT = "192.0.2.76"
DRIVE_ID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def wiring(monkeypatch):
    monkeypatch.setattr(runtime.connection_manager, "host", "drive.test")
    monkeypatch.setattr(runtime.connection_manager, "port", 443)
    reset_gate_registry_for_tests()
    yield
    for name in (PROBE, WRITE_PROBE):
        if main_mod.server._tool_manager.get_tool(name) is not None:
            main_mod.server.remove_tool(name)
        TOOL_REGISTRY.pop(name, None)
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


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class _Nas:
    """A Drive connection stand-in whose requests pass the write bound like the real one's.

    ``after_first_read`` runs once the first read has gone out.
    """

    def __init__(self, after_first_read=None) -> None:
        self.sent: list[str] = []
        self._after_first_read = after_first_read

    async def get(self, path: str, **_kwargs):
        async with write_request_bound():
            self.sent.append("GET")
        if self._after_first_read is not None and self.sent == ["GET"]:
            self._after_first_read()
        return {
            "connections": [{"client": CLIENT, "async": False, "sharedDrives": [{"id": DRIVE_ID, "permission": "rw"}]}]
        }

    async def put(self, path: str, json_body, **_kwargs):
        async with write_request_bound():
            self.sent.append("PUT")
        return {}


def _register_remove_tool(monkeypatch, nas: _Nas, seen: list | None = None):
    from unifi_drive_mcp.tools import nfs

    manager = FileServiceManager(nas, shared_drives=None)
    if seen is not None:
        plan = manager.plan_remove_nfs_connection

        async def observed_plan(client):
            gate = runtime.get_operation_gate()
            seen.append((gate.holds_write(), gate.snapshot()["reads_in_use"]))
            return await plan(client)

        monkeypatch.setattr(manager, "plan_remove_nfs_connection", observed_plan)
    monkeypatch.setattr(nfs, "file_service_manager", manager)
    main_mod.server.tool(name=WRITE_PROBE, permission_category="nfs_connection", permission_action="delete")(
        inspect.unwrap(nfs.drive_remove_nfs_connection)
    )


async def test_a_confirmed_write_holds_the_write_turn_and_its_preview_takes_a_read_slot(wiring, monkeypatch):
    seen: list = []
    _register_remove_tool(monkeypatch, _Nas(), seen)

    await main_mod.server.call_tool(WRITE_PROBE, {"client": CLIENT, "confirm": False})
    await main_mod.server.call_tool(WRITE_PROBE, {"client": CLIENT, "confirm": True})

    assert seen == [(False, 1), (True, 0)]


async def test_a_change_whose_budget_runs_out_after_its_reads_reports_nothing_applied(wiring, monkeypatch):
    """The ticket counts the plan's read as sent; the tool's outcome, not the gate's, says nothing changed."""
    clock = _Clock()
    gate = OperationGate(GateSettings(hold_budget_seconds=10), name="drive", clock=clock)
    gate_registry()._gates[GateKey.for_host("drive.test", 443, "drive")] = gate

    def spend_the_budget() -> None:
        clock.value = 11

    nas = _Nas(after_first_read=spend_the_budget)
    _register_remove_tool(monkeypatch, nas)

    result = await main_mod.server.call_tool(WRITE_PROBE, {"client": CLIENT, "confirm": True})

    payload = json.loads(result.content[0].text)
    assert payload["success"] is False
    assert "nothing was changed" in payload["error"]
    assert payload["mutation_applied"] is False
    assert nas.sent == ["GET"]
    assert not gate.write_held
