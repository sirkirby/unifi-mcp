"""The support bundle summarises the operation gate; a backup restore has its own time limit."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from unifi_core.operation_gate import GateSettings, OperationGate, WriteRequestTimeout, write_request_bound
from unifi_core.support_bundle import (
    AttemptStatus,
    ConnectionSection,
    CountBucket,
    NetworkCapabilities,
    OperationGateSummary,
    SafeConnectionAttempt,
    operation_gate_summary,
)


async def test_restore_has_its_own_explicit_limit() -> None:
    from unifi_core.network.managers.system_manager import RESTORE_TIMEOUT_SECONDS, SystemManager

    seen: dict = {}
    response = MagicMock()
    response.status = 200
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)

    def post(url, *, data, timeout):
        seen["timeout"] = timeout
        return response

    connection = MagicMock()
    connection.ensure_connected = AsyncMock(return_value=True)
    connection.controller.session.post = post
    connection.url_base = "https://controller.example"
    connection.site = "default"
    manager = SystemManager(connection)

    assert await manager.restore_backup(b"backup") is True
    # Ten minutes, replacing the session's five-minute default.
    assert RESTORE_TIMEOUT_SECONDS == 600
    assert seen["timeout"] == aiohttp.ClientTimeout(total=RESTORE_TIMEOUT_SECONDS)


async def test_a_write_request_refused_before_sending_says_it_was_not_sent() -> None:
    clock_value = [0.0]

    class Clock:
        def now(self) -> float:
            return clock_value[0]

        async def sleep(self, seconds: float) -> None:  # pragma: no cover - never waits here
            raise AssertionError

    gate = OperationGate(GateSettings(hold_budget_seconds=10), name="network", clock=Clock())
    async with gate.write():
        clock_value[0] = 11
        with pytest.raises(WriteRequestTimeout) as refused:
            async with write_request_bound():
                raise AssertionError("nothing may be sent")
    assert refused.value.request_sent is False
    assert WriteRequestTimeout("cut off").request_sent is True


async def test_the_support_summary_holds_only_flags_and_bucketed_counts() -> None:
    gate = OperationGate(GateSettings(read_cap=4), name="network (controller-identity)")
    for _ in range(3):
        async with gate.write(label="unifi_update_secret_named_thing"):
            pass
    async with gate.read():
        summary = operation_gate_summary(gate.snapshot())

    assert summary == OperationGateSummary(
        write_held=False,
        holder_over_budget=False,
        queue_depth=CountBucket.ZERO,
        reads_in_use=1,
        read_cap=4,
        hold_budget_seconds=120,
        writes_completed=CountBucket.TWO_TO_FIVE,
        writes_refused_busy=CountBucket.ZERO,
        writes_withdrawn=CountBucket.ZERO,
        holds_over_budget=CountBucket.ZERO,
        reads_refused_busy=CountBucket.ZERO,
    )
    dumped = json.dumps(summary.model_dump(mode="json"))
    assert "controller-identity" not in dumped and "secret_named" not in dumped

    section = ConnectionSection(
        initialized=True,
        connected=True,
        tls_verification_enabled=True,
        last_attempt=SafeConnectionAttempt(status=AttemptStatus.SUCCEEDED),
        capabilities=NetworkCapabilities(
            session_available=True,
            integration_api_key_configured=False,
            controller_type="direct",
            reconnect_circuit="closed",
        ),
        operation_gate=summary,
    )
    assert section.operation_gate == summary
    with pytest.raises(ValueError):
        OperationGateSummary.model_validate({**summary.model_dump(), "holder_label": "unifi_update_wlan"})


def test_a_malformed_snapshot_is_clamped_not_trusted() -> None:
    summary = operation_gate_summary({"write_held": "yes", "reads_in_use": 10_000, "read_cap": 0, "counters": None})
    assert summary.write_held is False
    assert summary.reads_in_use == 256
    assert summary.read_cap == 1
    assert summary.writes_completed is CountBucket.ZERO
