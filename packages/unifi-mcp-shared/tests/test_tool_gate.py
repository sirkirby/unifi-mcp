"""Domain tool calls take their controller's operation gate; meta tools never do."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.server.mcpserver import MCPServer as FastMCP
from unifi_core.jobs import JobStore
from unifi_core.operation_gate import GateSettings, OperationGate, observing_operations, write_request_bound
from unifi_core.policy_gate import PolicyGateChecker
from unifi_mcp_shared.meta_tools import BATCH_JOB_STATUSES, register_meta_tools
from unifi_mcp_shared.permissioned_tool import create_permissioned_tool
from unifi_mcp_shared.tasks import task_from_job_status
from unifi_mcp_shared.tool_gate import (
    EXIT_GATE_SETTINGS_INVALID,
    gate_settings_from_env,
    make_call_classifier,
)

LOGGER = logging.getLogger("test-tool-gate")


class FakeClock:
    """A gate clock that only moves when the test advances it."""

    def __init__(self) -> None:
        self.value = 0.0
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (self.value + seconds, future)
        self._sleepers.append(entry)
        try:
            await future
        finally:
            self._sleepers.remove(entry)

    async def advance(self, seconds: float) -> None:
        self.value += seconds
        for deadline, future in list(self._sleepers):
            if deadline <= self.value and not future.done():
                future.set_result(None)
        await settle()


async def settle(rounds: int = 40) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


def _payload(result) -> dict:
    return json.loads(result.content[0].text)


class Harness:
    """A FastMCP server whose domain tools register through permissioned_tool with a gate."""

    def __init__(
        self,
        *,
        gate: OperationGate | None = None,
        provider: bool = True,
        prefix: str = "unifi",
        connection_decorator=None,
        legacy_original=None,
        server=None,
    ) -> None:
        self.server = server or FastMCP(f"{prefix}-gate-test")
        # Meta tools register with the plain decorator, never permissioned_tool.
        self.plain_tool = self.server.tool
        self.gate = gate or OperationGate(GateSettings(), name="network")
        self.prefix = prefix
        self.store = JobStore()
        self.events: list[str] = []
        self.release = asyncio.Event()
        self.server.tool = create_permissioned_tool(
            original_tool_decorator=legacy_original(self.server.tool) if legacy_original else self.server.tool,
            policy_gate_checker=PolicyGateChecker(server_prefix="test"),
            server_prefix="TEST",
            register_tool_fn=Mock(),
            diagnostics_enabled_fn=lambda: False,
            wrap_tool_fn=lambda func, name: func,
            logger=LOGGER,
            gate_provider=(lambda: self.gate) if provider else None,
            connection_decorator=connection_decorator,
        )
        self._register_domain_tools()

    def _register_domain_tools(self) -> None:
        tool = self.server.tool
        gate = self.gate
        events = self.events
        prefix = self.prefix

        @tool(name=f"{prefix}_update_thing", permission_category="things", permission_action="update")
        async def update_thing(name: str, confirm: bool = False) -> dict:
            mode = "write" if gate.holds_write() else f"read:{gate.snapshot()['reads_in_use']}"
            events.append(f"update:{name}:{confirm}:{mode}")
            return {"success": True, "data": {"name": name, "mode": mode}}

        @tool(name=f"{prefix}_create_thing", permission_category="things", permission_action="create")
        async def create_thing(name: str) -> dict:
            events.append(f"create:{name}:{'write' if gate.holds_write() else 'read'}")
            return {"success": True, "data": {"name": name}}

        @tool(name=f"{prefix}_list_things", permission_category="things", permission_action="read")
        async def list_things() -> dict:
            events.append(f"list:{gate.snapshot()['reads_in_use']}:{gate.holds_write()}")
            return {"success": True, "data": []}

        @tool(name=f"{prefix}_get_status", annotations={"readOnlyHint": True})
        async def get_status() -> dict:
            events.append(f"status:{gate.snapshot()['reads_in_use']}")
            return {"success": True, "data": {}}

        @tool(name=f"{prefix}_rename_thing", permission_category="things", permission_action="update")
        async def rename_thing(name: str, confirm: bool = False) -> dict:
            if not confirm:
                return {"success": True, "requires_confirmation": True, "preview": {"name": name}}
            events.append(f"rename:{name}:{'write' if gate.holds_write() else 'read'}")
            return {"success": True, "data": {"name": name}}

    def register_meta(self, *, start=None, cancel=None) -> None:
        store = self.store

        async def start_async_tool(executor, arguments, *, after=None):
            return {"jobId": await store.start(executor(**arguments), after=after)}

        register_meta_tools(
            server=self.server,
            tool_decorator=self.plain_tool,
            tool_index_handler=AsyncMock(return_value={"tools": []}),
            start_async_tool=start or start_async_tool,
            get_job_status=store.status,
            register_tool=Mock(),
            prefix=self.prefix,
            cancel_job=cancel or store.cancel,
        )

    async def hold_write(self) -> asyncio.Task:
        entered = asyncio.Event()

        async def hold() -> None:
            async with self.gate.write(label="holder"):
                entered.set()
                await self.release.wait()

        task = asyncio.create_task(hold())
        await entered.wait()
        return task


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _params(func):
    return inspect.signature(func).parameters


async def _with_confirm(name: str, confirm: bool = False): ...


async def _without_confirm(name: str): ...


@pytest.mark.parametrize(
    ("action", "func", "kwargs", "bypass", "expected"),
    [
        ("read", _with_confirm, {"confirm": True}, False, "read"),
        (None, _with_confirm, {"confirm": True}, False, "read"),
        ("update", _with_confirm, {"confirm": True}, False, "write"),
        ("update", _with_confirm, {"confirm": False}, False, "read"),
        ("update", _with_confirm, {}, False, "read"),
        ("update", _with_confirm, {}, True, "write"),
        ("update", _with_confirm, {"confirm": False}, True, "read"),
        ("create", _without_confirm, {}, False, "write"),
        ("DELETE", _with_confirm, {"confirm": True}, False, "write"),
    ],
)
def test_classification_follows_the_declared_action_and_the_resolved_confirm(action, func, kwargs, bypass, expected):
    classify = make_call_classifier(action=action, parameters=_params(func), bypass_mode=lambda: bypass)
    assert classify(kwargs) == expected


def test_a_call_the_policy_gate_will_deny_takes_no_gate():
    classify = make_call_classifier(
        action="update", parameters=_params(_with_confirm), bypass_mode=lambda: False, policy_allows=lambda: False
    )
    assert classify({"confirm": True}) is None


# ---------------------------------------------------------------------------
# The wrapper on the registration paths
# ---------------------------------------------------------------------------


async def test_writes_hold_the_write_turn_and_previews_and_reads_take_a_read_slot():
    harness = Harness()
    call = harness.server.call_tool

    assert _payload(await call("unifi_update_thing", {"name": "a", "confirm": True}))["data"]["mode"] == "write"
    assert _payload(await call("unifi_update_thing", {"name": "b"}))["data"]["mode"] == "read:1"
    await call("unifi_create_thing", {"name": "c"})
    await call("unifi_list_things", {})
    await call("unifi_get_status", {})  # the read-only fast path

    assert harness.events == [
        "update:a:True:write",
        "update:b:False:read:1",
        "create:c:write",
        "list:1:False",
        "status:1",
    ]
    counters = harness.gate.snapshot()["counters"]
    assert counters["writes_granted"] == 2
    assert counters["reads_started"] == 3


async def test_bypass_mode_classifies_an_omitted_confirm_as_a_write(monkeypatch):
    monkeypatch.setenv("UNIFI_TEST_TOOL_PERMISSION_MODE", "bypass")
    registered = {}

    def capture(*d_args, **d_kwargs):
        def register(func):
            registered[d_kwargs["name"]] = func
            return func

        return register

    gate = OperationGate(GateSettings(), name="network")
    events: list[str] = []
    tool = create_permissioned_tool(
        original_tool_decorator=capture,
        policy_gate_checker=PolicyGateChecker(server_prefix="test"),
        server_prefix="TEST",
        register_tool_fn=Mock(),
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda func, name: func,
        logger=LOGGER,
        gate_provider=lambda: gate,
    )

    @tool(name="unifi_update_thing", permission_category="things", permission_action="update")
    async def update_thing(name: str, confirm: bool = False) -> dict:
        events.append(f"{confirm}:{gate.holds_write()}")
        return {"success": True}

    # A caller that omits confirm: bypass mode injects confirm=True, so the call is a write.
    await registered["unifi_update_thing"](name="a")
    assert events == ["True:True"]


async def test_redeeming_a_preview_token_runs_under_the_write_turn(monkeypatch):
    monkeypatch.setenv("UNIFI_TEST_REQUIRE_PREVIEW_TOKEN", "true")
    harness = Harness()
    call = harness.server.call_tool

    preview = _payload(await call("unifi_rename_thing", {"name": "a"}))
    token = preview["preview_token"]
    counters = harness.gate.snapshot()["counters"]
    assert counters["writes_granted"] == 0 and counters["reads_started"] == 1

    executed = _payload(await call("unifi_rename_thing", {"name": "a", "confirm": True, "preview_token": token}))
    assert executed["success"] is True
    assert harness.events == ["rename:a:write"]
    assert harness.gate.snapshot()["counters"]["writes_granted"] == 1


async def test_the_gate_sits_outside_the_connection_wait():
    order: list[str] = []
    gate = OperationGate(GateSettings(), name="network")

    def reconnecting(tool_decorator):
        def tool(*d_args, **d_kwargs):
            register = tool_decorator(*d_args, **d_kwargs)

            def decorator(func):
                @wraps(func)
                async def connected(*args, **kwargs):
                    order.append(f"connect:{'held' if gate.holds_write() else 'free'}")
                    return await func(*args, **kwargs)

                register(connected)
                return func

            return decorator

        return tool

    harness = Harness(gate=gate, connection_decorator=reconnecting)
    await harness.server.call_tool("unifi_update_thing", {"name": "a", "confirm": True})
    await harness.server.call_tool("unifi_get_status", {})
    assert order == ["connect:held", "connect:free"]
    assert harness.events[0] == "update:a:True:write"


async def test_a_write_waits_its_turn_while_meta_tools_and_reads_do_not():
    harness = Harness()
    harness.register_meta()
    call = harness.server.call_tool
    holder = await harness.hold_write()

    # Meta tools and reads answer while the write turn is held.
    for name, arguments in (
        ("unifi_tool_index", {}),
        ("unifi_batch_status", {"jobId": "missing"}),
        ("unifi_batch_cancel", {"jobId": "missing"}),
        ("unifi_execute", {"tool": "unifi_list_things", "arguments": {}}),
        ("unifi_get_status", {}),
    ):
        await asyncio.wait_for(call(name, arguments), timeout=1)

    # A write through *_execute queues for the gate inside the domain tool.
    pending = asyncio.create_task(
        call("unifi_execute", {"tool": "unifi_update_thing", "arguments": {"name": "w", "confirm": True}})
    )
    await settle()
    assert not pending.done()
    assert harness.gate.queue_depth == 1

    harness.release.set()
    await holder
    assert _payload(await pending)["data"]["mode"] == "write"


async def test_a_denied_write_takes_no_gate(monkeypatch):
    monkeypatch.setenv("UNIFI_POLICY_TEST_UPDATE", "false")
    harness = Harness()
    holder = await harness.hold_write()
    result = await asyncio.wait_for(
        harness.server.call_tool("unifi_update_thing", {"name": "a", "confirm": True}), timeout=1
    )
    assert _payload(result)["success"] is False
    assert harness.gate.queue_depth == 0
    harness.release.set()
    await holder


# ---------------------------------------------------------------------------
# Direct calls: wait budget and busy
# ---------------------------------------------------------------------------


async def test_a_direct_write_gives_up_after_the_wait_budget_without_running():
    clock = FakeClock()
    gate = OperationGate(GateSettings(direct_call_wait_seconds=5), name="network", clock=clock)
    harness = Harness(gate=gate)
    holder = await harness.hold_write()

    pending = asyncio.create_task(harness.server.call_tool("unifi_update_thing", {"name": "a", "confirm": True}))
    await settle()
    await clock.advance(4)
    assert not pending.done()
    await clock.advance(1)
    payload = _payload(await pending)
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to run unifi_update_thing: The network controller is busy")
    assert "not sent" in payload["error"]
    assert harness.events == []

    harness.release.set()
    await holder


async def test_a_direct_call_is_refused_busy_when_the_holder_overruns():
    clock = FakeClock()
    gate = OperationGate(
        GateSettings(hold_budget_seconds=10, direct_call_wait_seconds=3_000), name="network", clock=clock
    )
    harness = Harness(gate=gate)
    holder = await harness.hold_write()
    pending = asyncio.create_task(harness.server.call_tool("unifi_create_thing", {"name": "a"}))
    await settle()
    await clock.advance(12)
    payload = _payload(await pending)
    assert payload["success"] is False and "past its 10s budget" in payload["error"]
    harness.release.set()
    await holder


async def test_a_batch_job_waits_without_a_wait_budget():
    clock = FakeClock()
    gate = OperationGate(
        GateSettings(hold_budget_seconds=1_000, direct_call_wait_seconds=5), name="network", clock=clock
    )
    harness = Harness(gate=gate)
    harness.register_meta()
    holder = await harness.hold_write()

    batch = _payload(
        await harness.server.call_tool(
            "unifi_batch", {"operations": [{"tool": "unifi_create_thing", "arguments": {"name": "a"}}]}
        )
    )
    job_id = batch["jobs"][0]["jobId"]
    await settle()
    await clock.advance(60)
    status = await harness.store.status(job_id)
    assert status["status"] == "queued" and status["position"] == 1

    harness.release.set()
    await holder
    await settle()
    assert (await harness.store.status(job_id))["status"] == "done"


async def test_cancellation_propagates_through_the_wrapper():
    harness = Harness()
    holder = await harness.hold_write()
    pending = asyncio.create_task(harness.server.call_tool("unifi_create_thing", {"name": "a"}))
    await settle()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert harness.gate.queue_depth == 0
    harness.release.set()
    await holder


# ---------------------------------------------------------------------------
# Batch: ordering and cancel
# ---------------------------------------------------------------------------


async def test_batch_writes_reach_the_gate_in_submission_order_across_a_slow_first_call():
    harness = Harness()
    harness.register_meta()
    gate = harness.gate
    original_call_tool = harness.server.call_tool
    loading = asyncio.Event()

    # The first operation's tool is still loading (as the lazy loader does,
    # before the tool runs), so later operations would overtake it unchained.
    async def lazy_call_tool(name, arguments, context=None):
        if arguments.get("name") == "first":
            await loading.wait()
        return await original_call_tool(name, arguments, context=context)

    harness.server.call_tool = lazy_call_tool
    holder = await harness.hold_write()

    operations = [
        {"tool": "unifi_update_thing", "arguments": {"name": name, "confirm": True}}
        for name in ("first", "second", "third")
    ]
    batch = _payload(await original_call_tool("unifi_batch", {"operations": operations}))
    job_ids = [job["jobId"] for job in batch["jobs"]]
    await settle()
    assert [(await harness.store.status(job_id))["status"] for job_id in job_ids] == ["running", "queued", "queued"]
    assert gate.queue_depth == 0  # nothing overtook the loading first job

    loading.set()
    await settle()
    assert gate.queue_depth == 3
    harness.release.set()
    await holder
    await settle()
    assert [event.split(":")[1] for event in harness.events] == ["first", "second", "third"]
    assert [(await harness.store.status(job_id))["status"] for job_id in job_ids] == ["done"] * 3


async def test_batch_cancel_withdraws_queued_jobs_and_refuses_running_ones():
    harness = Harness()
    harness.register_meta()
    call = harness.server.call_tool
    holder = await harness.hold_write()

    operations = [{"tool": "unifi_create_thing", "arguments": {"name": name}} for name in ("a", "b", "c")]
    job_ids = [job["jobId"] for job in _payload(await call("unifi_batch", {"operations": operations}))["jobs"]]
    await settle()

    cancelled = _payload(await call("unifi_batch_cancel", {"jobIds": [job_ids[1], "missing"]}))
    assert cancelled["jobs"][0] == {"jobId": job_ids[1], "cancelled": True, "status": "cancelled"}
    assert cancelled["jobs"][1]["cancelled"] is False and cancelled["jobs"][1]["status"] == "unknown"

    harness.release.set()
    await holder
    await settle()
    assert [event.split(":")[1] for event in harness.events] == ["a", "c"]
    status = _payload(await call("unifi_batch_status", {"jobId": job_ids[1]}))
    assert status["status"] == "cancelled"

    # A job already running is refused.
    release = asyncio.Event()

    @harness.server.tool(name="unifi_slow_change", permission_category="things", permission_action="create")
    async def slow_change() -> dict:
        await release.wait()
        return {"success": True}

    running = _payload(await call("unifi_batch", {"operations": [{"tool": "unifi_slow_change"}]}))["jobs"][0]["jobId"]
    await settle()
    refused = _payload(await call("unifi_batch_cancel", {"jobId": running}))
    assert refused["cancelled"] is False and refused["status"] == "running"
    assert "cannot be recalled" in refused["reason"]
    release.set()
    await settle()
    assert _payload(await call("unifi_batch_cancel", {}))["error"] == "Provide jobId or jobIds parameter"


async def test_a_legacy_job_starter_without_after_still_starts_every_job():
    harness = Harness()
    started: list[str] = []
    store = harness.store

    async def legacy_start(executor, arguments):
        job_id = await store.start(executor(**arguments))
        started.append(job_id)
        return {"jobId": job_id}

    harness.register_meta(start=legacy_start)
    operations = [{"tool": "unifi_create_thing", "arguments": {"name": name}} for name in ("a", "b")]
    payload = _payload(await harness.server.call_tool("unifi_batch", {"operations": operations}))
    assert [job["jobId"] for job in payload["jobs"]] == started
    await settle()
    assert sorted(harness.events) == ["create:a:write", "create:b:write"]


# ---------------------------------------------------------------------------
# Old apps and setup mode
# ---------------------------------------------------------------------------


async def test_an_app_that_passes_no_provider_behaves_as_before():
    order: list[str] = []
    server = FastMCP("legacy")

    def reconnecting(tool_decorator):
        def tool(*d_args, **d_kwargs):
            register = tool_decorator(*d_args, **d_kwargs)

            def decorator(func):
                @wraps(func)
                async def connected(*args, **kwargs):
                    order.append("connect")
                    return await func(*args, **kwargs)

                register(connected)
                return func

            return decorator

        return tool

    # The old wiring: the connection wait is pre-applied, and no gate provider is passed.
    tool = create_permissioned_tool(
        original_tool_decorator=reconnecting(server.tool),
        policy_gate_checker=PolicyGateChecker(server_prefix="test"),
        server_prefix="TEST",
        register_tool_fn=Mock(),
        diagnostics_enabled_fn=lambda: False,
        wrap_tool_fn=lambda func, name: func,
        logger=LOGGER,
    )
    concurrent = 0
    peak = 0

    @tool(name="unifi_create_thing", permission_category="things", permission_action="create")
    async def create_thing(name: str) -> dict:
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await settle(3)
        concurrent -= 1
        return {"success": True, "data": {"name": name}}

    results = await asyncio.gather(*(server.call_tool("unifi_create_thing", {"name": str(i)}) for i in range(3)))
    assert all(_payload(result)["success"] for result in results)
    assert order == ["connect"] * 3
    assert peak == 3  # no gate: concurrent writes run together, as they always did


async def test_a_provider_without_a_gate_runs_the_call_and_admits_it():
    harness = Harness()
    # Setup mode, or a server with no controller yet: the provider has no gate to give.
    harness.gate = None  # type: ignore[assignment]
    admitted: list[str] = []

    class Observer:
        def admitted(self):
            admitted.append("admitted")

        def queued(self, ticket):
            pass

        def granted(self, ticket):
            pass

    async with observing_operations(Observer()):
        payload = _payload(await harness.server.call_tool("unifi_create_thing", {"name": "setup"}))
    assert payload["success"] is True
    assert admitted == ["admitted"]


# ---------------------------------------------------------------------------
# Status schema and task mapping
# ---------------------------------------------------------------------------


def test_batch_status_and_cancel_schemas_carry_the_new_states():
    registered = {}

    def register_tool(**kwargs):
        registered[kwargs["name"]] = kwargs

    def plain(*d_args, **d_kwargs):
        return lambda func: func

    register_meta_tools(
        server=SimpleNamespace(),
        tool_decorator=plain,
        tool_index_handler=AsyncMock(),
        start_async_tool=AsyncMock(),
        get_job_status=AsyncMock(),
        register_tool=register_tool,
        prefix="protect",
    )
    status = registered["protect_batch_status"]["output_schema"]["properties"]
    assert set(status["status"]["enum"]) == {"queued", "running", "done", "error", "cancelled", "unknown"}
    assert status["position"]["type"] == ["integer", "null"]
    cancel = registered["protect_batch_cancel"]
    assert set(cancel["input_schema"]["properties"]) == {"jobId", "jobIds"}
    assert cancel["annotations"]["readOnlyHint"] is False
    batch = registered["protect_batch"]["description"]
    assert "Writes execute one at a time in submission order; reads run concurrently, up to a cap." in batch
    assert "Queued jobs can be cancelled." in batch
    assert tuple(status["status"]["enum"]) == BATCH_JOB_STATUSES


@pytest.mark.parametrize(
    ("job_status", "task_status"),
    [("queued", "working"), ("running", "working"), ("cancelled", "cancelled"), ("done", "completed")],
)
def test_task_mapping_covers_queued_and_cancelled(job_status, task_status):
    task = task_from_job_status("job", {"status": job_status, "started": 1.0})
    assert task.status == task_status
    if job_status == "queued":
        assert "queued" in task.status_message


# ---------------------------------------------------------------------------
# Settings from the environment
# ---------------------------------------------------------------------------


_GATE_VARIABLES = (
    "UNIFI_WRITE_HOLD_SECONDS",
    "UNIFI_CALL_WAIT_SECONDS",
    "UNIFI_READ_CONCURRENCY",
    "UNIFI_NETWORK_WRITE_HOLD_SECONDS",
    "UNIFI_NETWORK_CALL_WAIT_SECONDS",
    "UNIFI_NETWORK_READ_CONCURRENCY",
)


@pytest.fixture
def clean_gate_env(monkeypatch):
    for name in _GATE_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_settings_default_when_nothing_is_set(clean_gate_env):
    assert gate_settings_from_env("NETWORK", logger=LOGGER) == GateSettings()


def test_server_level_settings_win_over_shared_ones(clean_gate_env):
    clean_gate_env.setenv("UNIFI_WRITE_HOLD_SECONDS", "200")
    clean_gate_env.setenv("UNIFI_NETWORK_WRITE_HOLD_SECONDS", "90.5")
    clean_gate_env.setenv("UNIFI_CALL_WAIT_SECONDS", "20")
    clean_gate_env.setenv("UNIFI_NETWORK_CALL_WAIT_SECONDS", "")  # empty counts as unset
    clean_gate_env.setenv("UNIFI_NETWORK_READ_CONCURRENCY", " 4 ")
    assert gate_settings_from_env("NETWORK", logger=LOGGER) == GateSettings(
        hold_budget_seconds=90.5, direct_call_wait_seconds=20, read_cap=4
    )


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("UNIFI_NETWORK_WRITE_HOLD_SECONDS", "soon"),
        ("UNIFI_NETWORK_WRITE_HOLD_SECONDS", "5"),
        ("UNIFI_WRITE_HOLD_SECONDS", "nan"),
        ("UNIFI_NETWORK_CALL_WAIT_SECONDS", "0"),
        ("UNIFI_CALL_WAIT_SECONDS", "inf"),
        ("UNIFI_NETWORK_READ_CONCURRENCY", "2.5"),
        ("UNIFI_READ_CONCURRENCY", "0"),
        ("UNIFI_NETWORK_READ_CONCURRENCY", "65"),
        ("UNIFI_NETWORK_READ_CONCURRENCY", "-1"),
    ],
)
def test_invalid_settings_refuse_startup_naming_the_variable(clean_gate_env, caplog, variable, value):
    clean_gate_env.setenv(variable, value)
    with caplog.at_level(logging.ERROR, logger=LOGGER.name):
        with pytest.raises(SystemExit) as refused:
            gate_settings_from_env("NETWORK", logger=LOGGER)
    assert refused.value.code == EXIT_GATE_SETTINGS_INVALID
    assert variable in caplog.text


@pytest.mark.parametrize("value", ["²", "٣", "1²"])
def test_non_ascii_digits_refuse_startup_instead_of_crashing(clean_gate_env, caplog, value):
    clean_gate_env.setenv("UNIFI_NETWORK_READ_CONCURRENCY", value)
    with pytest.raises(SystemExit) as refused:
        gate_settings_from_env("NETWORK", logger=LOGGER)
    assert refused.value.code == EXIT_GATE_SETTINGS_INVALID


def test_a_lowercase_prefix_still_reads_the_server_level_variable(clean_gate_env):
    clean_gate_env.setenv("UNIFI_READ_CONCURRENCY", "2")
    clean_gate_env.setenv("UNIFI_NETWORK_READ_CONCURRENCY", "5")
    assert gate_settings_from_env("network", logger=LOGGER).read_cap == 5


async def test_a_busy_refusal_of_a_confirmed_write_says_nothing_was_applied():
    clock = FakeClock()
    gate = OperationGate(GateSettings(direct_call_wait_seconds=1, read_cap=1), name="network", clock=clock)
    harness = Harness(gate=gate)
    holder = await harness.hold_write()
    write = asyncio.create_task(harness.server.call_tool("unifi_update_thing", {"name": "a", "confirm": True}))
    await settle()
    await clock.advance(1)
    refused = await write
    assert _payload(refused)["mutation_applied"] is False
    assert refused.structured_content["mutation_applied"] is False
    harness.release.set()
    await holder

    # A read refused as busy carries no mutation outcome.
    slot_free = asyncio.Event()

    async def fill_the_read_slot() -> None:
        async with gate.read():
            await slot_free.wait()

    filler = asyncio.create_task(fill_the_read_slot())
    await settle()
    read = asyncio.create_task(harness.server.call_tool("unifi_list_things", {}))
    await settle()
    await clock.advance(1)
    read_refusal = _payload(await read)
    assert read_refusal["success"] is False and "mutation_applied" not in read_refusal
    slot_free.set()
    await filler


# ---------------------------------------------------------------------------
# A write cut off at its hold budget
# ---------------------------------------------------------------------------

CUT_OFF_BUDGET = 10.0
UNKNOWN_GUIDANCE = "The change may or may not have been applied; read the resource back before retrying."


def _cut_off_harness():
    """A harness whose writes reach the controller through the hold-budget bound, like the apps' managers."""
    clock = FakeClock()
    gate = OperationGate(GateSettings(hold_budget_seconds=CUT_OFF_BUDGET), name="network", clock=clock)
    harness = Harness(gate=gate)

    async def send(*, sent_first: bool = False, budget_left: float) -> None:
        """One bounded controller request, made when ``budget_left`` seconds of the hold remain."""
        if sent_first:
            async with write_request_bound():
                pass
        clock.value += CUT_OFF_BUDGET - budget_left
        async with write_request_bound():
            await asyncio.sleep(1)  # a controller that does not answer

    return harness, send


