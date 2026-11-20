"""Controller requests inside a held write are bounded by the write's hold budget.

Network sends through aiounifi and Access through its proxy session, neither
of which has a request timeout shorter than aiohttp's five-minute default. Inside
a held write each request is cut off when the write's budget runs out, and the
caller is told the change may or may not have been applied. Outside a write
nothing changes.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiounifi.models.api import ApiRequest
from unifi_core.access.managers.connection_manager import AccessConnectionManager
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.operation_gate import GateSettings, OperationGate, WriteRequestTimeout


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        return self.value

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


def _nearly_spent_gate() -> tuple[OperationGate, _Clock]:
    clock = _Clock()
    return OperationGate(GateSettings(hold_budget_seconds=10), name="test", clock=clock), clock


class _Session:
    closed = False

    async def close(self):
        return None


def _network(slow_seconds: float) -> ConnectionManager:
    manager = ConnectionManager("controller.example", "admin", "pw")
    controller = MagicMock()
    controller.connectivity.config.session = _Session()
    controller.connectivity.is_unifi_os = True

    async def _request(api_request):
        await asyncio.sleep(slow_seconds)
        return {"data": [{"ok": True}]}

    controller.request = _request
    manager.controller = controller
    manager._aiohttp_session = controller.connectivity.config.session
    manager._initialized = True
    manager._auth_generation = 1
    return manager


@pytest.mark.parametrize("path", ["/rest/networkconf/abc", "/set/setting/mgmt"])
async def test_network_request_inside_a_held_write_stops_at_the_budget(path) -> None:
    manager = _network(slow_seconds=1)
    gate, clock = _nearly_spent_gate()

    async with gate.write():
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout, match="may or may not have been applied"):
            await manager.request(ApiRequest(method="put", path=path, data={"name": "x"}))


async def test_network_request_outside_a_write_is_not_bounded() -> None:
    manager = _network(slow_seconds=0.02)
    gate, clock = _nearly_spent_gate()
    async with gate.read():
        clock.value = 9.999
        assert await manager.request(ApiRequest(method="get", path="/rest/networkconf")) == [{"ok": True}]


def _access_response() -> AsyncMock:
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"code": "SUCCESS", "data": {"ok": True}})

    async def _slow_enter(*_args):
        await asyncio.sleep(1)
        return response

    response.__aenter__ = _slow_enter
    response.__aexit__ = AsyncMock(return_value=False)
    return response


async def test_access_proxy_request_inside_a_held_write_stops_at_the_budget() -> None:
    cm = AccessConnectionManager(host="access.example", username="admin", password="pw")
    session = MagicMock()
    session.request = MagicMock(return_value=_access_response())
    cm._proxy_session = session
    cm._proxy_available = True
    cm._csrf_token = "csrf"
    gate, clock = _nearly_spent_gate()

    async with gate.write():
        clock.value = 9.99
        with pytest.raises(WriteRequestTimeout):
            await cm.proxy_request("PUT", "doors/1", json={"name": "x"})
    # The proxy session survives: a timed-out write is not an auth failure.
    assert cm._proxy_session is session
