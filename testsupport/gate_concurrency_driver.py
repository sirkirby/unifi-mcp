"""Drive one MCP app's real tool dispatch against a fake controller, for operation-gate tests.

Test-only; no package ships it. Run in a fresh process (``python -c "import
gate_concurrency_driver as d; d.main('network')"``) so the app's main module
installs its real wiring before the tool module registers: the tools are then
reached exactly as an MCP client reaches them, through ``server.call_tool``,
the operation gate, the connection wait, the policy check and the tool body.
The controller is faked at the manager boundary: each write records when it
starts and ends, and each read how many reads overlap.

Prints one JSON object with what happened; the calling test asserts on it.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from typing import Any

SPECS: dict[str, dict[str, Any]] = {
    "network": {
        "package": "unifi_network_mcp",
        "prefix": "unifi",
        "tool_module": "unifi_network_mcp.tools.clients",
        "manager": "client_manager",
        "write_tool": "unifi_rename_client",
        "write_method": "rename_client",
        "write_args": lambda i: {"mac_address": f"02:00:00:00:00:{i:02x}", "name": f"client-{i}", "confirm": True},
        "write_key": lambda args, kwargs: args[0],
        "read_tool": "unifi_get_client_details",
        "read_method": "get_client_details",
        "read_args": lambda i: {"mac_address": f"02:00:00:00:01:{i:02x}"},
        "read_result": lambda *args, **kwargs: {"mac": args[0], "name": "fake", "hostname": "fake"},
        "write_result": True,
        "extra": {"get_client_details": lambda *args, **kwargs: {"mac": args[0], "name": "fake"}},
    },
    "protect": {
        "package": "unifi_protect_mcp",
        "prefix": "protect",
        "tool_module": "unifi_protect_mcp.tools.devices",
        "manager": "light_manager",
        "write_tool": "protect_update_light",
        "write_method": "apply_light_settings",
        "write_args": lambda i: {"light_id": f"light-{i}", "settings": {"name": f"light-{i}"}, "confirm": True},
        "write_key": lambda args, kwargs: args[0],
        "read_tool": "protect_list_lights",
        "read_method": "list_lights",
        "read_args": lambda i: {},
        "read_result": lambda *args, **kwargs: [],
        "write_result": {"applied": True},
        "extra": {
            "update_light": lambda light_id, settings: {
                "current_state": {},
                "proposed_changes": settings,
                "light_name": light_id,
            }
        },
    },
    "access": {
        "package": "unifi_access_mcp",
        "prefix": "access",
        "tool_module": "unifi_access_mcp.tools.doors",
        "manager": "door_manager",
        "write_tool": "access_lock_door",
        "write_method": "apply_lock_door",
        "write_args": lambda i: {"door_id": f"door-{i}", "confirm": True},
        "write_key": lambda args, kwargs: args[0],
        "read_tool": "access_list_doors",
        "read_method": "list_doors",
        "read_args": lambda i: {},
        "read_result": lambda *args, **kwargs: [],
        "write_result": {"locked": True},
        "extra": {},
    },
}

READ_CAP = 3


def _payload(result: Any) -> dict:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    return json.loads(result.content[0].text)


async def _run(product: str) -> dict:
    spec = SPECS[product]
    main = importlib.import_module(f"{spec['package']}.main")
    runtime = importlib.import_module(f"{spec['package']}.runtime")
    importlib.import_module(spec["tool_module"])  # registers through the real wiring

    from unifi_core.operation_gate import GateKey, GateSettings, gate_registry
    from unifi_mcp_shared.meta_tools import register_meta_tools

    connection_manager = runtime.connection_manager
    connection_manager.host = "controller.test"
    connection_manager.port = 443

    async def connected() -> bool:
        return True

    connection_manager.ensure_connected = connected
    gate_registry().get(GateKey.for_host("controller.test", 443, product), GateSettings(read_cap=READ_CAP))

    manager = getattr(runtime, spec["manager"])
    state = {"writes": 0, "write_overlap": False, "reads": 0, "read_peak": 0}
    writes: list[str] = []
    hold = {"event": None}

    async def fake_write(*args: Any, **kwargs: Any) -> Any:
        state["writes"] += 1
        if state["writes"] > 1:
            state["write_overlap"] = True
        writes.append(spec["write_key"](args, kwargs))
        if hold["event"] is not None:
            await hold["event"].wait()
        for _ in range(3):
            await asyncio.sleep(0)
        state["writes"] -= 1
        return spec["write_result"]

    async def fake_read(*args: Any, **kwargs: Any) -> Any:
        state["reads"] += 1
        state["read_peak"] = max(state["read_peak"], state["reads"])
        await asyncio.sleep(0.02)
        state["reads"] -= 1
        return spec["read_result"](*args, **kwargs)

    for name, fake in spec["extra"].items():

        async def fake_extra(*args: Any, _fake=fake, **kwargs: Any) -> Any:
            return _fake(*args, **kwargs)

        setattr(manager, name, fake_extra)
    setattr(manager, spec["write_method"], fake_write)
    setattr(manager, spec["read_method"], fake_read)

    register_meta_tools(
        server=main.server,
        tool_decorator=main._original_tool_decorator,
        tool_index_handler=main.tool_index_handler,
        start_async_tool=main.start_async_tool,
        get_job_status=main.get_job_status,
        register_tool=main.register_tool,
        prefix=spec["prefix"],
    )
    call = main.server.call_tool
    prefix = spec["prefix"]
    report: dict[str, Any] = {}

    # 1. Concurrent confirmed writes: never overlap, run in submission order.
    results = await asyncio.gather(*(call(spec["write_tool"], spec["write_args"](i)) for i in range(6)))
    report["direct_writes"] = {
        "order": list(writes),
        "expected": [list(spec["write_args"](i).values())[0] for i in range(6)],
        "overlap": state["write_overlap"],
        "success": [_payload(result).get("success") for result in results],
    }

    # 2. Concurrent reads: run side by side, up to the cap.
    results = await asyncio.gather(*(call(spec["read_tool"], spec["read_args"](i)) for i in range(7)))
    report["reads"] = {"peak": state["read_peak"], "success": [_payload(result).get("success") for result in results]}

    # 3. A batch of writes runs in submission order.
    writes.clear()
    operations = [{"tool": spec["write_tool"], "arguments": spec["write_args"](i)} for i in range(10, 15)]
    batch = _payload(await call(f"{prefix}_batch", {"operations": operations}))
    job_ids = [job["jobId"] for job in batch["jobs"]]
    for _ in range(400):
        statuses = [(await main.get_job_status(job_id))["status"] for job_id in job_ids]
        if all(status in ("done", "error", "cancelled") for status in statuses):
            break
        await asyncio.sleep(0.005)
    report["batch"] = {
        "order": list(writes),
        "expected": [list(spec["write_args"](i).values())[0] for i in range(10, 15)],
        "statuses": statuses,
        "overlap": state["write_overlap"],
    }

    # 4. Batch cancel withdraws queued writes; nothing is sent for them.
    writes.clear()
    hold["event"] = asyncio.Event()
    operations = [{"tool": spec["write_tool"], "arguments": spec["write_args"](i)} for i in range(20, 23)]
    batch = _payload(await call(f"{prefix}_batch", {"operations": operations}))
    job_ids = [job["jobId"] for job in batch["jobs"]]
    for _ in range(200):
        if len(writes) == 1 and (await main.get_job_status(job_ids[1]))["status"] == "queued":
            break
        await asyncio.sleep(0.005)
    cancelled = _payload(await call(f"{prefix}_batch_cancel", {"jobIds": [job_ids[1]]}))
    refused = _payload(await call(f"{prefix}_batch_cancel", {"jobId": job_ids[0]}))
    hold["event"].set()
    hold["event"] = None
    for _ in range(400):
        statuses = [(await main.get_job_status(job_id))["status"] for job_id in job_ids]
        if all(status in ("done", "error", "cancelled") for status in statuses):
            break
        await asyncio.sleep(0.005)
    report["cancel"] = {
        "order": list(writes),
        "expected": [list(spec["write_args"](i).values())[0] for i in (20, 22)],
        "statuses": statuses,
        "cancelled": cancelled["jobs"][0]["cancelled"],
        "running_refused": refused["cancelled"] is False and refused["status"] == "running",
    }
    return report


def main(product: str) -> None:
    print("GATE-REPORT " + json.dumps(asyncio.run(_run(product))))


def run_in_subprocess(product: str, *, cwd: str) -> dict:
    """Run :func:`main` for ``product`` in a fresh interpreter and return its report."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    env = {k: v for k, v in os.environ.items() if not k.startswith("UNIFI_") and k != "CONFIG_PATH"}
    here = str(Path(__file__).resolve().parent)
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [here, env.get("PYTHONPATH", "")]))
    completed = subprocess.run(
        [sys.executable, "-c", f"import gate_concurrency_driver as d; d.main({product!r})"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = [line for line in completed.stdout.splitlines() if line.startswith("GATE-REPORT ")]
    assert completed.returncode == 0 and lines, completed.stderr[-4000:]
    return json.loads(lines[-1][len("GATE-REPORT ") :])