@pytest.mark.parametrize(
    ("sent_first", "budget_left", "expected"),
    [
        (False, 0.005, None),  # sent, then cut off: the outcome is unknown
        (False, -1.0, False),  # refused before anything was sent
        (True, -1.0, None),  # refused, but an earlier request of the write went out
    ],
)
async def test_a_tool_that_catches_the_cut_off_reports_its_outcome(sent_first, budget_left, expected):
    harness, send = _cut_off_harness()

    @harness.server.tool(name="unifi_delete_thing", permission_category="things", permission_action="delete")
    async def delete_thing(confirm: bool = False) -> dict:
        try:
            await send(sent_first=sent_first, budget_left=budget_left)
        except Exception as exc:  # noqa: BLE001 - tools catch everything
            return {"success": False, "error": f"Failed to delete thing: {exc}"}
        return {"success": True}

    result = await harness.server.call_tool("unifi_delete_thing", {"confirm": True})
    payload = _payload(result)
    assert payload["success"] is False
    assert payload["mutation_applied"] is expected
    assert result.structured_content["mutation_applied"] is expected
    assert payload["error"].startswith("Failed to delete thing: The ")
    # The fixed guidance appears once: the tool's message already carried it.
    guidance = UNKNOWN_GUIDANCE if expected is None else "the controller request was not sent"
    assert payload["error"].count(guidance) == 1
    assert not harness.gate.write_held


