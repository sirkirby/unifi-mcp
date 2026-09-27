"""v2 system-log capability probe: recovery, unsupported detection, cooldown, coalescing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.errors import RequestError, ResponseError, Unauthorized
from unifi_core.network.managers import event_manager as em
from unifi_core.network.managers.event_manager import EventManager

V2_OK = {"logs": []}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    value = Clock()
    monkeypatch.setattr(em, "_monotonic", value)
    return value


@pytest.fixture
def connection() -> MagicMock:
    value = MagicMock()
    value.site = "default"
    value.request = AsyncMock()
    return value


@pytest.fixture
def manager(connection: MagicMock, clock: Clock) -> EventManager:
    return EventManager(connection)


def _http(status: int) -> ResponseError:
    return ResponseError(f"Call https://ctl/proxy/network/v2/api/site/default/system-log/count received {status}")


def _paths(connection: MagicMock) -> list[str]:
    return [call.args[0].path for call in connection.request.call_args_list]


@pytest.mark.asyncio
async def test_transient_failure_then_recovery(manager, connection, clock):
    connection.request.side_effect = [RequestError("timeout"), {"count": 1}]

    assert await manager._ensure_api_version() is False
    assert manager._use_v2 is None  # not cached

    clock.now += em._V2_PROBE_BACKOFF_BASE
    assert await manager._ensure_api_version() is True
    assert manager._use_v2 is True
    assert manager._v2_probe_error is None
    assert _paths(connection) == ["/system-log/count", "/system-log/count"]


@pytest.mark.asyncio
async def test_unsupported_controller_is_cached(manager, connection, clock):
    connection.request.side_effect = _http(404)

    assert await manager._ensure_api_version() is False
    assert manager._use_v2 is False
    clock.now += 10_000
    assert await manager._ensure_api_version() is False
    assert connection.request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [Unauthorized("nope"), _http(401), _http(429), _http(500), TimeoutError()])
async def test_inconclusive_errors_never_mark_unsupported(manager, connection, error):
    connection.request.side_effect = error

    assert await manager._ensure_api_version() is False
    assert manager._use_v2 is None
    assert manager._v2_probe_error


@pytest.mark.asyncio
async def test_cooldown_suppresses_probes_and_backoff_is_bounded(manager, connection, clock):
    connection.request.side_effect = RequestError("down")

    await manager._ensure_api_version()
    await manager._ensure_api_version()
    assert connection.request.await_count == 1  # inside cooldown

    delays = []
    for _ in range(10):
        clock.now = manager._v2_next_probe_at
        await manager._ensure_api_version()
        delays.append(manager._v2_next_probe_at - clock.now)
    assert delays[0] == em._V2_PROBE_BACKOFF_BASE * 2
    assert max(delays) == em._V2_PROBE_BACKOFF_MAX


@pytest.mark.asyncio
async def test_concurrent_callers_share_one_probe(manager, connection):
    gate = asyncio.Event()

    async def slow(_request):
        await gate.wait()
        return {"count": 1}

    connection.request.side_effect = slow
    tasks = [asyncio.create_task(manager._ensure_api_version()) for _ in range(5)]
    await asyncio.sleep(0)
    gate.set()

    assert await asyncio.gather(*tasks) == [True] * 5
    assert connection.request.await_count == 1


@pytest.mark.asyncio
async def test_failed_probe_serves_legacy_then_v2_after_cooldown(manager, connection, clock):
    connection.request.side_effect = [RequestError("blip"), [], {"count": 1}, V2_OK]

    assert await manager.get_events() == []
    assert "/stat/event" in connection.request.call_args_list[1].args[0].path

    clock.now += em._V2_PROBE_BACKOFF_BASE
    await manager.get_events()
    assert manager._use_v2 is True


@pytest.mark.asyncio
async def test_backoff_saturates_over_thousands_of_failures(manager, connection, clock):
    connection.request.side_effect = RequestError("down")

    for _ in range(3000):
        clock.now = manager._v2_next_probe_at
        await manager._ensure_api_version()

    assert manager._v2_next_probe_at - clock.now == em._V2_PROBE_BACKOFF_MAX
    assert manager._use_v2 is None


@pytest.mark.asyncio
async def test_unsupported_probe_leaves_no_probe_failure_diagnostic(manager, connection):
    connection.request.side_effect = _http(404)

    await manager._ensure_api_version()

    assert manager._v2_probe_error is None
    error = RuntimeError("legacy 404")
    assert manager._explain_legacy_failure("/stat/event", error) is error
