"""The incident evidence tool waits for the controller connection like every domain tool.

A call made while the server's background connect is still running waits for
it only within the bound, then fails with the standard "still connecting"
error instead of evidence. The collector never runs, so no request is sent and
no budget is counted. The controller is a loopback port that accepts and never
answers.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from unittest.mock import AsyncMock

import pytest
from fake_controller import FAKE_PASSWORD, FAKE_USERNAME, SilentPort

from unifi_core.protect.managers import connection_manager as pcm
from unifi_protect_mcp.reconnect import reconnecting_tool_decorator
from unifi_protect_mcp.tools import incident_evidence

pytestmark = pytest.mark.real_reconnect

WAIT_SECONDS = 0.5
WINDOW = {"start": "2026-08-08T12:00:00Z", "end": "2026-08-08T13:00:00Z"}


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    policy = pcm.RetryPolicy
    monkeypatch.setattr(pcm, "RetryPolicy", lambda **kw: policy(**{**kw, "base_delay": 0.0, "max_delay": 0.0}))


async def _call_evidence(cm: pcm.ProtectConnectionManager) -> dict:
    """Call ``protect_get_incident_evidence`` the way the server registers it: connect first."""
    registered = []
    reconnecting_tool_decorator(lambda *_a, **_k: registered.append, cm)(name="protect_get_incident_evidence")(
        inspect.unwrap(incident_evidence.get_incident_evidence)
    )
    return await registered[0](**WINDOW)


@pytest.mark.asyncio
async def test_an_evidence_call_while_the_controller_hangs_fails_within_the_bound_and_reads_nothing(monkeypatch):
    collector = AsyncMock()
    monkeypatch.setattr(incident_evidence, "collect_protect_incident_evidence", collector)
    with SilentPort() as silent:
        cm = pcm.ProtectConnectionManager(
            host="127.0.0.1",
            username=FAKE_USERNAME,
            password=FAKE_PASSWORD,
            port=silent.port,
            verify_ssl=False,
            bootstrap_refresh_seconds=0,
        )
        cm._attempt.wait_seconds = WAIT_SECONDS
        cm._reconnect_attempt_timeout = 5.0
        monkeypatch.setattr(incident_evidence, "connection_manager", cm)
        startup = asyncio.create_task(cm.initialize())
        await asyncio.sleep(0)
        try:
            started = time.monotonic()
            result = await _call_evidence(cm)
            elapsed = time.monotonic() - started
        finally:
            await cm.close()
            await asyncio.gather(startup, return_exceptions=True)

    assert elapsed < WAIT_SECONDS + 1.0
    assert result["success"] is False
    assert result["error"].startswith(
        "Failed to collect incident evidence: UniFi Protect connection is not ready: still connecting"
    )
    # Nothing was collected: no request was sent and no budget was counted.
    collector.assert_not_awaited()