async def test_a_tool_error_without_the_guidance_gets_it_appended():
    harness, send = _cut_off_harness()

    @harness.server.tool(name="unifi_delete_thing", permission_category="things", permission_action="delete")
    async def delete_thing(confirm: bool = False) -> dict:
        try:
            await send(budget_left=0.005)
        except Exception:  # noqa: BLE001 - a manager that reports failure as False
            return {"success": False, "error": "Failed to delete thing."}
        return {"success": True}

    payload = _payload(await harness.server.call_tool("unifi_delete_thing", {"confirm": True}))
    assert payload == {
        "success": False,
        "error": "Failed to delete thing. The controller did not answer within the write's time budget. "
        + UNKNOWN_GUIDANCE,
        "mutation_applied": None,
    }


@pytest.mark.parametrize(("budget_left", "expected"), [(0.005, None), (-1.0, False)])
async def test_a_cut_off_that_escapes_the_tool_becomes_the_error_contract(budget_left, expected):
    harness, send = _cut_off_harness()

    @harness.server.tool(name="unifi_delete_thing", permission_category="things", permission_action="delete")
    async def delete_thing(confirm: bool = False) -> dict:
        await send(budget_left=budget_left)
        return {"success": True}

    payload = _payload(await harness.server.call_tool("unifi_delete_thing", {"confirm": True}))
    assert payload["success"] is False
    assert payload["error"].startswith("Failed to run unifi_delete_thing: The ")
    assert payload["mutation_applied"] is expected


async def test_a_tool_that_reports_its_own_outcome_is_left_as_it_is():
    harness, send = _cut_off_harness()

    @harness.server.tool(name="unifi_delete_thing", permission_category="things", permission_action="delete")
    async def delete_thing(confirm: bool = False) -> dict:
        try:
            await send(sent_first=True, budget_left=-1.0)
        except Exception:  # noqa: BLE001 - the delete went out; only the read-back was refused
            return {"success": False, "error": "Deleted, but the read-back failed", "mutation_applied": True}
        return {"success": True}

    payload = _payload(await harness.server.call_tool("unifi_delete_thing", {"confirm": True}))
    assert payload == {"success": False, "error": "Deleted, but the read-back failed", "mutation_applied": True}


async def test_a_failed_write_that_was_not_cut_off_is_unchanged():
    harness, _send = _cut_off_harness()

    @harness.server.tool(name="unifi_delete_thing", permission_category="things", permission_action="delete")
    async def delete_thing(confirm: bool = False) -> dict:
        async with write_request_bound():
            pass
        return {"success": False, "error": "Failed to delete thing: controller answered 400"}

    @harness.server.tool(name="unifi_remove_thing", permission_category="things", permission_action="delete")
    async def remove_thing(confirm: bool = False) -> dict:
        raise RuntimeError("not a cut-off")

    payload = _payload(await harness.server.call_tool("unifi_delete_thing", {"confirm": True}))
    assert payload == {"success": False, "error": "Failed to delete thing: controller answered 400"}
    # Any other exception propagates as before.
    with pytest.raises(Exception, match="unifi_remove_thing") as raised:
        await harness.server.call_tool("unifi_remove_thing", {"confirm": True})
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert not harness.gate.write_held


# ---------------------------------------------------------------------------
# Admission without a gate, and operations that never reach a tool wrapper
# ---------------------------------------------------------------------------


def _main_style_reconnect(order: list[str]):
    """The connection wait as main's apps apply it: pre-wrapped around the raw decorator."""

    def reconnecting(tool_decorator):
        def tool(*d_args, **d_kwargs):
            register = tool_decorator(*d_args, **d_kwargs)

            def decorator(func):
                @wraps(func)
                async def connected(*args, **kwargs):
                    order.append("connect")
                    return await func(*args, **kwargs)

                register(connected)
                return func

            return decorator

        return tool

    return reconnecting


async def test_a_batch_on_an_app_without_a_gate_provider_still_runs_side_by_side():
    order: list[str] = []
    # Built exactly as main's apps build it today: no gate provider, no connection_decorator.
    harness = Harness(provider=False, legacy_original=_main_style_reconnect(order))
    harness.register_meta()
    slow = asyncio.Event()

    @harness.server.tool(name="unifi_slow_read", annotations={"readOnlyHint": True})
    async def slow_read() -> dict:
        await slow.wait()
        return {"success": True, "data": "slow"}

    operations = [
        {"tool": "unifi_slow_read"},
        {"tool": "unifi_get_status"},
        {"tool": "unifi_create_thing", "arguments": {"name": "w"}},
        {"tool": "unifi_list_things"},
    ]
    payload = _payload(await harness.server.call_tool("unifi_batch", {"operations": operations}))
    job_ids = [job["jobId"] for job in payload["jobs"]]
    await settle()

    statuses = [(await harness.store.status(job_id))["status"] for job_id in job_ids]
    assert statuses == ["running", "done", "done", "done"]
    assert order == ["connect"] * 4
    slow.set()
    await settle()
    assert (await harness.store.status(job_ids[0]))["status"] == "done"


@pytest.mark.parametrize("provider", [True, False])
async def test_operations_that_fail_before_any_tool_wrapper_do_not_stall_the_batch(tmp_path, monkeypatch, provider):
    from unifi_mcp_shared.strict_dispatch import StrictKwargFastMCP

    monkeypatch.setenv("UNIFI_POLICY_TEST_UPDATE", "false")
    manifest = tmp_path / "tools_manifest.json"
    manifest.write_text(
        json.dumps({"tools": [{"name": "unifi_create_thing", "schema": {"input": {"properties": {"name": {}}}}}]})
    )
    server = StrictKwargFastMCP("strict-gate-test", tools_manifest_path=manifest)
    harness = Harness(provider=provider, server=server)
    harness.register_meta()

    operations = [
        {"tool": "unifi_no_such_tool"},  # unknown tool
        {"tool": "unifi_create_thing", "arguments": {"name": "x", "typo": 1}},  # strict-dispatch rejection
        {"tool": "unifi_update_thing", "arguments": {"name": "denied", "confirm": True}},  # policy denial
        {"tool": "unifi_execute", "arguments": {"tool": "unifi_get_status", "arguments": {}}},  # execute
        {"tool": "unifi_batch_status", "arguments": {"jobId": "missing"}},  # a meta tool
        {"tool": "unifi_create_thing", "arguments": {"name": "last"}},
    ]
    payload = _payload(await harness.server.call_tool("unifi_batch", {"operations": operations}))
    job_ids = [job["jobId"] for job in payload["jobs"]]
    await settle(80)

    statuses = [(await harness.store.status(job_id))["status"] for job_id in job_ids]
    assert statuses == ["error", "error", "done", "done", "done", "done"]
    assert "create:last:" + ("write" if provider else "read") in harness.events


async def test_execute_in_a_batch_is_admitted_by_its_inner_tool():
    harness = Harness()
    harness.register_meta()
    holder = await harness.hold_write()
    operations = [
        {
            "tool": "unifi_execute",
            "arguments": {"tool": "unifi_update_thing", "arguments": {"name": "a", "confirm": True}},
        },
        {"tool": "unifi_create_thing", "arguments": {"name": "b"}},
    ]
    job_ids = [
        job["jobId"]
        for job in _payload(await harness.server.call_tool("unifi_batch", {"operations": operations}))["jobs"]
    ]
    await settle()
    # The execute job joined the queue through its inner write, so the next job started and queued behind it.
    assert [(await harness.store.status(job_id))["position"] for job_id in job_ids] == [1, 2]
    harness.release.set()
    await holder
    await settle()
    assert [event.split(":")[1] for event in harness.events] == ["a", "b"]
